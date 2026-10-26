# Changelog

## Clip quality

- Match keeps source color by default. CLI `--color reference` and MCP
  `color="reference"` opt into grading; recipes and reports record the mode.
  Recipes that omit `color_mode` also default to `source`.
- Skin checks catch lost chroma and lightness as well as hue changes, and
  reference-grade skin misses appear as top-level match warnings.
- Draft captions keep one font size across groups and shots. Long phrases
  regroup when word timings are available; untimed clauses try shorter wraps.
  A size reduction applies to every caption, including mixed preset drafts.
- Moments reject filler and back-reference openings and stop before questions.
  Ranking favors substantive opening statements; suggestions include their
  first and last sentences.
- Draft selection trims measured face-free gaps and text cards out of candidates
  when the source has faces elsewhere. Faceless sources remain usable; a nearby
  slate does not invalidate a required span that survives the trim.
- Match recipe, director, caption-fit and skin-report checkpoints are invalidated
  for the new quality policy.

## 1.0.0rc1

Release candidate for Zing v1. These highlights cover merged PRs #401 through
#452 on main.

### Long interviews

`zing moments` and the `zing_moments` MCP tool suggest complete transcript windows
with Estimated scores, reasons and ready-to-use `must_keep` JSON. Oversized
sources require a chosen moment; match then records its focused search window as
Measured in plans and reports. Audio/video duration drift up to 250 ms is accepted
with a warning; uncovered tails remain unmeasured. Match skips optional audio maps
beyond the analyzer's ten-minute limit. The MCP registry now has 37 tools.

### Studio

`zing studio` is the guided starting point. Choose a reference match, an edit
from clips, a photo meme, a style breakdown, music advice or new delivery
shapes. Save answers, resume work and review the resulting files. The
interview asks at most 10 questions on any path, offers a trim for references
over 60 s, and skips still images in a clip folder with a note. New sessions
start in the Zing workspace, never the current folder. (#429, #432, #445,
#446, #451)

### Explain

`zing explain` makes a style card from a video: cuts, transitions, captions,
color, framing and music. Use `--against` to compare with another video.
A hook and loop section reports time to first word, cut and caption, the
opening cut rate against the rest, and pixel checks for a clean loop and a
flash-forward cold open; anything not measured says unknown. Long references
take `--ref-start`/`--ref-end`, and analysis is capped at 60 s. (#424, #445,
#452)

### Screen demos

`zing plan screen` and `zing match screen` edit screen recordings with
cursor-aware auto-zoom, idle speed-up and action-timed cuts. Portrait framing
zooms until UI text is readable on a phone, without clipping the focus or
cutting text mid-word. (#443)

### Match and honest checks

Match takes a reference and your clips through planning, rendering and checks.
The director respects measured timing ranges, keeps source-cut mappings and
reports shortages when it cannot make distinct drafts. Color checks account
for scene differences and skin preservation. Missing evidence stays unknown;
a rendered file alone does not prove a style match. A moment too short for
three distinct drafts is labeled a variety limit, and short silent clips can
reach the target length by trimming the final shot, which is disclosed.
(#411, #417, #418, #431, #435, #437, #445, #451)

### Caption presets

Choose punch, box or clean captions. Word groups fit the available width,
baselines use font metrics, and highlight boxes can follow spoken words while
the surrounding phrase holds still. Positioned captions and optional
HyperFrames overlays share the composition plan. Box captions avoid
lower-thirds, numbers such as "$3,000" stay one unit with one plate per line,
and plate tops follow real glyph tops. (#404, #407, #408, #409, #412, #413,
#434, #438, #445, #450)

### Framing and aspects

Deliver 16:9, 1:1 and 9:16 from one edit. Framing options include zoomfill,
speaker-aware crops, headroom and picture-in-frame layouts. Delivery size
checks disclose low-resolution sources. Broadcast composites crop to the live
picture instead of the show graphics, a single talking head fills a 9:16
frame, and small background faces are disclosed as bystanders instead of
widening the shot. (#419, #423, #425, #434, #445, #450)

### Music

Place music around the edit, duck it under dialogue and inspect track advice.
Later mixing fixes reduce pumping and even out dialogue. Optional local audio
tagging separates vocals and instruments; speech timing repair stays bounded
by measured voice activity. (#405, #422, #427, #436)

### Memes and stills

Turn photos and a topic into concepts, contact sheets and exported stills.
Offline ideas, face-aware framing and subject-safe text support larger photos
and HEIC inputs where the decoder is available. Person and object detectors
also help protect pets from text placement. Animated meme rendering is
available for video inputs. (#402, #407, #409, #420, #425, #439)

### Setup and onboarding

Studio, doctor and setup explain missing speech models and ask before fetching
them. Downloads require HTTPS and verified hashes. Portable asset paths and
FFmpeg 9 compatibility improve setup across machines. `zing doctor` names the
missing FFmpeg capability and prints the install command for your system;
`zing setup --ffmpeg` runs it only after an explicit yes. Install,
troubleshooting and privacy guides cover Windows, macOS and Linux. (#401,
#403, #432, #440)

### Uoink

Use saved references, verified kept media and local search through Uoink's
existing service. Zing records choices and receipts, preserves real item
titles, and keeps a local workflow when the peer is absent. (#408, #415,
#421, #425)

### Agents and MCP

The agent skill, brief interview and composition tools expose local editing
workflows. The server uses the official MCP SDK 2.3 and offers 37 tools,
including studio and explain. Registry metadata and a separate manual registry
workflow prepare the listing for publication. The listing copy, registry line
and PyPI summary match across the README, MCP instructions, bundle manifest
and skill. (#407, #416, #424, #426, #429, #433, #442)

### Safety and privacy

Private handoff material is outside the public tree. Evaluation records retain
rights information, and unlicensed creator text and frames are not
redistributed. Model downloads require an explicit request; local editing does
not automatically publish media. (#414, #430, #432)

### Packaging and release

The release candidate includes runtime data and license notices in the wheel.
Fresh-install checks install common extras and all extras, list all 37 MCP
tools, call `zing_status`, and render an offline studio still on Windows,
macOS and Linux in CI. A manual release workflow builds and checks artifacts
before an environment approval gate, then uses PyPI Trusted Publishing.
GitHub releases start as drafts. No package or release was published as part
of this packaging pass. (#441)
