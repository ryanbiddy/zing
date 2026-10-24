"""Test an already-built wheel in two pristine venvs, outside the checkout.

Dependency installation uses the package index. Every product process then
blocks network connections, uses empty model caches and an isolated ZING_HOME.
No FFmpeg or downloaded models are required for this still-image acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
BLOCK_NETWORK = '''import sys
import socket
def deny(event, args):
    # Windows implements socketpair using a private loopback connection.
    # Allow only the stdlib caller, never application/service connections.
    pair = getattr(socket, "_fallback_socketpair", None)
    if (event == "socket.connect" and pair is not None
            and sys._getframe(1).f_code is pair.__code__
            and args[1][0] in {"127.0.0.1", "::1"} and args[1][1] != 5179):
        return
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise OSError("fresh-install: network disabled")
sys.addaudithook(deny)
'''


def run_check(wheel: Path, root: Path, extras: str) -> list[dict]:
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
    venv.create(folder, with_pip=True)
    bindir = folder / ("Scripts" if os.name == "nt" else "bin")
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    zing = bindir / ("zing.exe" if os.name == "nt" else "zing")
    steps = []

    def call(name, command, allowed=(0,), timeout=600):
        result = subprocess.run([str(c) for c in command], cwd=root, env=env,
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        steps.append({"step": name, "returncode": result.returncode,
                      "output_tail": (result.stdout + result.stderr)[-3000:]})
        (root / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode not in allowed:
            raise RuntimeError(f"{extras}: {name} exited {result.returncode}: {steps[-1]['output_tail']}")
        print(f"PASS [{extras}] {name}", flush=True)
        return result.stdout

    # Direct wheel reference prevents testing an older release on the index.
    call("install", [python, "-m", "pip", "install", f"myzing[{extras}] @ {wheel.as_uri()}"], timeout=1200)
    call("pip-check", [python, "-m", "pip", "check"])
    site = call("site", [python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"]).strip()
    (Path(site) / "sitecustomize.py").write_text(BLOCK_NETWORK, encoding="utf-8")
    call("socket-block", [python, "-c", "import socket\ntry: socket.create_connection(('127.0.0.1', 1))\nexcept OSError as e: assert 'network disabled' in str(e)\nelse: raise AssertionError('network enabled')"])
    call("installed-origin", [python, "-c",
         "import myzing, sys; from pathlib import Path; "
         "assert Path(myzing.__file__).is_relative_to(Path(sys.prefix)); print(myzing.__version__)"])
    help_text = call("help", [zing, "--help"])
    assert help_text.startswith("Start here: zing studio"), help_text
    doctor = call("doctor", [zing, "doctor"], allowed=(0, 1))
    assert "zing doctor" in doctor
    call("prompt-pack", [zing, "prompt", "study"])
    call("presets", [zing, "setup", "--list"])
    smoke = root / "mcp_stdio_smoke.py"
    shutil.copyfile(ROOT / "packaging/mcp_stdio_smoke.py", smoke)
    payload = json.loads(call("mcp-stdio", [python, smoke], timeout=180))
    assert payload["ok"] and payload["tool_count"] == 36 and payload["called"] == "zing_status", payload
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
    call("studio", [zing, "studio", "--answers", answer_file, "--yes", "--json"])
    result = json.loads((root / "studio/studio-result.json").read_text(encoding="utf-8"))
    assert result["ok"] and result["status"] == "ready" and result["outputs"], result
    outputs = [Path(p) for p in result["outputs"]]
    assert all(p.is_file() and p.is_relative_to(root) for p in outputs)
    call("decode-stills", [python, "-c",
         "import json; from PIL import Image; from pathlib import Path; "
         "r=json.loads(Path('studio/studio-result.json').read_text(encoding='utf-8')); "
         "images=[p for p in r['outputs'] if p.endswith('.png')]; assert images; "
         "[(Image.open(p).verify()) for p in images]; print(images)"])
    return steps


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
        root = Path(temporary.name)
    report = {"wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "platform": sys.platform, "checks": {}, "ok": False}
    try:
        for extras in ("mcp,render,memes", "all"):
            report["checks"][extras] = run_check(wheel, root / extras.replace(",", "-"), extras)
        report["ok"] = True
    except (OSError, RuntimeError, AssertionError, ValueError, subprocess.TimeoutExpired) as exc:
        report["error"] = str(exc)
        print(f"FAIL: {exc}", file=sys.stderr)
    finally:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if temporary:
            temporary.cleanup()
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
