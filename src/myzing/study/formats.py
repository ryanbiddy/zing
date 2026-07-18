"""Format-aware measurement parameters (A-Q4).

Zing studies more than vertical shorts: X native video and YouTube
long-form are first-class sources. Measurements themselves are
aspect- and duration-agnostic; what changes per format is WHERE the
hook lives and how densely we can afford to sample:

- Hook window: 0-3s for short-form (advice clusters at 1-6s), 0-30s for
  long-form (YouTube's own measured "Intro" analytics window) — TASTE-
  FRAMEWORK H5, score per-format.
- OCR body sampling drops from 4 to 2 fps on long-form so a 20-minute
  video doesn't cost thousands of OCR calls; the hook window keeps the
  dense rate either way, and the actual schedule is always recorded in
  warnings.

The format split is by DURATION, not platform: a 45s X clip is
short-form, a 20-minute YouTube video is long-form. 3 minutes is the
boundary (YouTube Shorts' own maximum).
"""

from __future__ import annotations

SHORT_FORM_MAX_S = 180.0

SHORT_HOOK_WINDOW_S = 3.0
LONG_HOOK_WINDOW_S = 30.0

SHORT_BODY_FPS = 4.0
LONG_BODY_FPS = 2.0


def is_short_form(duration: float) -> bool:
    return duration <= SHORT_FORM_MAX_S


def hook_window_s(duration: float) -> float:
    return SHORT_HOOK_WINDOW_S if is_short_form(duration) else LONG_HOOK_WINDOW_S


def body_fps(duration: float) -> float:
    return SHORT_BODY_FPS if is_short_form(duration) else LONG_BODY_FPS
