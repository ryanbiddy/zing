# Zing UX Study and Product Surface Design

Researcher: Antigravity. Date: 2026-07-18.
Scope: Design audit of CLI, markdown report, and MCP ergonomics, branding system design for Zing, and dashboard surface specifications.

---

## 1. Ergonomic Audit of Current Surfaces

### CLI Ergonomics
- **Progress Visibility**: Currently, running `zing study <url>` on the CLI blocks synchronously without visual progress indicators. The user stands in the dark while the engine downloads, transcribes, and runs OCR.
  - *Fix*: Implement a visual terminal step indicator (e.g., using `STUDY_PHASES` from `mcp_server.py`): `[1/6] ingest -> [2/6] shots...` to eliminate dead terminal states.
- **Doctor Autocorrect**: `zing doctor` identifies problems (like missing `ffmpeg`) but does not offer copy-paste setup commands.
  - *Fix*: Output OS-specific installs (e.g., `winget install Gnu.FFmpeg` for Windows, `brew install ffmpeg` for macOS).
- **Prompt Pack Discoverability**: `zing prompt` requires a positional name argument. If run with no argument or an invalid one, it fails instead of showing a list.
  - *Fix*: Interactively list available templates when the name is omitted.

### `breakdown.md` Ergonomics
- **Visual Gaps**: The markdown contains tables for shots and captions but lacks visual connections.
  - *Fix*: Now that keyframes are backfilled (PR #54), embed relative keyframe images directly in the markdown tables (`![Shot #3](file:///...)`) to let editors scan shot composition within their IDE/reader.
- **Literal Markdown Escapes**: Raw asterisks and markdown formatting are sometimes printed literally in string dumps.
  - *Fix*: Strip or parse markdown syntax in metadata string outputs.

### MCP Server Ergonomics
- **Status Granularization**: `zing_status` reports basic running/failed states.
  - *Fix*: Expose progress percentage or active phase index (e.g., `phase: "transcribe" (3/6)`) so frontends can render progress bars.

---

## 2. Zing Brand Identity (Uoink's Sibling)

Zing is the *taste, evaluation, and editing* engine, whereas Uoink is the *capture and storage* engine. They are sibling products: Uoink captures, Zing sharpens.

### Visual & Voice Rhymes
- **Aesthetic Contrast**: If Uoink is "Warm & Tactile" (cream paper, ink stamps, heavy block fonts, organic vermillion), Zing is "Electric & Precision" (dark voids, neon green/yellow lasers, blueprint grids, sharp geometric lines).
- **Brand Tokens**:
  - **Colors**:
    - Primary Dark: `--void` (`#030712` - deep space black)
    - Primary Accent: `--electric-lime` (`#A3E635` - high-frequency glow)
    - Ground: `--blueprint` (`#0B132B` - dark steel blue)
    - Muted: `--slate` (`#64748B` - grid line gray)
  - **Typography**:
    - Display: `Space Grotesk` or `Syne` (wide, futuristic, geometric sans-serif)
    - Mono: `JetBrains Mono` (sibling developer tool connection)
    - Body: `Inter` (neutral, high legibility)
- **Voice DNA**:
  - Uoink: "Uoink that shit." (colloquial, physical, heavy).
  - Zing: "Cut the slop. Find the spark." (direct, sharp, surgical, energetic).
- **The Visual Cue**:
  - Uoink uses the tilted rubber-stamp.
  - Zing uses the **"Zapped!" Neon Cut Mark** — a diagonal neon-green strike-through (`/`) over slop scores, representing editorial cuts and highlights.

---

## 3. Deferred Local Dashboard Surface Sketch (Uoink-Style)

This section is a future product sketch, not a description of the current
application. Zing currently runs through its CLI and direct stdio MCP server;
it has no HTTP listener. Port `5180` is reserved only. A local dashboard should
remain demand-gated until its first real user workflow justifies the extra
surface.

### Tab Architecture
1. **The Inbox (Incoming)**:
   - Lets the user choose a stable `uoink://item/<id>` reference and invoke
     `study_uoink_item`; Uoink does not push into Zing.
   - Left panel: user-selected captures awaiting or undergoing scoring.
   - Right panel: active video preview with a draft score meter.
2. **The Workbench (Build)**:
   - Tool to select multiple scored clips and compile them into an edit decision list (EDL).
   - Smart inputs auto-complete topic names, creator handles, and hook styles from the local database.
3. **The Cutting Room (Script)**:
   - Displays script text side-by-side with target timing graphs.
   - Highlights slop words in real-time, warning the creator when pacing slows down.
4. **The Evaluator (Compare)**:
   - Shows before-and-after scoring breakdowns when a new cut is rendered against the baseline.
5. **Settings**:
   - Manages local rendering paths, active prompt packs, and output presets (e.g. 9:16 vertical shorts, 16:9 widescreen).

### Onboarding & Empty States
- **Furnishing the Room**: Rather than showing "No data found," the Workbench loads with ghosted templates (e.g., "Creator Audit Template", "Slop Detection Baseline") representing pre-indexed video clips, allowing users to run sample evaluations immediately.
- **Phase Feedback**: When running a study, the dashboard renders an interactive phase ladder (`ingest -> shots -> transcribe -> ocr -> audio -> markdown`) where the active step pulses in electric-lime.
