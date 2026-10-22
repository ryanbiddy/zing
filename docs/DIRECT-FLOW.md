# The Direct flow over MCP (D-3)

Study raw footage through the CLI, then judge it through MCP with an AI client
connected per [Connect](CONNECT.md):

1. **Study the raw recording:** run `zing study recording.mp4 --raw` in a
   shell using the MCP server's workspace. This adds `provenance.raw_mode`
   measurements (keepers, dead air, fillers and repeated takes). MCP
   `study_video(path)` starts an ordinary study: poll `zing_status()`, then
   read the breakdown. It does not expose the raw-mode flag.
2. **Have (or build) the taste target:** `get_profile(name)`, or
   `build_profile(name, slugs, genre=...)` from studied references
   (or run `zing setup` for a guided build). No profile? The direct
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
