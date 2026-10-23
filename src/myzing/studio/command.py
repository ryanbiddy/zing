"""A one-question-at-a-time studio using ordinary UTF-8 stdin/stdout."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import threading
import time

from . import flow, jobs
from .models import SESSION_NAME, Session, load_session, read_json, save_session


def show_question(q, out):
    print("\n" + q["prompt"], file=out)
    for i, option in enumerate(q["options"], 1):
        print(f"  {i}. {option['label']}", file=out)
    value = q["recommended"]
    display = ",".join(value) if isinstance(value, list) else "yes" if value is True else "no" if value is False else value
    display = next((f"{i} ({option['label']})" for i, option in enumerate(q["options"], 1)
                    if option["value"] == value), display)
    if value is not None:
        print(f"Recommended: {display}", file=out)
        print(q["reason"], file=out)
    # Nothing precedes the opening menu, so it does not advertise b.
    back = "" if q["id"] == "path" else "b goes back | "
    print(("Enter accepts | " if value is not None else "") + "? explains | " + back + "q saves and quits", file=out)
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
    if plan.get("style"):
        print("Style: " + "; ".join(f"{k}: {v}" for k, v in plan["style"].items()), file=out)
    for warning in plan["warnings"]:
        print("Note: " + warning, file=out)


def show_result(result, out):
    print("\nStudio: " + result.get("status", "failed"), file=out)
    if result.get("speech_setup"):
        setup = result["speech_setup"]
        print(setup.get("note") or f"Speech model: {setup['model']}; downloaded {setup['downloaded_bytes'] / 1e6:.1f} MB; "
              + ("SHA-256 verified" if setup.get("verified") else "existing local cache"), file=out)
    if result.get("error"):
        print(result["error"], file=out)
    if "creator_summary" in result:
        from pathlib import Path
        summary = result["creator_summary"]
        root = Path(summary["output_folder"])
        def relative(path):
            try:
                return str(Path(path).relative_to(root))
            except ValueError:
                return str(path)
        rows = summary["deliveries"]
        if rows:
            from textwrap import wrap
            shapes = list(dict.fromkeys(r["shape"] for r in rows))
            width = max(35, max((len(relative(r["file"])) for r in rows if r["file"]), default=0))
            print("\nDraft | " + " | ".join(shape.ljust(width) for shape in shapes), file=out)
            print("----- | " + " | ".join("-" * width for _ in shapes), file=out)
            for draft in dict.fromkeys(r["draft"] for r in rows):
                cells = []
                for shape in shapes:
                    row = next((r for r in rows if r["draft"] == draft and r["shape"] == shape), None)
                    cells.append([relative(row["file"]), *wrap("[" + row["status"] + "]", width)] if row and row["file"] else ["not rendered"])
                for line in range(max(map(len, cells))):
                    label = draft if line == 0 else ""
                    print(label.ljust(5) + " | " + " | ".join((cell[line] if line < len(cell) else "").ljust(width) for cell in cells), file=out)
        for line in summary.get("style_summary", []):
            print(line, file=out)
        for item in summary["highlights"]:
            print(item["label"] + ": " + relative(item["file"]), file=out)
        if summary["recommendation"]:
            print("\n" + summary["recommendation"], file=out)
        for note in summary["notes"]:
            print("Note: " + note, file=out)
        for track in result.get("result", {}).get("advice", {}).get("tracks", []):
            print(f"{track['track']}: {track['rating']} ({track['score']}/100)", file=out)
            for reason in track.get("reasons", []):
                print("  " + (reason if isinstance(reason, str) else json.dumps(reason)), file=out)
        print("Output folder: " + summary["output_folder"], file=out)
        print("Full result: " + summary["full_result"], file=out)
        for action in summary["next_actions"]:
            print("Next: " + action, file=out)
        return
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
            raise ValueError("Please type an answer or drag a local path here; Enter cannot fill this in.")
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
    cache = {"progress": lambda text: print(text, file=sys.stderr if args.json else sys.stdout, flush=True)}

    def emit(event, data):
        if args.json:
            print(json.dumps({"event": event, **data}, ensure_ascii=False, allow_nan=False), flush=True)

    created, saved = set(), [None]  # folders this session made; where it last saved

    def claim():
        session.answers["project"] = flow.reserve_project()
        created.add(session.answers["project"])

    def persist(status=None):
        if "project" not in session.answers:
            claim()
        if status:
            session.status = status
        project = session.answers["project"]
        if not pathlib.Path(project).exists():
            created.add(project)
        path = save_session(project, session)
        if saved[0] not in (None, project) and saved[0] in created:
            # The session moved (o, or path 4's move out of the video's folder).
            # Remove the stale copy only from a folder studio made and that
            # holds nothing else, so no one resumes the abandoned answers.
            old = pathlib.Path(saved[0])
            try:
                if [p.name for p in old.iterdir()] == [SESSION_NAME]:
                    (old / SESSION_NAME).unlink()
                    old.rmdir()
            except OSError:
                pass
        saved[0] = project
        return path

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
        value = session.answers.pop(key, None)
        if key == "speech_download" and value is False and session.history[-1:] == ["speech_model"]:
            # After a declined download, b means "choose another model", not
            # "ask the same download question again".
            key = session.history.pop()
            session.answers.pop(key, None)
        if key == "speech_model":
            session.answers.pop("speech_download", None)
            if "speech_download" in session.history:
                session.history.remove("speech_download")
        if key == "platform":
            session.answers.pop("aspects", None)
        if key == "reference" and "tone" not in session.history:
            session.answers.pop("tone", None)
        session.result = {}
        session.status = "interview"

    try:
        if args.resume:
            jobs.reconcile(args.resume)
            session = load_session(args.resume)
            # A moved folder remains the home of the resumed session.
            from pathlib import Path
            session.answers["project"] = str(Path(args.resume).expanduser().resolve())
        if args.answers:
            try:
                raw_answers = read_json(args.answers)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{args.answers} is not valid JSON ({exc}); write one object keyed by question IDs.") from None
            supplied = flow.normalize_answers(raw_answers)
            if "speech_model" in supplied and supplied["speech_model"] != session.answers.get("speech_model"):
                session.answers.pop("speech_download", None)
                if "speech_download" in session.history:
                    session.history.remove("speech_download")
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
            if "path" in session.answers and "project" not in session.answers:
                claim()  # before any question, so a second terminal picks another folder
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
                    print(q["reason"])
                    print(json.dumps(q["evidence"], indent=2, ensure_ascii=False))
                    continue
                if raw == "b" and q["id"] == "path":
                    # b always means back, even where a-f also name the menu rows.
                    print("Already at the first question. Type 2 to edit clips without a reference.")
                    continue
                if raw == "b":
                    back()
                    continue
                try:
                    value = _answer(q, raw)
                    if q["id"] == "speech_download":
                        value = value if type(value) is bool else str(value).lower() in {"yes", "y"}
                    session.answers[q["id"]] = flow.normalize(q["id"], value)
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
                tone_option = "t changes tone | " if session.answers["path"] in "ab" else ""
                print("\nRun this plan? Recommended: yes.\nEnter=yes | o changes output folder | " + tone_option + "? explains | b goes back | q saves and quits\n> ", end="", flush=True)
                line = sys.stdin.readline()
                if not line or line.strip().lower() in {"q", "no", "n"}:
                    return pause()
                if line.strip() == "b":
                    back()
                    continue
                if line.strip() == "?":
                    print(json.dumps(plan["evidence"], indent=2, ensure_ascii=False))
                    continue
                if line.strip() == "o" or (line.strip() == "t" and tone_option):
                    key = "project" if line.strip() == "o" else "tone"
                    print("Output folder:" if key == "project" else "Tone (natural, calm, energetic):", flush=True)
                    value = sys.stdin.readline()
                    if not value or value.strip() == "q":
                        return pause()
                    try:
                        chosen = flow.normalize(key, value.strip())
                        if key == "project":
                            # Check collisions now; a rejected folder must not
                            # replace the working one or receive the session.
                            flow.next_step({**session.answers, "project": chosen}, cache=cache)
                        session.answers[key] = chosen
                    except (ValueError, OSError) as exc:
                        print(f"{exc} Keeping {session.answers[key]}." if key == "project" else str(exc))
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
                from .presentation import progress_label
                label = progress_label(text, session.answers)
                if label:
                    emit("progress", {"step": label, "producer_step": text})
                    if not args.json:
                        print("Working: " + label, flush=True)
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
        if result.get("status") == "cancelled":
            if not args.json:
                print("Studio run cancelled", flush=True)
            return pause()  # Ctrl+C reached the match worker; say how to continue.
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
