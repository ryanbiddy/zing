"""Find the external programs the factory runs: FFmpeg, Node, the factory sidecar and a local Chrome or Edge.

Discovery is read-only. Only setup installs the sidecar.
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

from myzing.storage import resolve_workspace

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
    if configured:
        return Path(configured).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[3] / "tools" / "factory-sidecar"
    return checkout if checkout.is_dir() else resolve_workspace() / "factory-sidecar"


def node_version() -> tuple[str, str]:
    node = shutil.which("node")
    if not node:
        raise FactoryError("Node is missing. Install Node.js 20 or newer and put node on PATH.")
    try:
        version = run(node, "--version", capture_output=True, text=True, timeout=10).stdout.strip()
        if int(version.lstrip("v").split(".")[0]) < 20:
            raise ValueError(version)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise FactoryError("Node.js 20 or newer is required. Install it and retry.") from exc
    return node, version


def setup(*, say=print) -> Path:
    node_version()
    sidecar = sidecar_directory()
    lock = sidecar / "package-lock.json"
    packaged = DATA / "sidecar"
    ready = (lock.is_file() and lock.read_bytes() == (packaged / lock.name).read_bytes()
             and (sidecar / "node_modules/playwright-core/package.json").is_file())
    npm = shutil.which("npm")
    if not ready and not npm:
        raise FactoryError("npm is missing. Install Node.js 20 or newer with npm and put npm on PATH.")
    sidecar.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json", "shot.cjs"):
        (sidecar / name).write_bytes((packaged / name).read_bytes())
    if not ready:
        say(str(sidecar))
        say("npm ci")
        run(npm, "ci", cwd=sidecar)
    say(f"Factory sidecar is ready in {sidecar}.")
    return sidecar


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
        raise FactoryError("The factory sidecar is not installed. Run 'zing factory setup'.")
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
    try:
        node, version = node_version()
        out["node"] = {"ok": True, "path": node, "version": version}
    except FactoryError as exc:
        out["node"] = {"ok": False, "fix": str(exc)}
    for name, probe in (("ffmpeg", ffmpeg), ("browser", browser), ("sidecar", lambda: str(node_sidecar()[1]))):
        try:
            out[name] = {"ok": True, "path": probe()}
        except FactoryError as exc:
            out[name] = {"ok": False, "fix": str(exc)}
    out["claude"] = {"ok": bool(shutil.which("claude")),
                     **({} if shutil.which("claude") else {"fix": "Optional: install Claude Code to use --judge claude."})}
    try:
        from myzing.layout.detector import model_path, model_hint, verified_model
        valid = verified_model(model_path())
        out["face_model"] = {"ok": valid} | ({} if valid else {"fix": model_hint(model_path())})
    except Exception as exc:
        out["face_model"] = {"ok": False, "fix": f"{exc}"}
    from . import cutout, depth, upscale
    out["depth_model"] = {"ok": depth.ready()} | ({} if depth.ready() else
                                                  {"fix": f"Optional: photos move through their depth after {depth.FETCH_HINT}."})
    out["cutout_model"] = {"ok": cutout.ready()} | ({} if cutout.ready() else
                                                    {"fix": f"Optional: --cutout stands the speaker in front of pictures after {cutout.FETCH_HINT}."})
    out["upscaler"] = {"ok": upscale.ready()} | ({} if upscale.ready() else
                                                 {"fix": f"Optional: small photos render sharp after {upscale.FETCH_HINT}."})
    try:
        from .visuals import KEY_NAMES, get_key
        out["stock_keys"] = {name: ("present" if get_key(name) else "absent") for name in KEY_NAMES}
    except ImportError:
        from myzing.doctor import _install_command
        out["stock_keys"] = {"ok": False, "fix": _install_command("myzing[factory]")}
    return out
