"""Every skip in this suite must be REGISTERED with a reason.

Why this gate exists (SG-4, 2026-07-20): a false-ready shipped because
`kokoro-onnx` caps at Python <3.14 and the ONLY place that constraint
lived was a test skip reason — `zing doctor` reported voiceover ready
on a Python that could not run it, and a user would have found out at
render time. A known constraint that exists only in a test skip is a
constraint the PRODUCT does not know.

This cannot prove a skip is harmless. It makes the set VISIBLE and
makes adding one deliberate: the registry entry is where the author is
asked whether the product surface knows what the test knows. That is
the "no silent caps" doctrine applied to skipped coverage.

Static by design. The first draft shelled out to pytest to read real
SKIPPED lines — which recursed (the suite runs this file, which ran the
suite) and hung for ten minutes. Reading the sources is both correct
for authored skips and vastly cheaper.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

# Authored skip reason (substring) -> why it is legitimate AND where the
# product surfaces the same fact, or an explicit note that it needs none.
REGISTERED_SKIPS = {
    "FFmpeg not installed": (
        "generated source-map media requires the encoder. PRODUCT SURFACE: zing doctor "
        "reports FFmpeg availability; the strict FFmpeg gate forbids this skip."
    ),
    "real-model test requires explicit opt-in": (
        "normal pytest never loads real Whisper, OCR, YuNet or Kokoro models without an explicit test opt-in. "
        "PRODUCT SURFACE: docs/DEVELOPER-GUIDE.md lists each environment variable; the real-ASR fixture "
        "also uses local_files_only=True. Production feature availability remains exposed by zing doctor."
    ),
    "opt in with ZING_REAL_TRANSITIONS=1": (
        "the real transition regression reads licensed, hash-pinned local media only. "
        "PRODUCT SURFACE: tools/eval/TRANSITIONS.md documents the opt-in and media root; "
        "the evaluator names the explicit download command. Production detection needs "
        "only the user's video and FFmpeg, not these evaluation assets."
    ),
    "pinned real classroom clip absent": (
        "evaluation media is deliberately excluded from Git and never downloaded by tests. "
        "PRODUCT SURFACE: run_transition_eval reports the missing pinned clip and explicit "
        "run_real_eval.py --download command; TRANSITIONS.md documents local setup."
    ),
    "real-media test needs ffmpeg and ffprobe": (
        "the separately opted-in media regression needs the decoder binaries. "
        "PRODUCT SURFACE: doctor names FFmpeg as required and the transition probe "
        "raises an explicit executable-not-found error. The 332 mandatory FFmpeg "
        "tests remain in the no-skip CI gate."
    ),
    "set ZING_CG2_REAL_ROOT": (
        "the opt-in caption negative reads pinned real media from an explicitly supplied directory. "
        "PRODUCT SURFACE: docs/CAPTION-GEOMETRY.md describes the offline real replay; "
        "doctor and caption_models report missing local OCR assets. No product cap is hidden."
    ),
    "SEC1-OCR: original OCR text is not redistributed": (
        "five historical fuzzy-clustering cases require third-party transcript "
        "text without recorded redistribution permission. PUBLIC SURFACE: NOTICE.md, "
        "tests/fixtures/research/README.md and tests/PRIVATE-FIXTURES.md "
        "state that lexical accuracy is not rerun. Generated overlay tests cover "
        "behavior; token counts/hashes keep the baseline scorer reproducible. "
        "No production capability is disabled. Restore empirical checks only "
        "with a licensed, independently labeled replacement corpus."
    ),
    "caption geometry OCR models unavailable": (
        "real caption geometry acceptance requires pinned local OCR assets. PRODUCT "
        "SURFACE: doctor and study name the explicit caption_models --fetch command. "
        "CI provisions them before the FFmpeg gate, which forbids these skips."
    ),
    "set ZING_REQUIRE_YUNET=1": (
        "real YuNet inference requires an explicitly fetched model and public-domain "
        "fixture. PRODUCT SURFACE: layout and doctor name the optional runtime and "
        "fetch-model command; normal planning never downloads assets."
    ),
    "optional real HyperFrames check": (
        "requires explicit ZING_REQUIRE_HYPERFRAMES=1 plus Node, the sidecar, "
        "Chrome, FFmpeg and a fetched OFL font. PRODUCT SURFACE: the adapter "
        "and zing doctor check local prerequisites and give setup remedies."
    ),
    "set ZING_REQUIRE_HYPERFRAMES=1 for real alpha render/composite": (
        "the P10a/P10b pixel acceptance needs the pinned local sidecar, browser, FFmpeg "
        "and NumPy from the existing color extra; it uses the bundled OFL font. "
        "PRODUCT SURFACE: v2 render preflight, the standalone adapter and doctor report missing render "
        "tools; docs/HYPERFRAMES-V2.md records setup and the separate opt-in gate."
    ),
    "optional real Kokoro check": (
        "the real synthesis check needs the optional kokoro-onnx runtime and "
        "model assets. PRODUCT SURFACE: tts_status() checks runtime and asset "
        "availability; doctor names the running Python and install action."
    ),
    "OpenTimelineIO optional runtime is not installed": (
        "OTIO is an optional extra. PRODUCT SURFACE: h_export_otio returns "
        "an actionable envelope naming myzing[render] when the import fails."
    ),
    "mcp SDK not installed": (
        "the MCP SDK is an optional extra. PRODUCT SURFACE: `zing serve-mcp` "
        "exits 2 with the install command; --print-config prints a NOTE."
    ),
    "ffmpeg unavailable": (
        "the real-transcription test needs the ffmpeg BINARY. PRODUCT "
        "SURFACE: ffmpeg is doctor's one REQUIRED check — missing it exits "
        "1 with the platform install command, and study_video refuses "
        "before dispatch."
    ),
    "Windows kernel32 branch": (
        "platform-specific F-03 liveness branch; the cross-platform "
        "assertions run everywhere and windows-latest CI executes this one. "
        "PRODUCT SURFACE: none needed — a platform detail, not a "
        "user-visible capability."
    ),
    "install myzing[memes] for render tests": (
        "meme rendering needs the optional Pillow extra; the skip is per test. "
        "CI installs the memes extra, and required FFmpeg gates fail if it is missing. "
        "PRODUCT SURFACE: doctor.check_pillow and both meme renderers' install hints name myzing[memes]."
    ),
    "Windows PowerShell mutation": (
        "the hermetic Chocolatey retry mutation creates Windows command "
        "shims. windows-latest CI executes both cases; the workflow-shape "
        "assertion still runs on every OS. PRODUCT SURFACE: none needed — "
        "this tests a Windows CI dependency installer, not a user capability."
    ),
    "Windows sharing violation on rename": (
        "only Windows refuses to rename a file another process has open, so only "
        "there does project-lock release retry; POSIX renames never hit it. "
        "windows-latest CI executes this case. PRODUCT SURFACE: none needed — a "
        "platform detail of lock cleanup, not a user-visible capability."
    ),
    "Windows status-reader sharing": (
        "Windows can briefly refuse replacement while a Studio status reader has the "
        "old JSON file open; POSIX permits that replacement. windows-latest runs this "
        "regression. PRODUCT SURFACE: studio.models.write_json retries the transient "
        "sharing failure so polling does not turn a running Studio job into a failure."
    ),
    "local OCR runtime/models are not installed": (
        "photo text is optional evidence for offline meme lines; it needs the study OCR runtime and "
        "verified local models, and the test never downloads them. PRODUCT SURFACE: doctor's ocr and "
        "caption_geometry checks; the still index records text=null when OCR was unavailable, and "
        "docs/MEMES.md says so."
    ),
    "FFmpeg is not on PATH": (
        "the real HEIC round trip encodes its fixture with the local FFmpeg (libx265). PRODUCT SURFACE: "
        "doctor's required ffmpeg check and optional heic check; HEIC decoding names the missing FFmpeg "
        "and the remedy. The no-skip FFmpeg gate runs the HEIF support test, which never skips."
    ),
}

# importorskip() names an optional MODULE rather than a constraint; the
# module name IS the reason, and each is a declared optional extra.
REGISTERED_IMPORTORSKIP = {
    "numpy", "cv2", "scenedetect", "faster_whisper", "mcp", "rapidocr", "onnxruntime",
    # Optional myzing[memes] and myzing[fonts]; doctor.check_pillow,
    # doctor.check_fonts and the command install hints expose the same gap.
    "PIL.Image",
}


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def collect_authored_skips() -> list[tuple[str, str]]:
    """(file, reason) for every skip reason written in a test source."""
    found: list[tuple[str, str]] = []
    for path in sorted([*TESTS.glob("test_*.py"), TESTS / "conftest.py"]):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            if name.endswith("importorskip"):
                arg = _literal(node.args[0]) if node.args else None
                if arg:
                    found.append((path.name, f"importorskip:{arg}"))
                continue
            if not (name.endswith(".skip") or name.endswith(".skipif")):
                continue
            for kw in node.keywords:
                if kw.arg == "reason":
                    text = _literal(kw.value)
                    if text:
                        found.append((path.name, text))
            for arg in node.args:
                text = _literal(arg)
                if text and name.endswith(".skip"):
                    found.append((path.name, text))
    return found


def test_every_authored_skip_is_registered():
    unregistered = []
    for filename, reason in collect_authored_skips():
        if reason.startswith("importorskip:"):
            if reason.split(":", 1)[1] not in REGISTERED_IMPORTORSKIP:
                unregistered.append((filename, reason))
        elif not any(key in reason for key in REGISTERED_SKIPS):
            unregistered.append((filename, reason))
    assert not unregistered, (
        "unregistered skip(s) — add each to this file's registry with WHY it "
        "is legitimate and WHERE the product surfaces the same fact (a "
        "constraint known only to a test is one the product does not know): "
        f"{unregistered}"
    )


def test_registry_has_no_stale_entries():
    """A registry that outlives its skips is its own kind of lie."""
    reasons = [reason for _, reason in collect_authored_skips()]
    stale = [key for key in REGISTERED_SKIPS if not any(key in r for r in reasons)]
    stale += [
        module for module in REGISTERED_IMPORTORSKIP
        if f"importorskip:{module}" not in reasons
    ]
    assert not stale, f"registered skip(s) that no longer occur — delete: {stale}"
