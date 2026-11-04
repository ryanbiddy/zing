"""`zing factory serve`: the local review dashboard for one project.

The agent produces the pack; this page is where a person watches, rates, swaps a visual, fixes a hook or copy,
re-renders, picks a clip from the transcript, moves a clip's in and out points, or makes one of the scout's runners-up. It binds 127.0.0.1 only, answers only to localhost Host headers, refuses cross-origin writes, and serves
files only from the project's clip folders. Nothing here posts or publishes.
"""
from __future__ import annotations

import json
import mimetypes
import queue
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import pick, pipeline, plan, render
from .judge import Judge
from .tools import FactoryError, data_path

CLIP = re.compile(r"^clip\d{2}$")
MEDIA = {".mp4", ".webm", ".jpg", ".jpeg", ".png", ".webp"}
TEXT_FIELDS = {"x", "instagram", "tiktok", "youtube_title", "first_comment"}


def _read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class Studio:
    """Project state for the page, and a single worker so renders never overlap."""

    def __init__(self, project: Path, judge: str = "host"):
        self.project, self.judge = Path(project).resolve(), judge
        if not (self.project / "factory.json").is_file():
            raise FactoryError(f"{self.project} is not a factory project")
        self.jobs: queue.Queue = queue.Queue()
        self.active: list[str] = []
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        while True:
            label, job = self.jobs.get()
            self.active.append(label)
            try:
                job()
            except Exception as exc:                       # surfaced on the page, never kills the server
                _write(self.project / "status.json", {**(_read(self.project / "status.json") or {}),
                                                      "error": f"{label}: {exc}"[:400]})
            finally:
                self.active.remove(label)

    def queue(self, label: str, job) -> dict:
        self.jobs.put((label, job))
        return {"queued": label}

    def state(self) -> dict:
        st = pipeline.status(self.project)
        ratings = _read(self.project / "ratings.json", {})
        clips = []
        for c in st["clips"]:
            d = self.project / c["clip"]
            vis = d / "visuals"
            clips.append({**c, "plan": _read(d / "plan.json"), "post": _read(d / "post.json"),
                          "receipt": _read(d / "receipt.json"),
                          "visual_requests": _read(vis / "requests.json"), "candidates": _read(vis / "manifest.json"),
                          "picks": _read(vis / "picks.json"), "rating": ratings.get(c["clip"]),
                          "videos": {p.name: p.name for p in sorted(d.glob("clip*.mp4"))}})
        st.update(clips=clips, packs={name: render.theme(name).get("name", name) for name in render.themes()},
                  jobs=list(self.active) + [label for label, _ in list(self.jobs.queue)])
        st["project"] = self.project.name
        st.pop("review", None)
        return st

    def clipdir(self, clip: str) -> Path:
        if not isinstance(clip, str) or not CLIP.match(clip) or not (self.project / clip).is_dir():
            raise FactoryError(f"unknown clip {clip!r}")
        return self.project / clip

    def _rerender(self, d: Path) -> None:
        cfg = _read(self.project / "factory.json", {})
        for shape in cfg.get("shapes", ["9x16"]):
            render.render(d, shape, cfg.get("pack", "zing"))

    # ---------------------------------------------------------------- actions
    def run(self, _body: dict) -> dict:
        return self.queue("run", lambda: pipeline.run(self.project, Judge(self.project, self.judge), say=lambda m: None))

    def _make(self, label: str, change) -> dict:
        """Change the moments, then run just that clip: queued, so it never races a run already going."""
        def job():
            clip = change()
            pipeline.run(self.project, Judge(self.project, self.judge), only={int(clip[4:])}, say=lambda m: None)
        return self.queue(label, job)

    def transcript(self) -> dict:
        segments = _read(self.project / "transcript.json") or []
        return {"segments": [{"s": s["s"], "e": s["e"], "text": s["text"]} for s in segments]}

    def rate(self, body: dict) -> dict:
        return pipeline.rate(self.project, body.get("clip"), body.get("v"), body.get("why") or "")

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
        if not isinstance(index, int) or not 0 <= index < len(pipeline.status(self.project)["bench"]):
            raise FactoryError("no such runner-up")
        return self._make("runner-up", lambda: pipeline.make_bench(self.project, index))

    def visual(self, body: dict) -> dict:
        d = self.clipdir(body.get("clip"))
        vis = d / "visuals"
        manifest, raw = _read(vis / "manifest.json", {}), _read(d / "plan-raw.json")
        request, index = body.get("request"), body.get("index")
        if raw is None or request not in manifest or not isinstance(index, int) or not 0 <= index < len(manifest[request]):
            raise FactoryError("no such visual candidate")
        picks = _read(vis / "picks.json", {"picks": {}})
        picks["picks"][request] = {"pick": index, "why": "chosen in the dashboard"}
        _write(vis / "picks.json", picks)

        def job():
            plan.finalize(d, raw, pick.chosen(vis, raw.get("visual_requests", []), manifest, picks["picks"]))
            self._rerender(d)
        return self.queue(f"{d.name}: new visual", job)

    def text(self, body: dict) -> dict:
        d = self.clipdir(body.get("clip"))
        field, value = body.get("field"), str(body.get("text") or "").strip()
        if not value:
            raise FactoryError("text cannot be empty")
        if field in TEXT_FIELDS:
            post = _read(d / "post.json", {})
            post[field] = value[:2200]
            _write(d / "post.json", post)
            return {"saved": field}
        if field != "hook":
            raise FactoryError(f"unknown field {field!r}")
        raw = _read(d / "plan-raw.json")
        current = _read(d / "plan.json")
        if raw is None or current is None:
            raise FactoryError("this clip has no plan yet")
        raw["hook"] = value[:120]
        _write(d / "plan-raw.json", raw)

        def job():
            plan.finalize(d, raw, current.get("visuals", {}))    # re-runs the hook fact check
            self._rerender(d)
        return self.queue(f"{d.name}: new hook", job)

    def rerender(self, body: dict) -> dict:
        d = self.clipdir(body.get("clip"))
        shape, pack = body.get("shape", "9x16"), body.get("pack", "zing")
        if shape not in render.SHAPES:
            raise FactoryError(f"unknown shape {shape!r}")
        render.theme(pack)
        return self.queue(f"{d.name}: {shape} {pack}", lambda: render.render(d, shape, pack))

    def media(self, path: str) -> Path:
        parts = [unquote(p) for p in path.split("/") if p]
        if not parts or not CLIP.match(parts[0]):
            raise FactoryError("not found")
        target = (self.project / Path(*parts)).resolve()
        if not target.is_relative_to(self.project / parts[0]) or target.suffix.lower() not in MEDIA or not target.is_file():
            raise FactoryError("not found")
        return target


def handler(studio: Studio, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    actions = {"/api/run": studio.run, "/api/rate": studio.rate, "/api/visual": studio.visual,
               "/api/text": studio.text, "/api/render": studio.rerender, "/api/clip": studio.clip,
               "/api/trim": studio.trim, "/api/bench": studio.bench}
    page = data_path("dashboard.html")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):                   # quiet; the page shows state
            pass

        def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, value) -> None:
            self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json")

        def _trusted(self) -> bool:
            return self.headers.get("Host", "") in hosts

        def do_GET(self):
            if not self._trusted():
                return self._json(403, {"error": "localhost only"})
            path = urlsplit(self.path).path
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
            with target.open("rb") as f:
                f.seek(start)
                body = f.read(end - start + 1)
            extra = {"Accept-Ranges": "bytes"}
            if rng:
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
            self._send(206 if rng else 200, body, kind, extra)

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self._trusted() or (origin and urlsplit(origin).netloc not in hosts):
                return self._json(403, {"error": "localhost only"})
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(415, {"error": "send JSON"})
            action = actions.get(urlsplit(self.path).path)
            if not action:
                return self._json(404, {"error": "not found"})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 64 << 10)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise FactoryError("send a JSON object")
                self._json(200, {"ok": True, **action(body)})
            except (FactoryError, ValueError) as exc:
                self._json(400, {"ok": False, "error": str(exc)})

    return Handler


def serve(project: Path, port: int = 8765, judge: str = "host", say=print) -> None:
    studio = Studio(project, judge)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(studio, port))
    say(f"Zing factory dashboard: http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
