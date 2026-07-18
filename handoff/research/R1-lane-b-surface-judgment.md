# R1-B — Surface & judgment design (Lane B)

Researcher: Lane B (Claude Fable 5). Date: 2026-07-18.
Method: three parallel web-research agents (MCP server design; LLM-as-judge;
cross-model prompt consistency) + direct source reading of uoink's MCP
server (`E:\AI\projects\uoink\checkouts\Yoink\{uoink_mcp.py, uoink_mcp_tools.py,
tests/test_c01_mcp_stdio.py}`) + local verification of the `mcp` SDK
(v1.28.1 installed, license/capability check).
Confidence tags: verified-data / practitioner-consensus / single-opinion.
Timebox honesty: .mcpb packaging tested only via docs (no bundle built);
prompt-consistency evidence is thinner than the judge literature — flagged
inline where it matters.

---

## 1a. Exemplary MCP servers — what the ecosystem converged on

- Spec (rev 2025-06-18; stable 2025-11-25): tools carry `name`,
  `description`, `inputSchema`, optional `outputSchema` + structured
  content; a tool returning structured content SHOULD also return
  serialized JSON as text. Two error channels: protocol errors (JSON-RPC)
  for malformed calls; execution errors go IN the result with
  `isError: true` so the model can see and react.
  https://modelcontextprotocol.io/specification/2025-06-18/server/tools —
  verified-data.
- Anthropic tool-design guidance: fewer, consolidated tools; describe each
  "as you would to a new hire"; unambiguous param names (`user_id` not
  `user`); error text = actionable improvements, not tracebacks; consider a
  `response_format` enum (concise used ~1/3 the tokens of detailed).
  https://www.anthropic.com/engineering/writing-tools-for-agents —
  verified-data.
- No normative naming rule; ecosystem convention is snake_case verb-first
  (GitHub MCP server: `get_file_contents`, `create_pull_request`).
  https://github.com/github/github-mcp-server — verified-data.
- Result size matters more than tool count: Claude Code warns at 10k output
  tokens, hard-caps at 25k (`MAX_MCP_OUTPUT_TOKENS`).
  https://code.claude.com/docs/en/mcp — verified-data.
- **Long-running tools — the finding that changes our design:** Claude
  Desktop has a hardcoded ~60s request timeout (TS SDK
  `DEFAULT_REQUEST_TIMEOUT_MSEC = 60000`), not user-configurable; the
  result is silently dropped after. Claude Code is far more forgiving
  (no 60s timer on stdio; 30-min idle timer that progress notifications
  reset; >2-min calls auto-background).
  https://github.com/anthropics/claude-code/issues/22542 +
  https://code.claude.com/docs/en/mcp — practitioner-consensus (Desktop),
  verified-data (Code). Spec-level "Tasks" (SEP-1686, rev 2025-11-25) would
  standardize durable jobs but has essentially zero client support today
  (https://canimcp.dev/) — verified-data.
- Prompts capability: `prompts/list`/`prompts/get` are user-controlled
  templates, surfaced as slash commands (`/mcp__zing__study` in Claude
  Code). Supported by Claude Desktop/Code, VS Code, Cursor; NOT by Codex or
  Gemini CLI. The model never sees prompts proactively.
  https://modelcontextprotocol.io/specification/2025-11-25/server/prompts +
  https://canimcp.dev/ — verified-data / practitioner-consensus.
- Images in tool results: base64 image content is in-spec and renders in
  Claude Desktop/Code and VS Code; counts against Claude Code's token cap.
  https://modelcontextprotocol.io/specification/2025-06-18/server/tools —
  verified-data.
- .mcpb packaging: DXT renamed MCPB, donated to the MCP project (Nov 2025);
  zip of manifest + server dir; Python servers must bundle deps or use
  `server.type: "uv"`; README warns compiled deps (pydantic — required by
  the Python SDK) don't bundle portably.
  https://github.com/modelcontextprotocol/mcpb — verified-data.
- Spec cadence warning: a 2026-07-28 release candidate is imminent
  (https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
  — re-check Tasks + client timeouts before any public ship. verified-data.

## 1b. uoink's MCP surface — the house pattern (read from source)

All verified-data (code read directly, paths above). The v2.1 canonical
surface is 14 `@mcp.tool` tools; the "64 tools" figure in the vision doc
counts the wider legacy/alias/OpenAPI surface.

- **Official MCP Python SDK + FastMCP over stdio, not hand-rolled.**
  `FastMCP("uoink", instructions=...)`, `@mcp.tool` over typed functions;
  SDK-missing import guarded with an actionable stderr message + exit 1.
- **stdout discipline:** stdout reserved for JSON-RPC; backend logging
  rebound to stderr around import.
- **The C-01 lesson (expensive, don't relearn):** the installer's
  embeddable Windows Python locks sys.path — every Claude Desktop launch
  crashed (22/22) while dev machines masked it. Fix: pin the app dir onto
  sys.path at entry. Test: `python -P` recreates the condition and drives
  initialize → notifications/initialized → tools/list → tools/call over
  real stdio with a minimal in-test client, isolated data root via env
  vars, loud skip if the SDK is absent.
- **Errors are data:** every tool returns `{"ok": true, ...}` or
  `{"ok": false, "error": friendly_message}`; exceptions caught at the tool
  boundary and mapped through a friendly_error() translator.
- **Long-running split:** single-video capture is synchronous (blocks for
  the whole extraction — predates the Desktop-timeout evidence above);
  playlist capture returns `job_id` + `get_job_status`/`cancel_job` polls.
- **Boundary hygiene:** every handler validates/clamps its own args;
  per-tool rate limiters; deprecated tool names kept as aliases with
  one-shot warnings; CI counts `@mcp.tool` decorators against doc headings
  so the documented surface can't drift.

Copy: SDK+FastMCP, ok/err envelope, C-01 smoke-test shape, stdout
discipline, boundary validation, docs lockstep. Avoid: the synchronous
long-running capture tool (contradicted by Desktop timeout evidence), and
`bind_backend()` module globals — Zing's modules are small enough to import
directly.

## 2. LLM-as-judge best practice

- Judge biases are documented with data: position bias, verbosity bias
  (both Claude and GPT preferred longer answers >90% in controlled tests),
  self-preference. Mitigations: avoid pairwise for single-item grading;
  anchored criteria. https://arxiv.org/pdf/2306.05685 — verified-data.
- **Coarse scales beat fine scales.** Hamel Husain (30+ engagements):
  binary pass/fail over Likert — adjacent points lack stable meaning.
  https://hamel.dev/blog/posts/evals-faq/why-do-you-recommend-binary-passfail-evaluations-instead-of-1-5-ratings-likert-scales.html
  — practitioner-consensus.
- **Directly on-point production datum:** OpusClip's video-quality judge
  converged on a 3-level (0–1–2) scale per rubric dimension (Hook /
  Content / Visual / Audio) after broader scales reduced consistency for
  humans AND LLMs; 75.2% rubric-level human agreement; judge score
  correlated with export rate (13%→35% low-to-high). Each level has
  explicit definitions, quantifiable cues, boundary examples.
  https://medium.com/opus-engineering/a-scalable-llm-as-a-judge-framework-for-video-quality-evaluation-74612034bd1e
  — verified-data (vendor-published).
- Decomposed criteria beat holistic scoring (G-Eval, EvalLM); checklists of
  Boolean questions show higher cross-model agreement than scale scoring
  (CheckEval, Krippendorff's alpha). https://arxiv.org/pdf/2303.16634 ;
  https://arxiv.org/abs/2403.18771 — verified-data.
- **Field order is load-bearing:** reasoning/evidence fields must precede
  verdict fields (autoregressive generation); GPT-4o dropped 95.75%→53.75%
  on GSM8K with answer-first ordering.
  https://platform.openai.com/docs/guides/structured-outputs (guidance) +
  https://www.dsdev.in/order-of-fields-in-structured-output-can-hurt-llms-output
  (magnitude; single-opinion with data).
- Strict JSON constraints help classification but can tax open reasoning
  (https://arxiv.org/html/2408.02442v1 — verified-data): enum fields for
  labels, free-text fields for the "why it works" analysis.
- **Grounding:** quote-extraction-before-answering is Anthropic's
  documented long-context technique; require the judge to cite concrete
  measurements (timestamps, counts) verbatim, and validate citations
  programmatically against the breakdown (Ragas-faithfulness inverted).
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips ;
  https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/
  — verified-data.
- **Abstention is necessary, not optional:** even reasoning LLMs handle
  unanswerable questions poorly (AbstentionBench); an explicit
  `cannot_judge` enum value with usage rules prevents hallucinated labels.
  https://arxiv.org/pdf/2506.09038 — verified-data.
- "Graders should cheat": privileged quantitative signals make judges
  expert-grade — supports Zing's measurements-first architecture directly.
  https://arxiv.org/pdf/2502.10961 — verified-data.
- Criteria drift is real (EvalGen): rubrics must be iterated against a
  human-labeled set — the wizard-of-oz S1 gate should seed a standing
  calibration set, not be a one-off. https://arxiv.org/abs/2404.12272 —
  verified-data.
- Vision keyframes (S2): frame counts in practice are small (4–20);
  transcript+OCR text alongside frames measurably lifts comprehension;
  sampling at detected shot boundaries beats uniform sampling; label frames
  "Frame N @ t=X.Xs", ~1568px longest edge for Claude, images before text.
  https://arxiv.org/html/2405.21075v1 ;
  https://platform.claude.com/docs/en/build-with-claude/vision ;
  https://arxiv.org/html/2502.21271v1 — verified-data.

## 3. Prompt-pack design for cross-model consistency

- Prompts don't transfer reliably across models: "model drifting" gaps of
  11–39% on benchmarks (https://arxiv.org/html/2512.01420v1); trivial
  format changes produced up to 76-point accuracy spreads, weakly
  correlated across models (https://arxiv.org/abs/2310.11324) — both
  verified-data. Larger frontier models are more format-robust
  (https://arxiv.org/abs/2411.10541 — verified-data).
- Vendor guidance diverges but has an intersection: Markdown headings are
  endorsed by all three vendors; XML-style tags are first-class for Claude
  and fine for OpenAI ("JSON performed particularly poorly" for long
  context per OpenAI's own GPT-4.1 guide); data-first + instructions
  restated at the end satisfies Anthropic's data-first AND OpenAI's
  bookend guidance simultaneously.
  https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/use-xml-tags ;
  https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide —
  verified-data (vendor docs).
- Few-shot is the best-evidenced consistency lever for judges: MT-Bench
  judge consistency rose 23.8%→63.7% (Claude-v1) and 65.0%→77.5% (GPT-4)
  with few-shot examples — but exemplars are order/count-sensitive, so ship
  exactly one fully-worked example and instruct not to copy its wording.
  https://arxiv.org/pdf/2306.05685 — verified-data.
- Prompt-pack prior art: the formats that won distribution (AGENTS.md 60k+
  repos, Claude Agent Skills SKILL.md, Cursor rules) are all "Markdown +
  minimal YAML frontmatter" — any tool parses them in an afternoon. Skills
  spec: `name` + `description` required, version conventionally in
  `metadata.version`, body under ~500 lines, reference detail in separate
  on-demand files. https://agentskills.io/specification ;
  https://agents.md/ — verified-data (specs).
- Prompt versioning: no standard; practitioner consensus is semver + a
  changelog (major = output-contract break). — practitioner-consensus, no
  rigorous evidence.

## 4. MCP-native media prior art

- **guimatheus92/mcp-video-analyzer** (TS, MIT): the best-shaped prior art —
  `get_frames`/`analyze_moment`/`get_frame_at` tool family, timestamped
  unified timeline JSON, adaptive frame count by duration, frames written
  to disk with paths in the response, perceptual-hash dedupe, graceful
  degradation. https://github.com/guimatheus92/mcp-video-analyzer —
  verified-data.
- **KyaniteLabs/kinocut** (Python, Apache-2.0): 150 tools — copy its
  preflight validation and JSON "receipts" (per-step provenance) for
  `save_judgment`; avoid its tool sprawl.
  https://github.com/KyaniteLabs/kinocut — verified-data.
- **misbahsy/video-audio-mcp** (Python/FastMCP, MIT): 30+ ffmpeg tools with
  no documented long-job handling — the cautionary example.
  https://github.com/misbahsy/video-audio-mcp — verified-data.

---

## Lane B design picks (concrete, justified)

1. **Server: official `mcp` Python SDK + FastMCP over stdio** (MIT,
   verified locally at v1.28.1 with prompts, `Context.report_progress`, and
   `Image` all present). This is also the house pattern — zero novel
   protocol code. Port uoink's stdout discipline and C-01 smoke test
   (`python -P`, real stdio handshake, isolated `ZING_HOME`, loud skip
   without SDK) as the CI gate.
2. **`study_video` = background job from day one** (supersedes my Phase-0
   critique item 2, which said "sync in S1"). Claude Desktop's
   unconfigurable ~60s timeout makes a minutes-long sync tool fail in the
   flagship client. Design: cheap validation up front (file exists /
   required tools present → immediate honest error), then start a worker
   thread and return `{ok, slug, status: "started"}` in <1s;
   `zing_status()` reports per-slug job state (phase, elapsed, error);
   `get_breakdown(slug)` returns "still studying, phase X" until done.
   Emit `ctx.report_progress` during the run (resets Claude Code's idle
   timer; harmless elsewhere). Skip spec Tasks (no client support).
3. **Errors:** two-channel per spec. Malformed args → protocol errors
   (FastMCP handles); everything else → result data in uoink's
   `{"ok": false, "error": ...}` envelope with actionable text ("ffmpeg
   not found — run `zing doctor` for install instructions"). Every failure
   a user can hit is honest and names the next step (house discipline).
4. **Result budgets:** `list_breakdowns` returns summaries only (already
   built in storage); `get_breakdown` returns full JSON for shorts (fits
   the 10k-token comfort zone for ≤60s videos) but gains a
   `detail: "summary"|"full"` param so long videos don't blow the 25k cap.
5. **`save_judgment`:** per-section replace (already enforced in storage),
   stamped `_meta` (`prompt_version`, `written_at`, optional `model`);
   response is a kinocut-style receipt: sections written, sections
   preserved, where the file lives.
6. **Prompt pack, triple-served:** (a) repo files `prompts/*.md` packaged
   as package data — SKILL.md-style YAML frontmatter with `name`,
   `description`, `metadata.version` (semver) + changelog; (b) MCP prompts
   capability so Claude-family/VS Code/Cursor users get
   `/mcp__zing__study`; (c) a `get_prompt(name)` tool so Codex/Gemini-CLI
   users (no prompts support) can still pull it. CLI: `zing prompt study`
   prints it for the paste flow.
7. **Judgment output contract (in prompts/study.md):** decomposed criteria;
   Boolean checklist questions + small enums (hook type, beat labels) with
   one-line definitions at point of use; 0–1–2 anchored levels for quality
   reads (OpusClip's production result), never 1–10; every object ordered
   evidence → reasoning → verdict; `cannot_judge` in every enum with usage
   rules ("visual hook with no words/captions in 0–3s → cannot_judge, say
   what a human should look at"); require verbatim measurement citations;
   one fully-worked example judgment with "don't copy its wording";
   breakdown JSON fenced in tags, instructions restated at the end
   (satisfies Claude + GPT guidance simultaneously); recommend temperature
   0 in the prompt's usage notes.
8. **Frames (S2, spec'd now):** `get_frames(slug, timestamps[])` returning
   labeled base64 JPEGs ("Frame N @ t=X.Xs", ≤1568px, ≤8 per call) sampled
   at detected shot boundaries — renders in Claude Desktop/Code/VS Code;
   extraction on demand via ffmpeg, no storage cost.
9. **.mcpb:** defer to S5; prefer `server.type: "uv"`; the
   pydantic-doesn't-bundle warning means a bundled-venv fallback must be
   tested per-platform. Re-check after the 2026-07-28 spec release.

## Deeper threads

1. **MCP Tasks (SEP-1686) adoption watch:** the experimental durable-jobs
   spec would replace our hand-rolled job pattern; zero client support
   today, 2026-07-28 RC imminent. Re-survey before S5 ship and swap if
   Claude Desktop adopts it.
2. **Judgment calibration harness:** EvalGen/criteria-drift evidence says
   the wizard-of-oz gate should become a standing set: Ryan-labeled
   judgments on the eval goldens + real references, with prompt-pack
   changes scored against them (agreement %, per-criterion). Where does
   this live — Lane C's eval harness or a new tools/eval-judgment?
3. **Cross-model judgment agreement measurement:** same breakdown, N
   models, measure enum-field agreement (the 76-point format-spread result
   suggests it may be worse than we hope). Cheap harness; would tell us if
   "consistent across Claude and GPT" is real or aspirational.
4. **Citation validation:** judge findings recommend programmatically
   verifying that cited timestamps/numbers exist in the breakdown
   (Ragas-inverted). Should `save_judgment` validate citations and reject
   ungrounded judgments, or only warn? Needs a design call before S2.
5. **Windows .mcpb reality check:** build one against a real Claude Desktop
   install (uv type vs bundled venv) — the pydantic warning suggests this
   is a half-day of pain best discovered before launch week.
