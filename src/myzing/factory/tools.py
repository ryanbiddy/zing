"""Find the external programs the factory runs: FFmpeg, Node, the factory sidecar and a local Chrome or Edge.

Read-only discovery: nothing here installs, downloads or signs in.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from importlib import resources
from pathlib import Path

DATA = resources.files("myzing") / "_data" / "factory"
_processes = ContextVar("factory_processes", default=None)


class FactoryError(RuntimeError):
    """An actionable factory failure."""


class Stopped(BaseException):
    pass


class Processes:
    def __init__(self):
        self.lock = threading.Lock()
        self.child = None
        self.stopped = False

    @contextmanager
    def scope(self):
        token = _processes.set(self)
        try:
            yield
        finally:
            _processes.reset(token)

    def stop(self):
        with self.lock:
            self.stopped = True
            if self.child and self.child.poll() is None:
                self.kill(self.child)

    def kill(self, child):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True,
                               timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(child.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            pass
        if child.poll() is None:
            child.kill()


NO_HOOK = "none yet (the clip was picked by hand): write one from what is said"


def data_path(*parts: str) -> Path:
    return Path(str(DATA.joinpath(*parts)))


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FactoryError("FFmpeg is missing; run 'zing setup ffmpeg' or put ffmpeg on PATH.")
    return found


def ffprobe() -> str:
    found = shutil.which("ffprobe")
    if not found:
        raise FactoryError("ffprobe is missing; it ships with FFmpeg ('zing setup ffmpeg').")
    return found


def sidecar_directory() -> Path:
    configured = os.environ.get("ZING_FACTORY_SIDECAR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[3] / "tools" / "factory-sidecar"


BROWSER_CANDIDATES = {
    "win32": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
              r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
              r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
              r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
              r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"],
    "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
}


def browser() -> str:
    for name in ("ZING_BROWSER_PATH", "HYPERFRAMES_BROWSER_PATH"):
        if os.environ.get(name) and Path(os.environ[name]).is_file():
            return os.environ[name]
    for raw in BROWSER_CANDIDATES.get(sys.platform, []):
        path = Path(os.path.expandvars(raw))
        if path.is_file():
            return str(path)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        if shutil.which(name):
            return shutil.which(name)
    raise FactoryError("No Chrome or Edge found; install one or set ZING_BROWSER_PATH to its executable.")


def node_sidecar() -> tuple[str, Path]:
    node = shutil.which("node")
    if not node:
        raise FactoryError("Node is missing; install Node.js 20 or newer and put node on PATH.")
    sidecar = sidecar_directory()
    if not (sidecar / "node_modules" / "playwright-core" / "package.json").is_file():
        raise FactoryError(f"The factory sidecar is not installed; run 'npm ci' in {sidecar}.")
    return node, sidecar


def sidecar_env(tmp: Path | None = None) -> dict[str, str]:
    """The sidecar's environment: the browser path, and never the stock-library keys."""
    from .visuals import KEY_NAMES
    env = {k: v for k, v in os.environ.items() if k not in KEY_NAMES}
    env["ZING_BROWSER_PATH"] = browser()
    if tmp:
        tmp.mkdir(parents=True, exist_ok=True)
        env["TEMP"] = env["TMP"] = str(tmp)
    return env


@contextmanager
def process(argv, **kwargs):
    owner = _processes.get()
    if owner:
        if os.name == "nt":
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
    with owner.lock if owner else nullcontext():
        if owner and owner.stopped:
            raise Stopped
        child = subprocess.Popen(argv, **kwargs)
        if owner:
            owner.child = child
    try:
        yield child
    finally:
        if owner:
            with owner.lock:
                owner.child = None
            if owner.stopped:
                raise Stopped


def run(*argv, **kwargs) -> subprocess.CompletedProcess:
    argv = [str(a) for a in argv]
    kwargs.setdefault("check", True)
    owner = _processes.get()
    if owner is None:
        return subprocess.run(argv, **kwargs)
    check, timeout = kwargs.pop("check"), kwargs.pop("timeout", None)
    data = kwargs.pop("input", None)
    if data is not None:
        kwargs["stdin"] = subprocess.PIPE
    if kwargs.pop("capture_output", False):
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    with process(argv, **kwargs) as child, child:
        try:
            stdout, stderr = child.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            owner.kill(child)
            exc.stdout, exc.stderr = child.communicate()
            raise
        except BaseException:
            owner.kill(child)
            child.communicate()
            raise
        if check and child.returncode:
            raise subprocess.CalledProcessError(child.returncode, argv, stdout, stderr)
        return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)


def check() -> dict:
    """Doctor-style report of every prerequisite; never raises."""
    out = {}
    for name, probe in (("ffmpeg", ffmpeg), ("browser", browser), ("sidecar", lambda: str(node_sidecar()[1]))):
        try:
            out[name] = {"ok": True, "path": probe()}
        except FactoryError as exc:
            out[name] = {"ok": False, "fix": str(exc)}
    out["claude"] = {"ok": bool(shutil.which("claude")),
                     **({} if shutil.which("claude") else {"fix": "Optional: install Claude Code to use --judge claude."})}
    try:
        from myzing.layout.detector import model_path, verified_model
        out["face_model"] = {"ok": verified_model(model_path())} | (
            {} if verified_model(model_path()) else {"fix": "Run 'zing layout fetch-model'."})
    except Exception as exc:
        out["face_model"] = {"ok": False, "fix": f"{exc}"}
    from . import cutout, depth, upscale
    out["depth_model"] = {"ok": depth.ready()} | ({} if depth.ready() else
                                                  {"fix": f"Optional: photos move through their depth after {depth.FETCH_HINT}."})
    out["cutout_model"] = {"ok": cutout.ready()} | ({} if cutout.ready() else
                                                    {"fix": f"Optional: --cutout stands the speaker in front of pictures after {cutout.FETCH_HINT}."})
    out["upscaler"] = {"ok": upscale.ready()} | ({} if upscale.ready() else
                                                 {"fix": f"Optional: small photos render sharp after {upscale.FETCH_HINT}."})
    from .visuals import KEY_NAMES, get_key
    out["stock_keys"] = {name: ("present" if get_key(name) else "absent") for name in KEY_NAMES}
    return out
