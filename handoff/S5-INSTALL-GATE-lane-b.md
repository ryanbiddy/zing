# S5 install gate records — fresh-host verification (Lane B)

Harness: `packaging/clean_host_check.py` — builds the wheel, installs it
(+`[mcp]`) into a pristine venv, and drives the first-run surface from a
neutral working directory with an isolated `ZING_HOME` and NO repo
checkout on the tested path. Every step's honest output is recorded;
any FAIL is a defect by sprint definition.

## Windows 11 (local, 2026-07-19) — 7/7 PASS

| step | result | evidence |
|---|---|---|
| build-wheel | PASS | myzing-0.1.0-py3-none-any.whl |
| install-wheel | PASS | wheel + [mcp] extra into bare venv |
| doctor | PASS | exit 0; honest tiers (ffmpeg found; recommended items name degraded modes + fixes) |
| doctor --json | PASS | all 7 checks present incl. tts |
| prompt-pack | PASS | packaged study.md served (no repo on path — the #156 mirror carried it) |
| preset-packs | PASS | all packs listed from packaged data |
| study-cached-media | PASS | exit 0; breakdown written with honest skip warnings (bare venv: no scenedetect/whisper/OCR — each named with its pip fix) |

Notable: this run would have FAILED at prompt-pack and preset-packs
before #156 (wheel carried neither). The packaging drift-gate keeps
that fixed.

## ubuntu-latest / windows-latest / macos-latest (CI)

The `clean-install` matrix job runs this harness on every PR and
uploads `clean-host-<os>.json` gate records as artifacts — the per-OS
records accrue with each run rather than being frozen here. First
execution: the PR that adds the job (see its artifacts for the three
records).

## Rough edges observed (defect candidates, none blocking)

1. `zing setup --list` on a fresh host prints pack names but nothing
   tells the user the NEXT command (`zing setup --pack <name>`); one
   usage line at the end of the listing would close the loop.
2. `zing doctor`'s bare-host output is honest but long (7 items);
   a one-line verdict at the top ("ready for local files; install
   [study] for URLs and full measurements") would serve first-run
   scanning. Both filed as observations, not fixed here — S5 defect
   triage owns priorities.
