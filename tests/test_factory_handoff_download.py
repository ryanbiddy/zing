"""Source downloads use fake processes and never call a model or the network."""
from __future__ import annotations

import io
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import cli, doctor, handoff, storage, uoink_bridge, urls
from myzing.factory import judge, serve
from myzing.study import downloader, ingest

URL = "https://example.test/watch/123"
REF = "uoink://item/short-123"


def refuse(*args, **kwargs):
    raise AssertionError("unmocked external operation")


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(ingest.subprocess, "Popen", refuse)
    monkeypatch.setattr(ingest, "require_public_host", lambda url: None)
    monkeypatch.setattr(urls, "open_no_redirect", refuse)
    monkeypatch.setattr(doctor, "resolve_ytdlp_argv", lambda: ["yt-dlp"])
    monkeypatch.setattr(downloader, "runtime_options", lambda: {})
    monkeypatch.setattr(handoff.webbrowser, "open", refuse)


def argv(dest):
    return ["yt-dlp", "--no-playlist", "-f", "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "--merge-output-format", "mp4", "--write-info-json", "-o", "media.%(ext)s", "-P", str(dest), URL]


@pytest.mark.parametrize("mode", ["binary", "runtime", "module"])
def test_fetch_keeps_exact_download_command_and_reuses_media(monkeypatch, mode):
    slug = "source"
    dest = storage.breakdown_dir(slug)
    expected = argv(dest)
    if mode == "runtime":
        monkeypatch.setattr(downloader, "runtime_options", lambda: {"js_runtimes": {"node": {}}})
        expected[1:1] = ["--js-runtimes", "node"]
    elif mode == "module":
        monkeypatch.setattr(doctor, "resolve_ytdlp_argv", lambda: ["python", "-m", "yt_dlp"])
        expected[:1] = ["python", "-m", "myzing.study.downloader"]
    calls = []

    def run(cmd, timeout):
        calls.append((cmd, timeout))
        (dest / "media.mp4").write_bytes(b"episode")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ingest.proc, "run", run)
    warnings = []
    assert ingest._fetch(URL, slug, dest, warnings) == dest / "media.mp4"
    assert calls == [(expected, 600)] and not warnings
    assert ingest._fetch(URL, slug, dest, warnings) == dest / "media.mp4"
    assert len(calls) == 1 and warnings == ["reusing already-downloaded media: media.mp4"]


class Process:
    def __init__(self, lines, code=0):
        self.stdout = io.StringIO(lines)
        self.returncode = None
        self.code = code
        self.killed = False

    def wait(self):
        self.returncode = self.code
        return self.code

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.code = -9


@pytest.fixture
def popen(monkeypatch):
    fake = SimpleNamespace(calls=[], lines="download:  42.0%\ndownload: 42.9 %\ndownload: 100%\n", code=0)

    def start(cmd, **kwargs):
        fake.calls.append((cmd, kwargs))
        dest = Path(cmd[cmd.index("-P") + 1])
        (dest / "media.mp4").write_bytes(b"episode")
        fake.process = Process(fake.lines, fake.code)
        return fake.process

    monkeypatch.setattr(ingest.subprocess, "Popen", start)
    return fake


def test_download_streams_parsed_progress_with_only_requested_flags(tmp_path, popen):
    popen.lines = "setup\ndownload: N/A\ndownload:  0.0%\ndownload: 42.5 %\ndownload: nope\n"
    popen.lines += "download: nan\ndownload: inf\ndownload: -1%\ndownload: 101%\ndownload: 100%\nmerged\n"
    dest = tmp_path / "source"
    seen = []
    assert ingest.download(URL, dest, progress=seen.append) == dest / "media.mp4"
    assert seen == [0.0, 42.5, 100.0]
    expected = argv(dest)
    expected[-1:-1] = ["--newline", "--progress-template", "download:%(progress._percent_str)s"]
    assert popen.calls == [(expected, dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", errors="replace", bufsize=1))]
    assert popen.process.stdout.closed and not popen.process.killed


def test_download_stream_failure_is_an_error(tmp_path, popen):
    popen.lines, popen.code = "private details\nlast error\n", 1
    with pytest.raises(ingest.MediaError, match="exit 1") as caught:
        ingest.download(URL, tmp_path / "source", progress=lambda percent: None)
    assert str(caught.value).endswith("last error") and "private details" not in str(caught.value)
    assert popen.process.stdout.closed


def test_download_timeout_kills_silent_process(tmp_path, monkeypatch):
    ended = threading.Event()

    class Silent(Process):
        def __init__(self):
            super().__init__("")
            self.stdout = self
            self.closed = False

        def __iter__(self):
            assert ended.wait(2)
            return iter(())

        def kill(self):
            super().kill()
            ended.set()

        def close(self):
            self.closed = True

    process = Silent()
    monkeypatch.setattr(ingest.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ingest.proc.Timeout) as caught:
        ingest.download(URL, tmp_path / "source", timeout=.02, progress=lambda percent: None)
    assert caught.value.timeout == .02 and process.killed and process.closed


@pytest.mark.parametrize("json_output", [False, True])
def test_handoff_progress_is_flushed_only_to_stderr(monkeypatch, tmp_path, popen, json_output):
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media",
                        lambda ref: {"ok": True, "data": {"state": "not_kept", "source_url": URL, "media": None}})
    monkeypatch.setattr(uoink_bridge, "item_metadata", lambda ref: {"ok": True, "title": "Episode", "source_url": URL})
    popen.lines = "private downloader output\ndownload: 42.0%\ndownload: 42.9%\ndownload: 43.1%\n"
    popen.lines += "download: 42%\ndownload: 100%\nmerging\n"

    class Output(io.StringIO):
        def __init__(self):
            super().__init__()
            self.flushes = []

        def flush(self):
            self.flushes.append(self.getvalue())

    out, err = Output(), Output()
    monkeypatch.setattr(handoff.sys, "stdout", out)
    monkeypatch.setattr(handoff.sys, "stderr", err)

    def ready(project, **kwargs):
        assert not out.getvalue()
        assert len(err.flushes) == 3
        kwargs["say"]("Open the page")
        kwargs["ready"]("http://127.0.0.1:1234/")

    monkeypatch.setattr(serve, "serve", ready)
    args = ["--json"] if json_output else []
    assert cli.main(["from-uoink", REF, "--allow-download", "--project", str(tmp_path / "project"), "--no-open", *args]) == 0
    if json_output:
        assert len(out.getvalue().splitlines()) == 1 and json.loads(out.getvalue())["downloaded"] is True
        expected = [json.dumps({"contract": handoff.CONTRACT, "version": 1, "progress": "download", "percent": percent})
                    for percent in (42.0, 43.1, 100.0)]
    else:
        assert out.getvalue() == "Open the page\n"
        expected = ["Downloading 42%", "Downloading 43%", "Downloading 100%"]
    assert err.getvalue().splitlines() == expected
    assert err.flushes == ["\n".join(expected[:i]) + "\n" for i in range(1, 4)]


def test_download_still_checks_public_host(tmp_path, monkeypatch):
    def private(url):
        raise ValueError("refusing private address")

    monkeypatch.setattr(ingest, "require_public_host", private)
    with pytest.raises(ingest.MediaError, match="refusing private address"):
        ingest.download(URL, tmp_path / "source", progress=lambda percent: None)
    assert not (tmp_path / "source").exists()
