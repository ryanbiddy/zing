"""S5 fresh-host install gate: wheel -> bare venv -> first-run truth.

Simulates a brand-new user with NO repo checkout in the test path:

    python packaging/clean_host_check.py
        [--skip-study | --require-study] [--report out.json]

1. Builds the wheel (``pip wheel . --no-deps``).
2. Creates a pristine venv in a temp dir and installs the wheel
   (+ the [mcp] extra, which a connecting user needs).
3. From a NEUTRAL working directory with an isolated ZING_HOME, runs the
   first-run surface exactly as a new user would:
   ``zing doctor``, ``zing doctor --json``, ``zing prompt study``,
   ``zing setup --list``, and (when ffmpeg exists) a cached-media
   ``zing study`` of a tiny generated clip.
4. Emits a per-step gate record (JSON + console): PASS/FAIL/SKIP with
   the observed output. Every rough edge in first-run output is a
   defect by sprint definition — the record is the evidence.

Exit 0 = all required steps passed; 1 = something a new user would hit.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path, env: dict, timeout: int = 600):
    return subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    study_mode = parser.add_mutually_exclusive_group()
    study_mode.add_argument("--skip-study", action="store_true",
                            help="skip the cached-media study step")
    study_mode.add_argument(
        "--require-study",
        action="store_true",
        help="fail unless the cached-media study step passes",
    )
    parser.add_argument("--report", type=Path, default=None,
                        help="write the JSON gate record here")
    args = parser.parse_args(argv)

    steps: list[dict] = []

    def record(step: str, status: str, detail: str, output: str = ""):
        steps.append({
            "step": step, "status": status, "detail": detail,
            "output_tail": output[-1500:],
        })
        print(f"[{status:>4}] {step}: {detail}")

    with tempfile.TemporaryDirectory(prefix="zing-cleanhost-") as tmp:
        tmpdir = Path(tmp)
        dist = tmpdir / "dist"

        build = run(
            [sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps",
             "-w", str(dist)],
            cwd=REPO, env=dict(os.environ),
        )
        wheels = list(dist.glob("myzing-*.whl"))
        if build.returncode != 0 or not wheels:
            record("build-wheel", "FAIL", "pip wheel failed",
                   build.stdout + build.stderr)
            return _finish(
                steps, args.report, require_study=args.require_study
            )
        wheel = wheels[0]
        record("build-wheel", "PASS", wheel.name)

        venv_dir = tmpdir / "venv"
        venv.create(venv_dir, with_pip=True)
        vpy = venv_dir / ("Scripts" if os.name == "nt" else "bin") / (
            "python.exe" if os.name == "nt" else "python"
        )
        install = run(
            [str(vpy), "-m", "pip", "install", "--quiet",
             f"myzing[mcp] @ {wheel.as_uri()}"],
            cwd=tmpdir, env=dict(os.environ),
        )
        if install.returncode != 0:
            record("install-wheel", "FAIL", "pip install failed",
                   install.stdout + install.stderr)
            return _finish(
                steps, args.report, require_study=args.require_study
            )
        record("install-wheel", "PASS", "wheel + [mcp] extra installed")

        # The new-user environment: neutral cwd, isolated workspace, and
        # NO repo on any path — the packaged data must carry everything.
        workdir = tmpdir / "userland"
        workdir.mkdir()
        env = dict(os.environ)
        env["ZING_HOME"] = str(tmpdir / "zing-home")
        env.pop("ZING_PROMPTS_DIR", None)
        env.pop("ZING_PRESETS_DIR", None)

        def zing(*cli: str, timeout: int = 600):
            return run([str(vpy), "-m", "myzing.cli", *cli], workdir, env,
                       timeout=timeout)

        r = zing("doctor")
        ok = r.returncode in (0, 1) and "zing doctor" in r.stdout
        record("doctor", "PASS" if ok else "FAIL",
               f"exit {r.returncode} (0/1 both honest)", r.stdout + r.stderr)

        r = zing("doctor", "--json")
        try:
            payload = json.loads(r.stdout)
            names = {c["name"] for c in payload["checks"]}
            ok = "ffmpeg" in names and "tts" in names
            record("doctor-json", "PASS" if ok else "FAIL",
                   f"checks: {sorted(names)}", "")
        except (ValueError, KeyError) as e:
            record("doctor-json", "FAIL", f"unparseable: {e}",
                   r.stdout + r.stderr)

        r = zing("prompt", "study")
        ok = r.returncode == 0 and "Judging a Zing breakdown" in r.stdout
        record("prompt-pack", "PASS" if ok else "FAIL",
               "packaged study.md served" if ok else f"exit {r.returncode}",
               "" if ok else r.stdout + r.stderr)

        r = zing("setup", "--list")
        ok = r.returncode == 0 and "ai-tech-talking-head" in r.stdout
        record("preset-packs", "PASS" if ok else "FAIL",
               "packaged packs listed" if ok else f"exit {r.returncode}",
               r.stdout + r.stderr)

        if args.skip_study:
            record("study-cached-media", "SKIP", "--skip-study")
        elif not shutil.which("ffmpeg"):
            if args.require_study:
                record(
                    "study-cached-media",
                    "FAIL",
                    "ffmpeg is required by --require-study but is not on PATH",
                )
            else:
                record(
                    "study-cached-media", "SKIP", "no ffmpeg on this host"
                )
        else:
            clip = workdir / "clip.mp4"
            gen = run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=red:s=320x568:d=2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)],
                workdir, dict(os.environ),
            )
            if gen.returncode != 0:
                record("study-cached-media", "FAIL", "clip generation failed",
                       gen.stderr)
            else:
                r = zing("study", str(clip), timeout=900)
                ok = r.returncode == 0 and "breakdown" in (
                    r.stdout + r.stderr
                ).lower()
                record("study-cached-media", "PASS" if ok else "FAIL",
                       f"exit {r.returncode}", r.stdout + r.stderr)

    return _finish(
        steps, args.report, require_study=args.require_study
    )


def _finish(
    steps: list[dict],
    report: Path | None,
    *,
    require_study: bool = False,
) -> int:
    if require_study:
        study = next(
            (step for step in steps if step["step"] == "study-cached-media"),
            None,
        )
        if study is None:
            steps.append({
                "step": "study-cached-media",
                "status": "FAIL",
                "detail": "required study step was not reached",
                "output_tail": "",
            })
        elif study["status"] == "SKIP":
            study["status"] = "FAIL"
            study["detail"] = f"required study was skipped: {study['detail']}"
    failed = [s for s in steps if s["status"] == "FAIL"]
    summary = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "steps": steps,
        "failed": len(failed),
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nclean-host gate: {len(steps)} steps, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
