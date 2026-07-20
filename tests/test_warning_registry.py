"""Registry gate for Lane A's problem-reporting warnings.

`study.md` tells judging AIs "`warnings[]` — **read this first**" and
"**warnings gate judgments**". So a warning that reports a problem
without saying what to DO or what it COST leaves both a human and a
model stranded at the exact moment they were told to pay attention.

Lane B enforced that for doctor as a live invariant (#354). Doing the
same here by pattern-matching source strings was tried and rejected:
a first pass flagged 19 warnings, and reading them cut it to 3 —
consequences get phrased as "fell back to sequential" or "treated as
empty", which no reasonable regex catches. A gate built on that
classifier would enshrine false positives and train editors to ignore
it.

So this follows the repo's existing skip-registry pattern
(tests/test_skip_registry.py): every problem-reporting warning is
listed here WITH the reason it is honest. The test does not judge the
wording — it fails when a NEW one appears unregistered, forcing the
author to make the same decision consciously rather than by omission.

Offline: reads source text only.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "myzing"
LANE_A = ("study", "profile", "assemble")

# Words that mark a warning as reporting a PROBLEM rather than a finding.
# ("raw: 3 dead-air spans" is a measurement result and needs no remedy.)
PROBLEM = re.compile(
    r"(skipped|failed|could not|unavailable|mismatch|ignored|inconclusive|empty:)",
    re.I,
)

# Each entry: a distinctive fragment of the warning -> why it is honest.
# A warning is honest when it names a FIX, a CONSEQUENCE, or is itself the
# consequence. Add new entries deliberately; that is the point of the file.
REGISTERED: dict[str, str] = {
    # Keys are fragments as they appear in ONE source literal. Warnings
    # split across line-continuations are keyed on their first fragment —
    # a lesson from building this: the registry must describe the code as
    # extracted, not as remembered.
    #
    # --- a FIX is named --------------------------------------------------
    "rapidocr/onnxruntime not installed": "names pip install myzing[study]",
    "faster-whisper not installed": "names pip install myzing[study]",
    "scenedetect not installed": "names pip install myzing[study]",
    "backend failed to start": "names zing doctor + likely cause",
    "whisper model '{name}' could not be": "names zing doctor + download/disk cause",
    "shot detection failed: {e} — scenedetect is installed but": "names zing doctor",
    "could not read this file; run 'zing doctor'": "continuation of the above",
    # --- a CONSEQUENCE is named ------------------------------------------
    "transition detection skipped: {exc} — transitions[]": "says NOT-MEASURED, not empty",
    "frame(s) could not be extracted": "says those shots carry no image",
    "loudness curve skipped: ffmpeg failed": "says music + keeper checks lose their basis",
    "batched transcription failed ({e}); fell back to": "names the fallback",
    "frame(s) failed to OCR and were treated": "says they were treated as empty",
    "music detection skipped: needs VAD speech spans": "names the missing input",
    "keeper derivation skipped": "explains the definitional dependency",
    "dead-air measurement skipped (VAD unavailable)": "names the missing input",
    "dead-air measurement, which was unavailable": "continuation of the above",
    "filler and repeated-take measurement skipped": "names the missing transcript",
    "no audio stream: transcription and audio measurements will be skipped":
        "states exactly what will be skipped",
    "falling back to fetch": "the fallback IS the consequence",
    "kept media integrity mismatch": "paired with the falling-back message",
    "integrity_mismatch": "contract reason code recorded in provenance",
    "kept_media ignored": "the ignoring IS the consequence",
    "normalization thresholds, so normalization was skipped":
        "states the residual risk explicitly",
    "could not verify constant frame timing": "states the residual risk",
    # --- the warning IS the finding; a remedy would be invented ----------
    "music detection inconclusive": "an honest unknown, not a fault",
    "music rate: inconclusive": "profile roll-up of the same unknown",
    "caption OCR skipped: unknown duration": "broken input, cause stated",
    "caption OCR failed while reading frames": "decode fault, exception carried",
    "speech ratio skipped: VAD failed": "cause carried in the message",
    "transcription failed: {e}": "cause carried in the message",
    "loudness curve skipped: {e}": "ToolMissing carried in the message",
    "loudness curve empty": "names missing/unreadable audio as the cause",
    "transition audio alignment skipped": "names the decode failure",
    "kept media unavailable": "paired with the falling-back message",
    "kept media failed probe": "paired with the falling-back message",
}


def _warning_strings() -> list[tuple[str, str]]:
    """Every string literal in a warning-appending call, per module."""
    out: list[tuple[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path).replace("\\", "/")
        if not any(f"/{pkg}/" in rel for pkg in LANE_A):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not any(
                key in line
                for key in ("warnings.append", "result.warnings =", "notes.append")
            ):
                continue
            blob = " ".join(x.strip() for x in lines[i : i + 8])
            for literal in re.findall(r'"([^"]{15,})"', blob):
                out.append((path.name, literal))
    return out


def test_every_problem_reporting_warning_is_registered() -> None:
    unregistered = sorted({
        f"{module}: {text[:70]}"
        for module, text in _warning_strings()
        if PROBLEM.search(text)
        and not any(key in text for key in REGISTERED)
    })
    assert not unregistered, (
        "unregistered problem-reporting warning(s). Add each to "
        "REGISTERED in this file with WHY it is honest — a fix named, a "
        "consequence named, or the warning IS the consequence. If it is "
        "none of those, the warning strands its reader and should say "
        f"more instead:\n  " + "\n  ".join(unregistered)
    )


def test_registry_has_no_stale_entries() -> None:
    """A registry that outlives its warnings is its own kind of lie."""
    all_text = " ".join(text for _, text in _warning_strings())
    stale = sorted(key for key in REGISTERED if key not in all_text)
    assert not stale, (
        "registry entries with no matching warning — remove them so the "
        f"file keeps describing the code: {stale}"
    )
