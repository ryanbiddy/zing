# SG-4 scan: measurement-stack upstream currency (pre-Decision-Week)

Scope: doctor has a staleness story for yt-dlp only; nothing watches
the rest of the measurement stack. With the launch packet assembling,
this scan checks every studied dependency against its live upstream.
Live-verified (PyPI JSON API + release pages); versions read from the
working venv and pyproject.

## Verdict: the whole stack is CURRENT. No build needed.

| Dependency | Ours | Upstream latest | State |
|---|---|---|---|
| scenedetect-headless | 0.7 (floor >=0.7) | 0.7 | current |
| faster-whisper | 1.2.1 (floor >=1.1) | 1.2.1 (2025-10-31, stable-not-stalled) | current |
| rapidocr | 3.9.1 (floor >=3.9) | 3.9.1 | current |
| mcp SDK | 1.28.1 (floor >=1.2) | 1.28.x line | current |
| yt-dlp | 2026.7.4 | (doctor's own 90-day staleness watch) | 15 days old |

Cross-checks that could have bitten and did not:

- **PySceneDetect 0.7 (2026-05) was a BREAKING major** (timestamp
  overhaul incl. native VFR, 1-based frames, non-overlapping adjacent
  scenes, SceneDetector interface change). Our floor is already
  `>=0.7` and CI is green against it — Lane A's shots.py speaks the
  new API. A lower floor would have let pip serve 3.9 users the old
  0.6 API our code would break against; moot because...
- **Python floors are aligned**: scenedetect 0.7 requires >=3.10 and
  `myzing` declares `requires-python = ">=3.10"`. No resolution trap.

## Watch-item for the next stack scan (not a defect)

Upstream has opened a NEW distribution name, `scenedetect-core`
(0.7.1.dev0 on PyPI, no stable release). If future releases move to
`-core` and `-headless` stops tracking, our `[study]` extra freezes
silently at 0.7 while looking healthy. Trigger for action: a STABLE
scenedetect-core release; the fix at that point is a one-line extras
rename. Do not act on a dev0.

## Sources

- https://pypi.org/pypi/{scenedetect-headless,scenedetect,scenedetect-core,rapidocr}/json
  (fetched live this cycle)
- https://github.com/Breakthrough/PySceneDetect/releases +
  https://www.scenedetect.com/changelog/ (v0.7 breaking notes)
- https://github.com/SYSTRAN/faster-whisper/releases (1.2.1 stable)
