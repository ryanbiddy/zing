"""`zing factory serve`: the local review dashboard for one project.

The agent produces the pack; this page is where a person watches, rates, swaps a visual, fixes a hook or copy,
re-renders, picks a clip from the transcript, moves a clip's in and out points, or makes one of the scout's runners-up. It binds 127.0.0.1 only, answers only to localhost Host headers, refuses cross-origin writes, and serves
files only from the project's clip folders. Nothing here posts or publishes.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import queue
import re
import secrets
import threading
import time
from functools import cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import edit, pipeline, plan, render
from .edit import CLIP, TEXT_FIELDS
from .judge import Judge
from .tools import FactoryError, Processes, Stopped, data_path

MEDIA = {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"}


def _read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


@cache
def _project_lock(project: Path):
    return threading.RLock()


class Studio:
    """Project state for the page, and a single worker so renders never overlap."""

    def __init__(self, project: Path, judge: str = "host"):
        self.project, self.judge = Path(project).resolve(), judge
        if not (self.project / "factory.json").is_file():
            raise FactoryError(f"{self.project} is not a factory project")
        self.jobs: queue.Queue = queue.Queue()
        self.active: list[str] = []
        self.lock = _project_lock(self.project)
        self._guard = threading.Lock()
        self.worker = None
        self.stopped = threading.Event()
        self.processes = Processes()

    def _work(self) -> None:
        while not self.stopped.is_set():
            with self._guard:
                try:
                    label, job = self.jobs.get_nowait()
                except queue.Empty:
                    self.worker = None
                    return
                self.active.append(label)
            try:
                with self.processes.scope():       # saves take the lock; a long render must not block them
                    if self.stopped.is_set():
                        return
                    job()
            except Stopped:
                return
            except Exception as exc:                       # surfaced on the page, never kills the server
                with self.lock:
                    try:
                        state = _read(self.project / "status.json")
                    except Exception:
                        state = None
                    try:
                        _write(self.project / "status.json", {**(state if isinstance(state, dict) else {}),
                                                              "error": f"{label}: {exc}"[:400]})
                    except Exception:
                        pass
            finally:
                with self._guard:
                    self.active.remove(label)
                self.jobs.task_done()

    def queue(self, label: str, job) -> dict:
        with self._guard:
            if self.stopped.is_set():
                raise FactoryError("dashboard is stopping")
            self.jobs.put((label, job))
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._work, daemon=False)
                self.worker.start()
        return {"queued": label}

    def close(self) -> None:
        with self._guard:
            self.stopped.set()
            worker = self.worker
        self.processes.stop()
        if worker:
            worker.join()

    def state(self) -> dict:
        st = pipeline.status(self.project)
        ratings = _read(self.project / "ratings.json", {})
        clips = []
        for c in st["clips"]:
            d = self.project / c["clip"]
            vis = d / "visuals"
            clips.append({**c, "plan": _read(d / "plan.json"), "post": _read(d / "post.json"),
                          "receipt": _read(d / "receipt.json"),
                          "context": _read(d / "context.json"),
                          "words": _read(d / "words.json", {}).get("words", []),
                          "brief_check": _read(d / "brief_check.json"),
                          "visual_requests": _read(vis / "requests.json"), "candidates": _read(vis / "manifest.json"),
                          "picks": _read(vis / "picks.json"), "rating": ratings.get(c["clip"]),
                          "videos": {p.name: p.name for p in sorted(d.glob("clip*.mp4"))}})
        with self._guard, self.jobs.mutex:
            jobs = list(self.active) + [label for label, _ in self.jobs.queue]
        st.update(clips=clips, packs={name: render.theme(name).get("name", name) for name in render.themes()}, jobs=jobs)
        st["project"] = self.project.name
        st.pop("review", None)
        return st

    def clipdir(self, clip: str) -> Path:
        return edit.clipdir(self.project, clip)

    def _rerender(self, d: Path) -> None:
        edit._rerender(d)

    def _context(self, d: Path) -> None:
        edit._context(d, Judge(self.project, self.judge))

    # ---------------------------------------------------------------- actions
    def run(self, _body: dict) -> dict:
        return self.queue("run", lambda: pipeline.run(self.project, Judge(self.project, self.judge),
                          say=lambda m: None, stop=self.stopped.is_set))

    def _make(self, label: str, change) -> dict:
        """Change the moments, then run just that clip: queued, so it never races a run already going."""
        def job():
            clip = change()
            pipeline.run(self.project, Judge(self.project, self.judge), only={int(clip[4:])},
                         say=lambda m: None, stop=self.stopped.is_set)
        return self.queue(label, job)

    def transcript(self) -> dict:
        segments = _read(self.project / "transcript.json") or []
        return {"segments": [{"s": s["s"], "e": s["e"], "text": s["text"]} for s in segments]}

    def rate(self, body: dict) -> dict:
        with self.lock:
            return edit.rate(self.project, body.get("clip"), body.get("v"), body.get("why") or "")

    def clip(self, body: dict) -> dict:
        a, b = pipeline.check_range(self.project, body.get("start"), body.get("end"))   # refuse now, not in the queue
        hook = str(body.get("hook") or "")
        return self._make("new clip", lambda: pipeline.add_clip(self.project, a, b, hook))

    def trim(self, body: dict) -> dict:
        clip = body.get("clip")
        pipeline._clip_number(self.project, clip)              # a clip still waiting for its cut has no folder yet
        a, b = pipeline.check_range(self.project, body.get("start"), body.get("end"))
        return self._make(f"{clip}: new in and out", lambda: pipeline.trim(self.project, clip, a, b))

    def bench(self, body: dict) -> dict:
        index = body.get("index")
        bench = pipeline.load_moments(self.project).get("bench", [])
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(bench):
            raise FactoryError("no such runner-up")
        moment = bench[index]

        def change():
            current = pipeline.load_moments(self.project).get("bench", [])
            if moment not in current:
                raise FactoryError("that runner-up is no longer on the bench")
            return pipeline.make_bench(self.project, current.index(moment))
        return self._make("runner-up", change)

    def visual(self, body: dict) -> dict:
        request, index = body.get("request"), body.get("index")
        d, _, _ = edit._check_visual(self.project, body.get("clip"), request, index)
        return self.queue(f"{d.name}: new visual", lambda: edit.visual(self.project, d.name, request, index,
                          why="chosen in the dashboard", context=self._context, rerender=self._rerender))

    def text(self, body: dict) -> dict:
        field, value = body.get("field"), body.get("text")
        d, _, _ = edit._check_text(self.project, body.get("clip"), field, value)
        if field in TEXT_FIELDS:
            with self.lock:
                edit.text(self.project, d.name, field, value)
            return {"saved": field}
        return self.queue(f"{d.name}: new hook", lambda: edit.text(self.project, d.name, field, value,
                          context=self._context, rerender=self._rerender))

    def word(self, body: dict) -> dict:
        clip, index, new = body.get("clip"), body.get("index"), body.get("new")
        at, old = body.get("at"), body.get("old")
        edit._word(self.project, clip, index, at, old, new)
        return self.queue(f"{clip}: new word", lambda: edit.word(self.project, clip, index, new, at=at, old=old,
                          context=self._context, rerender=self._rerender))

    def rerender(self, body: dict) -> dict:
        shape, pack = body.get("shape", "9x16"), body.get("pack", "zing")
        d = edit._check_render(self.project, body.get("clip"), shape, pack)
        return self.queue(f"{d.name}: {shape} {pack}", lambda: edit.rerender(self.project, d.name, shape, pack))

    def media(self, path: str) -> Path:
        parts = [unquote(p) for p in path.split("/") if p]
        if not parts or not CLIP.match(parts[0]):
            raise FactoryError("not found")
        target = (self.project / Path(*parts)).resolve()
        if not target.is_relative_to(self.project / parts[0]) or target.suffix.lower() not in MEDIA or not target.is_file():
            raise FactoryError("not found")
        return target


def handler(studio: Studio, port: int, token: str, on_request=None):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    actions = {"/api/run": studio.run, "/api/rate": studio.rate, "/api/visual": studio.visual,
               "/api/text": studio.text, "/api/render": studio.rerender, "/api/clip": studio.clip,
               "/api/trim": studio.trim, "/api/bench": studio.bench, "/api/word": studio.word}
    page = data_path("dashboard.html")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):                   # quiet; the page shows state
            pass

        def parse_request(self):
            parsed = super().parse_request()
            if parsed and on_request:
                on_request()
            return parsed

        def _headers(self, code: int, length: int, kind: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None) -> None:
            self._headers(code, len(body), kind, extra)
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, value) -> None:
            self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json")

        def _trusted(self) -> bool:
            return self.headers.get("Host", "") in hosts

        def _authenticated(self) -> bool:
            for cookie in self.headers.get("Cookie", "").split(";"):
                name, _, value = cookie.strip().partition("=")
                if name == f"zing_dash_{port}":          # each dashboard keeps its own cookie
                    return hmac.compare_digest(value.encode("utf-8"), token.encode("utf-8"))
            return False

        def _denied(self) -> None:
            self._send(403, b"Open the link printed by `zing factory serve`.\n", "text/plain; charset=utf-8")

        def do_GET(self):
            if not self._trusted():
                return self._json(403, {"error": "localhost only"})
            url = urlsplit(self.path)
            path = url.path
            given = parse_qs(url.query, keep_blank_values=True).get("t")
            if self.command == "GET" and given is not None:
                if len(given) != 1 or not hmac.compare_digest(given[0].encode("utf-8"), token.encode("utf-8")):
                    return self._denied()
                return self._send(303, b"", "text/plain", {"Location": "/" + path.lstrip("/"),
                                  "Set-Cookie": f"zing_dash_{port}={token}; HttpOnly; SameSite=Strict; Path=/"})
            if not self._authenticated():
                return self._denied()
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
                if path == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon")
                if path == "/api/project":
                    return self._json(200, studio.state())
                if path == "/api/transcript":
                    return self._json(200, studio.transcript())
                if path.startswith("/media/"):
                    return self._file(studio.media(path[len("/media/"):]))
            except FactoryError as exc:
                return self._json(404, {"error": str(exc)})
            except (ValueError, OSError) as exc:
                return self._json(500, {"error": str(exc)})
            self._json(404, {"error": "not found"})

        do_HEAD = do_GET

        def _file(self, target: Path) -> None:
            size = target.stat().st_size
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
            start, end = 0, size - 1
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):              # open-ended ranges come back in 8 MB pieces; players ask again
                    start = int(rng.group(1))
                    end = min(size - 1, int(rng.group(2)) if rng.group(2) else start + (8 << 20) - 1)
                else:
                    start = max(0, size - int(rng.group(2)))
                if start > end:
                    return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
            extra = {"Accept-Ranges": "bytes"}
            if rng:
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
            with target.open("rb") as f:
                self._headers(206 if rng else 200, end - start + 1, kind, extra)
                if self.command == "HEAD":
                    return
                f.seek(start)
                left = end - start + 1
                while left:
                    body = f.read(min(left, 1 << 20))
                    if not body:
                        break
                    self.wfile.write(body)
                    left -= len(body)

        def do_POST(self):
            try:
                length = max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                length = 0
            if length > 64 << 10:
                self.close_connection = True
                return self._json(413, {"error": "request too large"})
            raw = self.rfile.read(length)       # read before answering; Windows resets a socket closed with unread data
            origin = self.headers.get("Origin")
            if not self._trusted() or (origin and urlsplit(origin).netloc not in hosts):
                return self._json(403, {"error": "localhost only"})
            if not self._authenticated():
                return self._denied()
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(415, {"error": "send JSON"})
            action = actions.get(urlsplit(self.path).path)
            if not action:
                return self._json(404, {"error": "not found"})
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise FactoryError("send a JSON object")
                self._json(200, {"ok": True, **action(body)})
            except (FactoryError, ValueError) as exc:
                self._json(400, {"ok": False, "error": str(exc)})

    return Handler


def serve(project: Path, port: int = 8765, judge: str = "host", say=print, *, ready=None,
          idle_seconds: float | None = None) -> None:
    studio = Studio(project, judge)
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    last_request = time.monotonic()

    def touched():
        nonlocal last_request
        last_request = time.monotonic()

    server.RequestHandlerClass = handler(studio, server.server_port, token, touched)
    try:
        page = f"http://127.0.0.1:{server.server_port}/?t={token}"
        say(f"Open {page}  (Ctrl+C to stop)")
        if ready:
            ready(page)
        if idle_seconds is None:
            server.serve_forever()
        else:
            while (remaining := idle_seconds - (time.monotonic() - last_request)) > 0:
                server.timeout = min(0.5, remaining)
                server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.server_close()
        finally:
            studio.close()
