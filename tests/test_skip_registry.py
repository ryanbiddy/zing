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
}

# importorskip() names an optional MODULE rather than a constraint; the
# module name IS the reason, and each is a declared optional extra.
REGISTERED_IMPORTORSKIP = {
    "numpy", "cv2", "scenedetect", "faster_whisper", "mcp",
}


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def collect_authored_skips() -> list[tuple[str, str]]:
    """(file, reason) for every skip reason written in a test source."""
    found: list[tuple[str, str]] = []
    for path in sorted(TESTS.glob("test_*.py")):
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
