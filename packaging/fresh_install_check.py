"""Test an already-built wheel in two pristine venvs, outside the checkout.

Dependency installation uses the package index. Every product process then
blocks network connections, uses empty model caches and an isolated ZING_HOME.
No FFmpeg or downloaded models are required for this still-image acceptance.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BLOCK_NETWORK = '''import sys
import socket
def deny(event, args):
    if event not in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        return
    # Windows implements socketpair using a private loopback connection.
    # Allow only the stdlib caller, never application/service connections.
    caller = sys._getframe(1).f_code
    if (event == "socket.connect"
            and caller.co_name in {"socketpair", "_fallback_socketpair"}
            and caller.co_filename == socket.__file__
            and args[1][0] in {"127.0.0.1", "::1"} and args[1][1] != 5179):
        return
    raise OSError("fresh-install: network disabled")
sys.addaudithook(deny)
'''


class StepError(RuntimeError):
    def __init__(self, step):
        self.step = step
        super().__init__(f"{step['step']} exited {step['returncode']}: "
                         f"{step['stderr_tail'] or step['stdout_tail']}")


def text_output(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


class Recorder:
    """Checkpoint before launch and after completion, including failed validation."""

    def __init__(self, root, env, extras, steps, checkpoint):
        self.root, self.env, self.extras = root, env, extras
        self.steps, self.checkpoint = steps, checkpoint

    def __call__(self, name, command, allowed=(0,), timeout=600, validate=None):
        command = [str(c) for c in command]
        step = {"step": name, "command": command, "returncode": None,
                "stdout_tail": "", "stderr_tail": "", "status": "running"}
        self.steps.append(step)
        self.checkpoint()
        print(f"RUN [{self.extras}] {name}: {subprocess.list2cmdline(command)}", flush=True)
        stdout = stderr = ""
        try:
            result = subprocess.run(command, cwd=self.root, env=self.env,
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=timeout)
            stdout, stderr = result.stdout, result.stderr
            step.update(returncode=result.returncode, stdout_tail=stdout[-6000:],
                        stderr_tail=stderr[-6000:])
            if result.returncode not in allowed:
                raise StepError(step)
            if validate:
                validate(stdout)
            step["status"] = "passed"
        except Exception as exc:
            if isinstance(exc, subprocess.TimeoutExpired):
                stdout, stderr = text_output(exc.stdout), text_output(exc.stderr)
                step.update(stdout_tail=stdout[-6000:], stderr_tail=stderr[-6000:])
            step.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                        traceback=traceback.format_exc())
            raise
        finally:
            (self.root / (name + ".log")).write_text(
                stdout + "\n--- stderr ---\n" + stderr + step.get("traceback", ""), encoding="utf-8")
            self.checkpoint()
        print(f"PASS [{self.extras}] {name}", flush=True)
        return stdout


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_studio(root):
    root = root.resolve(strict=True)
    result = json.loads((root / "studio/studio-result.json").read_text(encoding="utf-8"))
    require(result.get("ok") and result.get("status") == "ready" and result.get("outputs"),
            f"studio did not produce ready outputs: {result!r}")
    for output in result["outputs"]:
        path = Path(output).resolve(strict=True)
        require(path.is_file() and path.is_relative_to(root),
                f"studio output {output!r} resolves to {str(path)!r}, outside run root {str(root)!r} or not a file")


def run_check(wheel: Path, root: Path, extras: str, steps: list, checkpoint) -> None:
    # macOS /var -> /private/var and Windows short names/junctions must compare
    # against the same canonical paths used by studio and the venv interpreter.
    root = root.resolve()
    root.mkdir(parents=True)
    env = dict(os.environ, UOINK_URL="http://127.0.0.1:1",
               ZING_HOME=str(root / "home"), HF_HOME=str(root / "models"),
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    for key in ("PYTHONPATH", "PYTHONHOME", "ZING_PROMPTS_DIR", "ZING_PRESETS_DIR",
                "UOINK_TOKEN", "ELEVENLABS_API_KEY"):
        env.pop(key, None)
    folder = root / "venv"
    bindir = folder / ("Scripts" if os.name == "nt" else "bin")
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    zing = bindir / ("zing.exe" if os.name == "nt" else "zing")
    call = Recorder(root, env, extras, steps, checkpoint)
    call("venv", [sys.executable, "-m", "venv", folder])

    # Direct wheel reference prevents testing an older release on the index.
    call("install", [python, "-m", "pip", "install", f"myzing[{extras}] @ {wheel.as_uri()}"], timeout=1200)
    call("pip-check", [python, "-m", "pip", "check"])
    site = call("site", [python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"]).strip()
    (Path(site) / "sitecustomize.py").write_text(BLOCK_NETWORK, encoding="utf-8")
    call("socket-block", [python, "-c", "import socket\ntry: socket.create_connection(('127.0.0.1', 1))\nexcept OSError as e: assert 'network disabled' in str(e)\nelse: raise AssertionError('network enabled')"])
    call("installed-origin", [python, "-c",
         "import myzing, sys; from pathlib import Path; "
         "assert Path(myzing.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), myzing.__file__; print(myzing.__version__)"])
    call("help", [zing, "--help"], validate=lambda text: require(
        "Start here: zing studio" in text.split("usage:", 1)[0], f"unexpected help opening: {text[:500]!r}"))
    call("doctor", [zing, "doctor"], allowed=(0, 1), validate=lambda text: require(
        "zing doctor" in text, f"missing doctor report: {text[:500]!r}"))
    call("prompt-pack", [zing, "prompt", "study"])
    call("presets", [zing, "setup", "--list"])
    smoke = root / "mcp_stdio_smoke.py"
    shutil.copyfile(ROOT / "packaging/mcp_stdio_smoke.py", smoke)
    def validate_mcp(text):
        payload = json.loads(text)
        require(payload.get("ok") and payload.get("tool_count") == 37 and payload.get("called") == "zing_status",
                f"unexpected MCP exchange: {payload!r}")

    call("mcp-stdio", [python, smoke], timeout=180, validate=validate_mcp)
    photos = root / "photos"
    photos.mkdir()
    call("generate-image", [python, "-c",
         "from PIL import Image, ImageDraw; im=Image.new('RGB',(1200,1200),'#255678'); "
         "ImageDraw.Draw(im).rectangle((350,350,850,850),fill='#efbd44'); im.save('photos/sample.png')"])
    answers = {"path": "c", "project": str(root / "studio"), "photos": str(photos),
               "topic": "finishing the first draft", "platform": "square", "allow_download": False}
    answer_file = root / "answers.json"
    answer_file.write_text(json.dumps(answers), encoding="utf-8")
    # Studio's photo path is offline by design; no --offline CLI option exists.
    # Explicit no-download answers, offline env flags and the socket guard enforce it.
    call("studio", [zing, "studio", "--answers", answer_file, "--yes", "--json"],
         validate=lambda _: validate_studio(root))
    call("decode-stills", [python, "-c",
         "import json; from PIL import Image; from pathlib import Path; "
         "r=json.loads(Path('studio/studio-result.json').read_text(encoding='utf-8')); "
         "images=[p for p in r['outputs'] if p.endswith('.png')]; assert images, 'studio produced no PNG outputs'; "
         "[(Image.open(p).verify()) for p in images]; print(images)"])


def optional_extras(wheel):
    """Read the artifact, not possibly different checkout dependency metadata."""
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        message = BytesParser().parsebytes(archive.read(metadata))
    return sorted(set(message.get_all("Provides-Extra", [])) - {"all", "dev", "mcp", "render", "memes"})


def unavailable_extra(exc):
    """Only explicit pip availability errors qualify, never smoke or transport failures."""
    step = exc.step
    error = step["stderr_tail"] + step["stdout_tail"]
    if step["step"] != "install" or re.search(
            r"retrying|connection|timed? out|ssl|certificate|403|401|resolutionimpossible", error, re.I):
        return False
    return bool(re.search(r"No matching distribution found|Could not find a version that satisfies"
                          r"|not a supported wheel on this platform", error, re.I))


def check_environments(wheel, root, report, checkpoint):
    def check(label, extras):
        steps = report["checks"][label] = []
        report["environments"][label] = "running"
        checkpoint()
        try:
            run_check(wheel, root / label.replace(",", "-"), extras, steps, checkpoint)
        except Exception:
            report["environments"][label] = "failed"
            checkpoint()
            raise
        report["environments"][label] = "passed"
        checkpoint()

    def limitation(label, exc):
        report["environments"][label] = "platform_limitation"
        report["platform_limitations"].append({"extras": label, "platform": sys.platform,
                                             "machine": platform.machine(), "pip_error": exc.step})
        print(f"PLATFORM LIMITATION [{label}]: {exc}", file=sys.stderr, flush=True)
        # Handled optional install errors still retain and print their full traceback.
        traceback.print_exc()
        checkpoint()

    check("mcp,render,memes", "mcp,render,memes")  # Always fatal on failure.
    try:
        check("all", "all")
    except StepError as exc:
        if not unavailable_extra(exc):
            raise
        all_failure = exc
        # Independent venvs prevent a failed install from contaminating later checks.
        for extra in optional_extras(wheel):
            label = "optional-" + extra
            try:
                check(label, "mcp,render,memes," + extra)
            except StepError as optional_error:
                if not unavailable_extra(optional_error):
                    raise
                limitation(label, optional_error)
        # If no constituent failed, the aggregate install is broken, not unavailable.
        if not report["platform_limitations"]:
            raise all_failure
        limitation("all", all_failure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, help="new directory; retain logs, images and venvs")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    wheels = [args.wheel] if args.wheel else list(args.dist.glob("*.whl"))
    if len(wheels) != 1:
        parser.error("supply exactly one built wheel")
    wheel = wheels[0].resolve(strict=True)
    temporary = None
    if args.work_dir:
        root = args.work_dir.resolve()
        root.mkdir(parents=True, exist_ok=False)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="zing-fresh-")
        root = Path(temporary.name).resolve()
    report = {"wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "platform": sys.platform, "machine": platform.machine(),
              "python": sys.version, "work_dir": str(root), "checks": {},
              "environments": {}, "platform_limitations": [], "ok": False, "status": "running"}

    def checkpoint():
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    try:
        check_environments(wheel, root, report, checkpoint)
        report["ok"] = True
        report["status"] = "passed_with_platform_limitations" if report["platform_limitations"] else "passed"
    except Exception as exc:
        report.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(), status="failed")
        print(f"FAIL: {report['error']}", file=sys.stderr)
        traceback.print_exc()
    finally:
        checkpoint()
        if temporary:
            temporary.cleanup()
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
