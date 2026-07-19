"""Render ``judgment["direct"]`` into ``direction.md`` — for a creator.

The judging AI writes the direction contract (prompts/direct.md v1);
this module turns it into the file a human actually reads, in creator
order: what works, what's missing (cited), exactly what to film.
Written automatically when ``save_judgment(section="direct")`` lands.

Plain language is a hard rule of the contract; the renderer keeps the
internal evidence (criterion IDs, profile stats) in a collapsed
"receipts" section instead of deleting it — honest, but out of the way.
"""

from __future__ import annotations

from typing import Any

_SEVERITY_LABEL = {
    "blocking": "MUST FIX",
    "important": "SHOULD FIX",
    "polish": "POLISH",
}
_SEVERITY_ORDER = {"blocking": 0, "important": 1, "polish": 2}


def _fmt_time(seconds: Any) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    return f"{int(s // 60)}:{s % 60:04.1f}" if s >= 60 else f"{s:.1f}s"


def render_direction(direct: dict[str, Any], slug: str) -> str:
    """Markdown for direction.md from a judgment['direct'] dict.

    Tolerant of missing keys (save_judgment validates required ones, but
    a hand-written or older judgment should still render something
    honest rather than crash)."""
    lines: list[str] = [f"# Direction — {slug}", ""]

    verdict = direct.get("verdict", "")
    if verdict:
        lines += [str(verdict), ""]

    keepers = direct.get("keepers") or []
    lines += ["## What already works", ""]
    if keepers:
        for k in keepers:
            span = f"{_fmt_time(k.get('start'))}–{_fmt_time(k.get('end'))}"
            lines.append(f"- **Keep {span}** — {k.get('why', '')}")
    else:
        lines.append("- Nothing was marked keepable — see the gaps below.")
    lines.append("")

    gaps = sorted(
        direct.get("gaps") or [],
        key=lambda g: _SEVERITY_ORDER.get(g.get("severity", "polish"), 3),
    )
    lines += ["## What's missing", ""]
    if gaps:
        for g in gaps:
            label = _SEVERITY_LABEL.get(g.get("severity", ""), "NOTE")
            lines.append(
                f"- **[{label}]** {g.get('footage_evidence', '')}"
            )
    else:
        lines.append("- No gaps found against the target.")
    lines.append("")

    prompts = direct.get("shot_prompts") or []
    lines += ["## What to film", ""]
    if prompts:
        for sp in prompts:
            hint = sp.get("duration_hint")
            hint_txt = f" (~{_fmt_time(hint)})" if hint else ""
            lines.append(f"{sp.get('n', '?')}. {sp.get('instruction', '')}{hint_txt}")
    else:
        lines.append("Nothing to film — the footage covers the target.")
    lines.append("")

    notes = direct.get("assembly_notes", "")
    if notes:
        lines += ["## Assembly notes", "", str(notes), ""]

    if gaps:
        lines += ["<details><summary>Receipts (how each gap was measured)</summary>", ""]
        for g in gaps:
            lines.append(
                f"- `{g.get('criterion_id', '?')}` · target: "
                f"{g.get('profile_evidence', '')} · footage: "
                f"{g.get('footage_evidence', '')}"
            )
        lines += ["", "</details>", ""]

    meta = direct.get("_meta", {})
    if meta:
        lines.append(
            f"*Directed by {meta.get('model', 'an AI')} · prompt "
            f"{meta.get('prompt_version', '?')} · {meta.get('written_at', '')}*"
        )
        lines.append("")
    return "\n".join(lines)
