# Ask through the studio front door

Use `zing_studio` when a creator describes an outcome without choosing commands.
Start with no answers, or supply the known path (`a` reference edit, `b` edit
without a reference, `c` photo meme/still, `d` style breakdown, `e` music advice,
`f` new delivery shape). The tool returns one question at a time.

Relay `question.prompt`, `options`, `recommended`, `reason` and `evidence`.
When there is no recommended answer, ask plainly for the required input; do not
offer Enter to accept an unknown. Use numbered menus; letters remain aliases.
Ask only what is missing; preserve the user's answers in your next call. A
recommendation can be an editorial default or unknown. Audio-stream presence
does not prove speech, and orientation does not prove a safe crop.

The output folder defaults automatically. Ask about the destination once;
shapes follow it unless the creator chooses custom. A local reference receives
an offline preview with an eight-second deadline: at most 20 seconds of video,
three OCR frames, and existing cut/audio measurements. Quote the measured
numbers and sampling limits. Pacing follows the reference by default and can
be changed on the plan screen. Missing measurements remain unknown. Pass back
the returned answers, including the default project, to keep the session stable.

When the response is a plan, show what will be made, shapes, steps, time estimate
or explicit unknown, downloads and output folder. Obtain confirmation. Follow
the returned execution metadata:

- a: `match_start` then `match_status`. Keep the returned `execution.arguments.studio_options` to
  honor studio caption/music choices. `answers.allow_download` is separate consent.
- c: `still_concepts`, review the contact sheet, then `still_render` with a
  returned concept ID. Readability scores do not judge humor.
- e: `music_check`; explain good/usable/bad ratings using its measured reasons.
- b/d/f: `zing_studio_run(answers=..., confirmed=true)`, then poll with `project`.
  Use `cancel=true` only to stop that server's owned job.

With shell access, use `zing studio --answers answers.json --json` to review
the same plan, then add `--yes` after confirmation. Read every JSON Lines event.
Incomplete answers return another question; no execution occurs. Interactive
`zing studio` supports Enter, `?`, `b`, `q` and `--resume <project>`.

Present a drafts-by-shapes table, one recommendation grounded in measured match
checks (or say there is no clear winner), and at most five merged creator notes.
Keep full detail in the result. Include the output folder, result path and exact
draft-choice command, then two or three concrete next actions. Do not call
an edit a style match merely because it rendered. Do not silently crop baked-in
captions in a flattened-video re-delivery; recommend the original plan when
available. The style-card module has a labeled study/inspect fallback.
