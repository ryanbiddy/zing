---
name: taste
description: Turn a built StyleProfile into "this taste in words" — a few plain sentences a creator recognizes as theirs.
version: 0.1.0
---

# Saying a taste out loud

After onboarding builds a StyleProfile, say what it found — in words a
creator nods along to, not numbers. This is the confirmation moment of
`zing setup`: if the words don't sound like their taste, the reference
set is wrong, and finding that out NOW is the point.

## How

1. `get_profile(name)`. Read `warnings`, every stat's `n`, and
   `unjudged_source_slugs` first — thin or unjudged profiles get
   hedged words, and a coherence warning means you say "these
   references pull in different directions" instead of averaging them
   into mush.
2. Write **3–5 sentences**, each grounded in a stat or a collected
   judgment, none containing numbers or internal vocabulary. Translate:
   `shot_duration` median 1.1s → "you like fast hands — cuts land
   about every second"; `caption_words_visible_mode` 1 + high all-caps
   → "captions punch one word at a time, in caps"; hook-type judgments
   mostly `curiosity_gap` → "you open by making people need the
   answer".
3. Name what the profile CAN'T say yet, in one honest closing line
   ("judgments are in for only two of five references — the read
   sharpens as you judge more").
4. Present the words to the user and ask one question: "does this
   sound like the taste you meant?" If no — the fix is the reference
   list, and `setup_taste` with adjusted links is the next step.

No JSON contract here — this prompt produces prose for a human moment.
Keep it under 90 words, warm, and free of hedging filler; the honesty
lives in what you say, not in qualifiers.

## Changelog

- **0.1.0** (2026-07-19, S4 Track 2): initial.
