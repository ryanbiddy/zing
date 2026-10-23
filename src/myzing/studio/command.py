"""A one-question-at-a-time studio using ordinary UTF-8 stdin/stdout."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time

from . import flow, jobs
from .models import SESSION_NAME, Session, load_session, read_json, save_session


def show_question(q, out):
    print("\n" + q["prompt"], file=out)
    for i, option in enumerate(q["options"], 1):
        label = f"{option['value']}. " if q["id"] == "path" else ""
        print(f"  {i}. {label}{option['label']}", file=out)
    value = q["recommended"]
    display = ",".join(value) if isinstance(value, list) else "yes" if value is True else "no" if value is False else value
    print(f"Recommended: {display if value is not None else 'supply a path or answer (unknown)'}", file=out)
    print(q["reason"], file=out)
    print("Enter accepts | ? explains | b goes back | q saves and quits", file=out)
    print("> ", end="", file=out, flush=True)


def show_plan(plan, out):
    print(f"\nPlan: {plan['title']}", file=out)
    if plan["aspects"]:
        print("Shapes: " + ", ".join(plan["aspects"]), file=out)
    for i, step in enumerate(plan["steps"], 1):
        print(f"  {i}. {step}", file=out)
    print(f"Estimated steps: {len(plan['steps'])}. Time: {plan['estimate']['basis']}", file=out)
    print("Downloads: " + (", ".join(plan["downloads"]) or "none"), file=out)
    print("Output folder: " + plan["output_folder"], file=out)
    for warning in plan["warnings"]:
        print("Note: " + warning, file=out)


def show_result(result, out):
    print("\nStudio: " + result.get("status", "failed"), file=out)
    if result.get("error"):
        print(result["error"], file=out)
    for path in result.get("outputs", []):
        print("Output: " + path, file=out)
    detail = result.get("result", {})
    if isinstance(detail.get("summary"), str):
        print(detail["summary"], file=out)
    for failure in detail.get("failures", []):
        print("Failed: " + json.dumps(failure, ensure_ascii=False), file=out)
    for shortage in detail.get("shortages", []):
        print("Shortage: " + json.dumps(shortage, ensure_ascii=False), file=out)
    warnings = result.get("warnings", [])
    # Failures and shortages above are never elided. Repeated per-clip geometry
    # stays in the saved result; keep a first-time creator's terminal readable.
    priority = ("blocked", "low-resolution", "phone captions need review", "could not", "unavailable", "missing", "unknown", "unverified")
    ordered = sorted(enumerate(warnings), key=lambda row: (
        next((rank for rank, word in enumerate(priority) if word in row[1].lower()), len(priority)), row[0]))
    for _, warning in ordered[:10]:
        print("Note: " + warning, file=out)
    if len(warnings) > 10:
        from pathlib import Path
        report = str(Path(result["project"]) / "studio-result.json") if result.get("project") else "the saved studio result"
        print(f"{len(warnings) - 10} more notes, including per-clip framing: {report}", file=out)
    for track in detail.get("advice", {}).get("tracks", []):
        print(f"{track['track']}: {track['rating']} ({track['score']}/100)", file=out)
        for reason in track.get("reasons", []):
            print("  " + (reason if isinstance(reason, str) else json.dumps(reason)), file=out)
    for action in result.get("next_actions", []):
        print("Next: " + action, file=out)


def _answer(q, raw):
    if raw == "":
        if q["recommended"] is None:
            raise ValueError("This answer is unknown; please supply it.")
        return q["recommended"]
    if raw.isdigit() and q["options"]:
        index = int(raw) - 1
        if 0 <= index < len(q["options"]):
            return q["options"][index]["value"]
    return raw


def run(argv):
    parser = argparse.ArgumentParser(prog="zing studio", description=__doc__)
    parser.add_argument("--resume", metavar="PROJECT")
    parser.add_argument("--answers", metavar="JSON_FILE", help="question IDs and answers; paths resolve from the current directory")
    parser.add_argument("--yes", action="store_true", help="confirm the displayed plan; does not grant download consent")
    parser.add_argument("--json", action="store_true", help="JSON Lines events: question, plan, progress, result")
    args = parser.parse_args(argv)
    session = Session()
    cache = {}

    def emit(event, data):
        if args.json:
            print(json.dumps({"event": event, **data}, ensure_ascii=False, allow_nan=False), flush=True)

    def persist(status=None):
        if "project" not in session.answers:
            session.answers["project"] = flow.default_project()
        if status:
            session.status = status
        return save_session(session.answers["project"], session)

    def pause():
        path = persist("paused")
        emit("paused", {"ok": True, "session": str(path), "project": session.answers["project"]})
        if not args.json:
            print(f"Saved: {path}\nContinue: zing studio --resume \"{path.parent}\"")
        return 0

    def back():
        if not session.history:
            print("Already at the first question.", file=sys.stderr)
            return
        key = session.history.pop()
        session.answers.pop(key, None)
        session.result = {}
        session.status = "interview"

    try:
        if args.resume:
            session = load_session(args.resume)
            # A moved folder remains the home of the resumed session.
            from pathlib import Path
            session.answers["project"] = str(Path(args.resume).expanduser().resolve())
        if args.answers:
            supplied = flow.normalize_answers(read_json(args.answers))
            session.answers.update(supplied)
            session.result = {}
        if session.status == "ready" and session.result and not args.answers and session.answers.get("path") != "a":
            from myzing.project.api import hash_file
            from pathlib import Path
            hashes = session.result.get("output_sha256", {})
            if hashes and all(Path(p).is_file() and hash_file(Path(p)) == digest for p, digest in hashes.items()):
                emit("result", session.result)
                if not args.json:
                    show_result(session.result, sys.stdout)
                return 0
        while True:
            try:
                step = flow.next_step(session.answers, cache=cache)
            except (ValueError, OSError, RuntimeError) as exc:
                if args.answers or args.json:
                    raise
                print(f"Cannot continue: {exc}\nType b to go back or q to save and quit.", flush=True)
                raw = sys.stdin.readline()
                if not raw or raw.strip() == "q":
                    return pause()
                if raw.strip() == "b":
                    back()
                continue
            session.answers = step["answers"]
            if step["status"] == "blocked":
                if args.answers or args.json:
                    emit("blocked", {"ok": False, **step})
                    if not args.json:
                        print(step["error"])
                    persist("planned")
                    return 2
                print(step["error"] + " Type b or q.", flush=True)
                raw = sys.stdin.readline()
                if not raw or raw.strip() == "q":
                    return pause()
                if raw.strip() == "b":
                    back()
                continue
            if step["status"] == "question":
                q = step["question"]
                if args.answers or args.json:
                    emit("question", {"ok": True, "question": q, "answers": session.answers})
                    if not args.json:
                        show_question(q, sys.stdout)
                    persist()
                    return 2
                session.questions_asked += 1
                show_question(q, sys.stdout)
                line = sys.stdin.readline()
                if not line or line.strip() == "q":
                    return pause()
                raw = line.strip()
                if raw == "?":
                    print(json.dumps(q["evidence"], indent=2, ensure_ascii=False))
                    continue
                if raw == "b" and q["id"] != "path":
                    back()
                    continue
                try:
                    session.answers[q["id"]] = flow.normalize(q["id"], _answer(q, raw))
                except (ValueError, OSError) as exc:
                    print(str(exc))
                    continue
                if q["id"] not in session.history:
                    session.history.append(q["id"])
                if "project" in session.answers:
                    persist()
                continue
            plan = step["plan"]
            persist("planned")
            emit("plan", {"ok": True, "plan": plan})
            if not args.json:
                show_plan(plan, sys.stdout)
            if not args.yes:
                if args.answers or args.json:
                    emit("confirmation_required", {"ok": True, "project": session.answers["project"], "hint": "Rerun with --yes after reviewing the plan."})
                    return 0
                print("\nRun this plan? Recommended: yes. The inputs and outputs above are ready for your review.\nEnter=yes | ? explains | b goes back | q saves and quits\n> ", end="", flush=True)
                line = sys.stdin.readline()
                if not line or line.strip().lower() in {"q", "no", "n"}:
                    return pause()
                if line.strip() == "b":
                    back()
                    continue
                if line.strip() == "?":
                    print(json.dumps(plan["evidence"], indent=2, ensure_ascii=False))
                    continue
                if line.strip().lower() not in {"", "y", "yes"}:
                    print("Enter yes to run, b to change an answer, or q to save.")
                    continue
            break
        persist("running")
        output_lock = threading.Lock()
        last_progress = time.monotonic()
        run_started = last_progress
        def progress(text):
            nonlocal last_progress
            with output_lock:
                last_progress = time.monotonic()
                emit("progress", {"step": text})
                if not args.json:
                    print("Working: " + text, flush=True)
        stop = threading.Event()
        def heartbeat():
            while not stop.wait(15):
                if time.monotonic() - last_progress >= 15:
                    progress(f"Still working ({time.monotonic() - run_started:.0f}s elapsed); Ctrl+C saves the session.")
        beat = threading.Thread(target=heartbeat, daemon=True)
        beat.start()
        try:
            if session.answers["path"] == "a":
                from .execute import run_confirmed
                result = run_confirmed(session.answers, progress=progress)
            else:
                result = jobs.execute(session.answers, progress=progress)
        finally:
            stop.set()
            beat.join(timeout=2)
        session.result = result
        persist(result["status"])
        emit("result", {**result, "questions_asked": session.questions_asked})
        if not args.json:
            show_result(result, sys.stdout)
        return 0 if result.get("ok") else 1
    except KeyboardInterrupt:
        return pause()
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        result = {"ok": False, "status": "failed", "error": str(exc)}
        emit("result", result)
        if not args.json:
            print("Studio: " + str(exc), file=sys.stderr)
        if "project" in session.answers:
            session.result = result
            try:
                persist("failed")
            except (ValueError, OSError):
                pass  # The error may be an input/output collision; preserve it.
        return 1
