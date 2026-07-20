# SG-4 scan: zing's platform-install position (and what the bundle installs)

Prompted by the RB block's macOS findings (universal2 dead; LGPL ffmpeg
has no macOS equivalent -> a legal question for Ryan on uoink's side).
That raised the obvious question nobody had asked of MY surface: what
does zing actually require per platform, and what does our one-click
bundle really install?

## Zing's position is clean, and worth stating plainly

- **Core has ZERO runtime dependencies** (`dependencies = []`). Every
  heavy, compiled thing — onnxruntime, faster-whisper/ctranslate2,
  rapidocr, yt-dlp — lives in the OPTIONAL `[study]` extra.
- **ffmpeg is REQUIRED but never bundled.** Doctor names the
  platform install command; the user installs it themselves. Zing ships
  no ffmpeg binary and links nothing, so the LGPL question live on the
  uoink side does not arise here. Worth recording explicitly now that
  the suite has a real legal question open: **zing's answer is "we do
  not distribute it".**
- The `.mcpb` bundle is `type: uv` with `--extra mcp`, and `mcp` is
  pure Python — so "one bundle serves Windows/macOS/Linux" holds
  architecturally, not just by luck.

## THE FINDING: what the bundle installs, the product then misdescribed

A `.mcpb` install produces core + `mcp` and NO study extras — by
design. Ask that install to study something and it said:

> the study engine is not in this build yet (Sprint 1 in progress) —
> study_video will work here unchanged once it lands

Three things wrong, all user-facing, all on our own documented
one-click path:

1. **Stale.** Sprint 1 shipped long ago; S6 is closed.
2. **Misdiagnosed.** The engine IS in the build — `myzing.study.api`
   ships in the wheel. The EXTRAS are missing.
3. **Unactionable, and actively misleading.** It tells the user to WAIT
   for a future release. They would wait forever; the fix is one pip
   command.

Same family as D-13 and the review's P1-1: a message whose advice
cannot be followed. Fixed at all three sites (study_video,
study_uoink_item, build_profile) to name the cause and the exact
command, and to note that the bundle installing only the server is
expected rather than broken.

## Why it survived: THREE tests pinned the wrong text

`test_study_video_engine_absent_is_honest`,
`test_build_builder_absent_is_honest`, and
`test_summary_preserves_start_denied_cause` all asserted
`"not in this build yet"`. Each was written to protect an honest
message — and once the world moved, they protected a lie instead. A
test that pins a message also pins that message's CORRECTNESS; nothing
was watching whether the sentence was still true.

New guard: `test_no_user_facing_message_cites_a_sprint` fails on any
string literal in `mcp_server.py` containing "Sprint N". Sprint numbers
are internal scheduling — a user reading one learns nothing actionable
and sees the product's age on their screen.

## Sources

- this repo's `pyproject.toml`, `packaging/mcpb/manifest.json`
- live probes of the extras-absent import path (this cycle)
