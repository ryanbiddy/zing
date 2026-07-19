# The Direct flow over MCP (D-3)

Raw footage in, honest direction out — the whole loop through the MCP
tools, for any AI client connected per docs/CONNECT.md:

1. **Study the raw recording:** `study_video(path)` → poll
   `zing_status()` → the breakdown gains raw-mode measurements
   (`provenance.raw_mode`: keepers, dead air, fillers, repeated takes).
2. **Have (or build) the taste target:** `get_profile(name)`, or
   `build_profile(name, slugs, genre=...)` from studied references
   (`zing setup` will streamline this — S4). No profile? The direct
   prompt runs in rubric-only mode and says so in its output.
3. **Judge:** load the `direct` prompt (`/mcp__zing__direct` in Claude
   clients, `get_prompt("direct")` elsewhere) and follow it against
   `get_breakdown(raw_slug)` + the profile + the genre rubric. Visual
   gaps need `get_frames` or keyframes — the prompt refuses to invent
   what nobody saw.
4. **Write back:** `save_judgment(raw_slug, judgment, section="direct")`
   — Zing validates the contract keys and renders **`direction.md`**
   next to `breakdown.md`: what works, what's missing, what to film, in
   that order, in plain language. The receipt includes the rendered
   path.

Failure honesty along the way: every tool answers errors as data with
the next step named; a missing profile, missing rubric access, or
missing raw-mode data degrades into STATED limitations inside the
direction, never silent pretending. The direction contract itself lives
in `prompts/direct.md` (v1.0.0) — required keys, severity vocabulary,
the plain-language rule for shot prompts.
