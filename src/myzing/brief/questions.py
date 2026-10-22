"""One question/default contract for plain terminals and MCP clients."""

from __future__ import annotations

import json
import re
from typing import TextIO

from .models import Brief, BriefError


# Six topics; small follow-ups keep ordinary answers free of JSON syntax.
TOPICS = (
    ("What should this edit do for someone?", (
        ("purpose", "What should they take away?", "text"),
        ("audience", "Who are we talking to?", "text"))),
    ("Where will they watch it?", (
        ("platform", "Which platform?", "text"),
        ("aspect", "Which frame: 9:16, 1:1, or 16:9?", "choice"),
        ("target_length_seconds", "How many seconds do we have? (up to 60)", "seconds"))),
    ("What must make the cut, and what stays out?", (
        ("must_keep", "What must stay?", "moments"),
        ("forbidden", "What must stay out?", "moments"))),
    ("Let's get the words right.", (
        ("caption_language", "Caption language? ('original' keeps the spoken language; 'none' disables captions)", "text"),
        ("exact_spellings", "Which names or terms need exact spelling? Separate with semicolons.", "list"))),
    ("What should we hear?", (
        ("music", "Music: supplied files, none, or keep original audio?", "audio"),
        ("sfx", "SFX: supplied files, none, or keep original audio?", "audio"))),
    ("How closely should we follow the reference?", (
        ("reference_match", "Choose exact, pacing only, or recommend.", "choice"),)),
)


def brief_questions() -> dict:
    defaults = Brief().to_dict()
    return {
        "version": 1,
        "instructions": "Every answer is optional. Enter skips to the printed default; omitted JSON keys do the same.",
        "questions": [
            {"topic": topic, "fields": [
                {"key": key, "prompt": prompt, "format": kind, "default": defaults[key]}
                for key, prompt, kind in group]}
            for topic, group in TOPICS
        ],
        "answer_examples": {
            "framing": "auto",
            "aspects": ["16:9", "1:1", "9:16"],
            "framing_max_upscale": 2.5,
            "must_keep": [{"clip": "clip ID or path", "start": 0, "end": 2}, {"phrase": "exact words"}],
            "forbidden": [], "exact_spellings": ["Zoë", "Zing"],
            "music": {"source": "supplied files", "files": ["audio/bed.wav"]},
            "sfx": {"source": "none"},
        },
        "optional_fields": [{"key": "framing", "default": "auto", "choices": ["auto", "fit", "fill", "reframe", "blurfill"],
                             "description": "Auto crops only within loss, subject-coverage and enlargement limits; otherwise blurfill."},
                            {"key": "aspects", "default": [], "description": "Delivery list: 16:9, 1:1, 9:16. Empty uses aspect."},
                            {"key": "framing_max_upscale", "default": 2.5, "description": "Configurable auto crop enlargement limit, 1-16x."}],
    }


def _seconds(value: str) -> float:
    parts = value.split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError("use seconds or hh:mm:ss")
    nums = [float(p) for p in parts]
    if len(nums) > 1 and (any(n < 0 for n in nums) or any(n >= 60 for n in nums[1:])):
        raise ValueError("clock minutes/seconds must be below 60")
    return sum(n * 60 ** i for i, n in enumerate(reversed(nums)))


def parse_answer(raw: str, kind: str):
    if kind == "seconds":
        try:
            return float(raw)
        except ValueError as exc:
            raise BriefError("target_length_seconds: enter a number of seconds, such as 30.") from exc
    if kind == "list":
        return json.loads(raw) if raw.startswith("[") else [s.strip() for s in raw.split(";")]
    if kind == "moments":
        if raw.lower() == "none":
            return []
        if raw.startswith("["):
            return json.loads(raw)
        result = []
        # Semicolons inside a quoted phrase are preserved.
        for part in re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', raw):
            part = part.strip()
            if part.startswith('"') and part.endswith('"'):
                result.append({"phrase": json.loads(part)})
            else:
                match = re.fullmatch(r"(.+)\s+@\s+([\d.:]+)\s*-\s*([\d.:]+)", part)
                if not match:
                    raise BriefError('Use clip.mp4 @ 0-2; "exact phrase" (or a JSON list).')
                result.append({"clip": match[1].strip(), "start": _seconds(match[2]), "end": _seconds(match[3])})
        return result
    if kind == "audio":
        if raw.startswith("{"):
            return json.loads(raw)
        if raw.startswith("supplied files:"):
            return {"source": "supplied files", "files": [s.strip() for s in raw.split(":", 1)[1].split(";")]}
        return {"source": raw, "files": []}
    return raw


def interview(project, stdin: TextIO, stdout: TextIO) -> Brief:
    from .api import validate_for_project

    answers = {}
    print("Let's find the edit. Six topics; Enter accepts each printed default.", file=stdout)
    for index, question in enumerate(brief_questions()["questions"], 1):
        print(f"\n{index}. {question['topic']}", file=stdout)
        for item in question["fields"]:
            key, kind = item["key"], item["format"]
            if kind == "moments":
                print('  Use clip.mp4 @ 0-2; "exact phrase". Times are source seconds or mm:ss.', file=stdout)
            if kind == "audio":
                print("  For files: supplied files: audio/bed.wav; audio/hit.wav (paths relative to project).", file=stdout)
            while True:
                default = json.dumps(item["default"], ensure_ascii=False)
                print(f"  {item['prompt']} [default: {default}]\n> ", end="", file=stdout, flush=True)
                line = stdin.readline()
                if line == "":
                    raise BriefError("Input ended before the interview finished; brief unchanged. Rerun, or use --answers '{}'.")
                raw = line.strip()
                try:
                    candidate = {**answers, key: parse_answer(raw, kind) if raw else item["default"]}
                    brief = validate_for_project(project, Brief.from_answers(candidate))
                except (ValueError, OverflowError) as exc:
                    print(f"  {exc} Please try that answer again.", file=stdout)
                    continue
                answers = {k: brief.to_dict()[k] for k in candidate}
                break
    return Brief.from_answers(answers)
