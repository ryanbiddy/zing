"""Project network policy and the host-only request ledger."""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .tools import FactoryError

_project = ContextVar("factory_project", default=None)
CLAUDE = "claude CLI (Anthropic)"


@contextmanager
def scope(project: Path):
    token = _project.set(Path(project).resolve())
    try:
        yield
    finally:
        _project.reset(token)


class Network:
    def __init__(self, project: Path | None = None):
        start = project or _project.get()               # outside a project (a model download from anywhere) nothing
        path = Path(start).resolve() if start else None  # is recorded, and no stray ledger lands in the working folder
        self.project = next((p for p in (path, *path.parents) if (p / "factory.json").is_file()), path) if path else None

    @property
    def offline(self) -> bool:
        if self.project is None:
            return False
        path = self.project / "factory.json"
        return bool(json.loads(path.read_text(encoding="utf-8")).get("offline")) if path.is_file() else False

    def check(self, purpose: str) -> None:
        if self.offline:
            raise FactoryError(f"offline project: {purpose} is disabled")

    def record(self, host: str, purpose: str, size: int | None = None, at: str | None = None) -> int | None:
        if self.project is None:
            return None
        row = {"at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "host": host, "purpose": purpose, "bytes": size}
        self.project.mkdir(parents=True, exist_ok=True)
        body = json.dumps({k: v for k, v in row.items() if k != "bytes"}, ensure_ascii=False)[:-1]
        data = (body + ', "bytes": ' + f'{json.dumps(size):>20}' + '}\n').encode("utf-8")
        with (self.project / "network.jsonl").open("ab", buffering=0) as f:
            f.write(data)
            offset = f.tell() - 22                       # update only the fixed-width byte count
            os.fsync(f.fileno())                         # the attempt is durable before any connection
        return offset

    def _finish(self, row):
        if row["size"] is not None and row.get("offset") is not None:
            with (self.project / "network.jsonl").open("r+b", buffering=0) as f:
                f.seek(row["offset"])
                f.write(f'{row["size"]:>20}'.encode("ascii"))

    @contextmanager
    def request(self, url: str, purpose: str):
        self.check(purpose)
        host = CLAUDE if url == CLAUDE else urlsplit(url).hostname
        if not host:
            raise ValueError("network request needs a host")
        row = {"host": host, "purpose": purpose, "size": None,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        row["offset"] = self.record(**row)
        try:
            yield row
        finally:
            self._finish(row)

    def open(self, url, purpose, *, headers=None, timeout=60, method="GET", data=None, validate=None):
        self.check(purpose)
        call = self.request(url, purpose)
        row = call.__enter__()
        row["size"] = 0
        try:
            if validate:
                url = validate(url) or url
            req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
            response = urllib.request.build_opener(_Redirect(self, row, validate)).open(req, timeout=timeout)
            return _Response(response, row, call)
        except BaseException:
            call.__exit__(None, None, None)
            raise

    def capture_requests(self, output):
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        for line in (output or "").splitlines():
            if line.startswith("{\"network\":"):
                row = json.loads(line)["network"]
                self.record(row["host"], "site resource", at=row["at"])

    def run_video(self, url, purpose, argv, *, validate, **kwargs):
        with self.request(url, purpose):
            validate(url)
            try:
                result = subprocess.run(argv, **kwargs)
            except subprocess.TimeoutExpired as exc:
                self.video_requests(exc.stderr, url, purpose)
                raise
            self.video_requests(result.stderr, url, purpose)
            return result

    def video_requests(self, output, url, purpose):
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        hosts = [urlsplit("//" + h.strip()).hostname for h in re.findall(r"(?im)^Host: ([^\r\n]+)", output or "")]
        if hosts and hosts[0] == urlsplit(url).hostname:
            hosts = hosts[1:]                            # the first request was recorded before FFmpeg ran
        for host in hosts:
            if host:
                self.record(host, purpose)

    def fetch(self, url, target, digest, limit, *, purpose, progress=None):
        from myzing import model_fetch
        self.check(purpose)

        def https(url):
            if urlsplit(url).scheme != "https":
                raise ValueError("model downloads need HTTPS")

        with model_fetch.transport(lambda u: self.open(u, purpose, validate=https)):
            return model_fetch.fetch_verified(url, target, digest, limit, progress=progress)


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, network, row, validate):
        self.network, self.row, self.validate = network, row, validate

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.network.check(self.row["purpose"])
        redirect = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirect is not None:
            self.network._finish(self.row)
            self.row.update(host=urlsplit(newurl).hostname, size=0,
                            at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            self.row["offset"] = self.network.record(self.row["host"], self.row["purpose"], at=self.row["at"])
            if self.validate:
                try:
                    newurl = self.validate(newurl) or newurl
                except (ValueError, OSError, FactoryError):
                    fp.close()
                    raise
                redirect.full_url = newurl
        return redirect


class _Response:
    def __init__(self, response, row, call):
        self.response, self.row, self.call = response, row, call

    def __getattr__(self, name):
        return getattr(self.response, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def read(self, *args):
        data = self.response.read(*args)
        self.row["size"] += len(data)
        return data

    def close(self):
        if self.call is not None:
            try:
                self.response.close()
            finally:
                self.call.__exit__(None, None, None)
                self.call = None


def summary(project: Path) -> dict:
    net = Network(project)
    path = net.project / "network.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    hosts, purposes = Counter(r["host"] for r in rows), Counter(r["purpose"] for r in rows)
    if not rows:
        text = "offline: nothing fetched" if net.offline else "No network requests recorded"
    else:
        counts = Counter((r["host"], r["purpose"]) for r in rows)
        text = f"{len(rows)} network requests · " + "; ".join(f"{h} / {p} {n}" for (h, p), n in sorted(counts.items()))
    return {"requests": len(rows), "hosts": dict(sorted(hosts.items())), "purposes": dict(sorted(purposes.items())),
            "summary": text}
