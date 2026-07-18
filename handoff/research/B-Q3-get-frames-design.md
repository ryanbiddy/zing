# get_frames(slug, timestamps[]) — S2 tool design (B-Q3)

Author: Lane B. Date: 2026-07-18. Status: ready to build at S2 open.
Closes the text-only judgment gap (Phase-0 critique #6 → binding B#6):
today the judgment AI reads numbers about a visual medium; this tool lets
it SEE the frames it is judging. Evidence base: R1-lane-b-surface-judgment
§2 (keyframe practice) and §1a (images in MCP results).

## Signature & contract

    get_frames(slug: str, timestamps: list[float]) -> content blocks

- ≤ **6 timestamps per call** (hard cap 8; more → honest error naming the
  cap and suggesting a second call). Rationale: image tokens ≈ w·h/750 on
  Claude; at our output size that is ~800 tokens/frame, so 6 frames ≈ 5k
  tokens — comfortably under Claude Code's 10k warn threshold with room
  for the text labels (R1-B §1a).
- Frames are extracted **on demand from the stored media** via ffmpeg
  (`storage.find_media(slug)`); nothing is cached to disk in v1.
- Result content interleaves text and image blocks, in timestamp order:
  a text label `Frame N @ t=X.XXs` followed by its JPEG image block
  (labels are load-bearing: they are how the model cites a frame —
  Claude vision docs, R1-B §2).
- Output size: longest edge **1024 px**, JPEG ~q80. Below Claude's
  1568px optimum but half the token cost; hook frames are legible at
  1024 on 1080×1920 sources. Revisit against real judgments in S2 eval.

## Error surface (all `{ok:false, error}` data, house envelope)

| Condition | Message shape |
|---|---|
| unknown slug | same as get_breakdown: points at list_breakdowns |
| media absent | "breakdown exists but its media file is gone (media.* not in the workspace) — re-run study_video to refetch" |
| ffmpeg missing | points at `zing doctor` |
| timestamp beyond duration | per-frame: that frame becomes a text block "t=X.Xs is past the video's end (duration Ys)" — valid timestamps in the same call still return images |

## Caller guidance (goes in the tool description + study.md bump)

- Sample at **shot boundaries** (`shots[].start`), not uniform intervals —
  keyframe-aligned sampling beats uniform for judgment (R1-B §2, two
  sources). The hook window 0–3s is the priority: request the start of
  every shot in 0–3s first.
- Always judge frames TOGETHER with the transcript/caption text —
  text+frames measurably beats frames alone (Video-MME, R1-B §2).
- When this ships, `prompts/study.md` gets a minor version bump: the
  visual-hook rule becomes "call get_frames on the 0–3s shot starts
  before declaring `cannot_judge`" — the honest-degradation path remains
  for clients that can't render images (Codex/Gemini CLI, R1-B §1a).

## Implementation sketch

One ffmpeg exec per frame (≤8, ~100ms each, fine):

    ffmpeg -ss <t> -i <media> -frames:v 1 \
      -vf "scale='min(1024,iw)':-2" -c:v mjpeg -q:v 5 -f image2pipe -

FastMCP side: return a list of `TextContent`/`Image` objects (SDK
`mcp.server.fastmcp.utilities.types.Image` verified present at 1.28.1).
Relationship to `Shot.keyframe` files (Lane A writes those at study
time): complementary — stored keyframes serve filesystem-capable clients
free of charge; get_frames serves protocol-only clients and arbitrary
timestamps. No duplication: get_frames does NOT read the keyframe JPEGs
(they may be sized/cropped for other uses); it always extracts fresh.

## Test plan (offline)

- Handler tests with a mocked `proc.run`-style subprocess returning fixed
  JPEG bytes: ordering, labels, per-frame out-of-range honesty, cap
  enforcement, media-absent path.
- One integration test behind the existing ffmpeg-in-CI gate (Lane C
  pattern): synthetic 2-color video, ask for a frame from each color
  span, assert the JPEG's dominant pixel differs (content probe, no OCR).
- stdio smoke: tools/call get_frames on the synthetic video asserts an
  image content block with mimeType image/jpeg is present.

## Open question for the orchestrator (non-blocking)

Whether get_frames should also accept `shot_index: int` sugar
(`get_frames(slug, shots=[0,1,2])`) so the model doesn't have to copy
timestamps — cheap to add, slightly wider schema. Default: leave it out
of v1; measurement citations should quote timestamps anyway.
