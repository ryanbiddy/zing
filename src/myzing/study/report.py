"""breakdown.md renderer: the human-readable edit breakdown.

Pure function of a Breakdown — no I/O, no judgment. Facts only: shot
table, pacing, the first-3-seconds anatomy (what a viewer sees/hears
before deciding to keep watching), captions, audio, and every measurement
warning. What the numbers MEAN (hook type, why it works) belongs to the
AI over MCP, not this file.
"""

from __future__ import annotations

from myzing.schemas import Breakdown, CaptionEvent, Shot, Word

from . import formats


def render_markdown(b: Breakdown) -> str:
    parts = [
        _header(b),
        _pacing(b),
        _first_seconds(b),
        _shot_table(b.shots),
        _captions(b.captions),
        _audio(b),
        _warnings(b.warnings),
    ]
    return "\n\n".join(p for p in parts if p) + "\n"


def _header(b: Breakdown) -> str:
    m = b.meta
    title = m.title or m.source_url
    lines = [f"# Edit breakdown — {title}"]
    facts = [
        f"platform: {m.platform}",
        f"duration: {m.duration:.1f}s",
        f"{m.width}x{m.height} @ {m.fps:g} fps",
    ]
    if m.author:
        facts.insert(1, f"author: {m.author}")
    lines.append(" · ".join(facts))
    lines.append(f"source: {m.source_url}")
    return "\n".join(lines)


def _pacing(b: Breakdown) -> str:
    if not b.shots:
        return "## Pacing\n\n(no shot data — see warnings)"
    cuts = max(0, len(b.shots) - 1)
    lines = [
        "## Pacing",
        "",
        f"- {len(b.shots)} shots, {cuts} cuts, "
        f"avg shot {b.avg_shot_duration:.2f}s",
    ]
    if b.cuts_per_10s:
        windows = " ".join(f"{c:g}" for c in b.cuts_per_10s)
        lines.append(f"- cuts per 10s window: {windows}")
        fastest = max(range(len(b.cuts_per_10s)), key=b.cuts_per_10s.__getitem__)
        lines.append(
            f"- densest window: {fastest * 10}-{fastest * 10 + 10}s "
            f"({b.cuts_per_10s[fastest]:g} cuts)"
        )
    return "\n".join(lines)


def _first_seconds(b: Breakdown) -> str:
    window = formats.hook_window_s(b.meta.duration)
    lines = [f"## First {window:.0f} seconds", ""]
    shots = [s for s in b.shots if s.start < window]
    words = [w for w in b.words if w.start < window]
    caps = [c for c in b.captions if c.start < window]

    if shots:
        described = ", ".join(_shot_brief(s) for s in shots)
        lines.append(f"- shots: {described}")
    else:
        lines.append("- shots: (none measured)")

    if words:
        spoken = " ".join(w.text for w in words)
        lines.append(f'- spoken: "{spoken}"')
    else:
        lines.append("- spoken: (nothing transcribed in this window)")

    if caps:
        for c in caps:
            lines.append(
                f'- on-screen text {c.start:.2f}-{c.end:.2f}s: "{c.text}"'
            )
    else:
        lines.append("- on-screen text: (none observed)")
    return "\n".join(lines)


def _shot_brief(s: Shot) -> str:
    return f"#{s.index} ({s.start:.2f}-{s.end:.2f}s)"


def _shot_table(shots: list[Shot]) -> str:
    if not shots:
        return ""
    lines = [
        "## Shots",
        "",
        "| # | start | end | duration | keyframe |",
        "|---|-------|-----|----------|----------|",
    ]
    for s in shots:
        lines.append(
            f"| {s.index} | {s.start:.2f} | {s.end:.2f} | "
            f"{s.duration:.2f}s | {s.keyframe or '—'} |"
        )
    return "\n".join(lines)


def _captions(captions: list[CaptionEvent]) -> str:
    lines = ["## Captions", ""]
    if not captions:
        lines.append("(no on-screen text observed — see warnings for OCR "
                      "sampling limits)")
        return "\n".join(lines)
    style = _caption_style(captions)
    if style:
        lines.append(style)
        lines.append("")
    lines.append("| start | end | text | pos | conf |")
    lines.append("|-------|-----|------|-----|------|")
    for c in captions:
        lines.append(
            f"| {c.start:.2f} | {c.end:.2f} | {c.text} | {c.position} | "
            f"{c.confidence:.2f} |"
        )
    return "\n".join(lines)


def _caption_style(captions: list[CaptionEvent]) -> str:
    n = len(captions)
    caps_frac = sum(c.all_caps for c in captions) / n
    wv = sorted(c.words_visible for c in captions)[n // 2]
    from collections import Counter
    pos = Counter(c.position for c in captions).most_common(1)[0][0]
    bits = [
        f"style: mostly {pos}",
        "ALL CAPS" if caps_frac > 0.6 else "mixed case",
        f"~{wv} word(s) visible at a time",
    ]
    return "- " + ", ".join(bits)


def _audio(b: Breakdown) -> str:
    a = b.audio
    lines = ["## Audio", ""]
    lines.append(
        f"- speech: {a.speech_ratio:.0%} of runtime"
        + (" (voice present)" if a.has_voiceover else " (no meaningful speech)")
    )
    music = "yes" if a.has_music else "no"
    lines.append(
        f"- music bed: {music} (confidence {a.music_confidence:.2f})"
    )
    if a.loudness_curve:
        peak = max(a.loudness_curve)
        quiet = min(a.loudness_curve)
        lines.append(
            f"- loudness (RMS dBFS, 1s buckets): peak {peak:.1f}, "
            f"quietest {quiet:.1f}, {len(a.loudness_curve)} samples"
        )
    if b.words:
        low_conf = sum(1 for w in b.words if w.confidence < 0.5)
        if low_conf:
            lines.append(
                f"- transcript: {len(b.words)} words, {low_conf} low-confidence"
            )
        else:
            lines.append(f"- transcript: {len(b.words)} words")
    return "\n".join(lines)


def _warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    lines = ["## Measurement notes", ""]
    lines += [f"- {w}" for w in warnings]
    return "\n".join(lines)
