# Changelog

## 1.0.0rc1

Release candidate for Zing v1. These highlights cover merged PRs #401 through
#439 on main at `385554e`. The held #433 description change is not included.

### Studio

`zing studio` is the guided starting point. Choose a reference match, an edit
from clips, a photo meme, a style breakdown, music advice or new delivery
shapes. Save answers, resume work and review the resulting files. (#429, #432)

### Explain

`zing explain` makes a style card from a video: cuts, transitions, captions,
color, framing and music. Use `--against` to compare with another video. (#424)

### Match and honest checks

Match takes a reference and your clips through planning, rendering and checks.
The director respects measured timing ranges, keeps source-cut mappings and
reports shortages when it cannot make distinct drafts. Color checks account
for scene differences and skin preservation. Missing evidence stays unknown;
a rendered file alone does not prove a style match. (#411, #417, #418, #431,
#435, #437)

### Caption presets

Choose punch, box or clean captions. Word groups fit the available width,
baselines use font metrics, and highlight boxes can follow spoken words while
the surrounding phrase holds still. Positioned captions and optional
HyperFrames overlays share the composition plan. (#404, #407, #408, #409,
#412, #413, #434, #438)

### Framing and aspects

Deliver 16:9, 1:1 and 9:16 from one edit. Framing options include zoomfill,
speaker-aware crops, headroom and picture-in-frame layouts. Delivery size
checks disclose low-resolution sources. (#419, #423, #425, #434)

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
FFmpeg 9 compatibility improve setup across machines. (#401, #403, #432)

### Uoink

Use saved references, verified kept media and local search through Uoink's
existing service. Zing records choices and receipts, preserves real item
titles, and keeps a local workflow when the peer is absent. (#408, #415,
#421, #425)

### Agents and MCP

The agent skill, brief interview and composition tools expose local editing
workflows. The server uses the official MCP SDK 2.3 and offers 36 tools,
including studio and explain. Registry metadata and a separate manual registry
workflow prepare the listing for publication. (#407, #416, #424, #426, #429)

### Safety and privacy

Private handoff material is outside the public tree. Evaluation records retain
rights information, and unlicensed creator text and frames are not
redistributed. Model downloads require an explicit request; local editing does
not automatically publish media. (#414, #430, #432)

### Packaging and release

The release candidate includes runtime data and license notices in the wheel.
Fresh-install checks exercise common extras and all extras, all 36 MCP tools
and an offline studio still render on Windows, macOS and Linux in CI. A manual
release workflow builds and checks artifacts before an environment approval
gate, then uses PyPI Trusted Publishing. GitHub releases start as drafts.
No package or release was published as part of this packaging pass.
