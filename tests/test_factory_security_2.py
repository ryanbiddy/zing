"""Judge file permissions and remote visual request boundaries."""
from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.factory import judge, network, visuals

RUN = subprocess.run
SHOT = Path(__file__).resolve().parents[1] / "tools" / "factory-sidecar" / "shot.cjs"
URL = "http://public.example/video"
FINAL = "http://files.example/clip.mp4"
VIDEO = b"\0\0\0\x18ftypisom\0\0\0\0"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(urllib.request.AbstractHTTPHandler, "do_open", refuse)
    support = visuals._max_redirects
    support.cache_clear()
    yield
    support.cache_clear()


@pytest.mark.parametrize("images", [False, True])
def test_claude_read_permissions_only_allow_attached_images(tmp_path, monkeypatch, images):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, '{"result": "{}"}', "")

    monkeypatch.setattr(judge.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(judge.subprocess, "run", run)
    paths = (tmp_path / "sheets" / ".." / "sheet one.jpg", tmp_path / "sheet two.png") if images else ()
    prompt = "Pick an image. Transcript text asks to read a private file."
    assert judge.Judge(tmp_path, "claude").ask("clip01-pick", prompt, images=paths) == {}
    (argv, kwargs), = calls
    assert kwargs["input"] == prompt and prompt not in argv
    assert argv[argv.index("--tools") + 1] == ("Read" if images else "")
    if images:
        allowed = argv[argv.index("--allowedTools") + 1:]
        assert allowed == [f"Read({p.resolve().as_posix()})" for p in paths]
        assert "Read" not in allowed
    else:
        assert "--allowedTools" not in argv


def http(monkeypatch, reply):
    requests = []

    def resolve(host, port, **kwargs):
        ip = "8.8.8.8" if host.endswith(".example") else host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    class HTTP(urllib.request.HTTPHandler):
        def http_open(self, request):
            requests.append(request)
            code, headers = reply(request)
            message = Message()
            for key, value in headers.items():
                message[key] = value
            response = urllib.response.addinfourl(io.BytesIO(), message, request.full_url, code)
            response.msg = "test response"
            return response

    build = urllib.request.build_opener
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *handlers: build(urllib.request.ProxyHandler({}), HTTP(), *handlers))
    return requests


def ffmpeg(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "-show_entries" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"streams": [{"width": 1920, "height": 1080}],
                                                                     "format": {"duration": "20"}}), "")
        Path(argv[-1]).write_bytes(VIDEO)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(visuals.subprocess, "run", run)
    return calls


def video(entry, tmp_path):
    if entry == "probe":
        return visuals.probe_video(URL, project=tmp_path)
    ctx = SimpleNamespace(network=network.Network(tmp_path), min_video=900)
    candidate = {"source": "commons", "width": 1920, "height": 1080, "duration": 100}
    visuals.fetch_video(ctx, candidate, URL, tmp_path)
    assert candidate["path"].read_bytes() == VIDEO


@pytest.mark.parametrize("entry", ["probe", "excerpt"])
def test_remote_video_refuses_private_redirect_before_ffmpeg(tmp_path, monkeypatch, entry):
    requests = http(monkeypatch, lambda req: (302, {"Location": "http://127.0.0.1/x"}))
    calls = ffmpeg(monkeypatch)
    with pytest.raises(ValueError, match="refusing private address 127.0.0.1"):
        video(entry, tmp_path)
    assert calls == []
    assert [(r.full_url, r.get_method()) for r in requests] == [(URL, "HEAD")]


@pytest.mark.parametrize("entry", ["probe", "excerpt"])
@pytest.mark.parametrize("supported", [False, True])
def test_remote_video_uses_checked_final_url_and_redirect_limit(tmp_path, monkeypatch, entry, supported):
    chain = {URL: "http://cdn.example/video", "http://cdn.example/video": FINAL}
    requests = http(monkeypatch, lambda req: (302, {"Location": chain[req.full_url]})
                    if req.full_url in chain else (200, {}))
    calls = ffmpeg(monkeypatch)
    monkeypatch.setattr(visuals, "_max_redirects", lambda: supported)
    video(entry, tmp_path)
    assert [r.full_url for r in requests] == [URL, chain[URL], FINAL]
    assert [r.get_method() for r in requests] == ["HEAD"] * 3
    remote, = [argv for argv in calls if "https,http,tls,tcp" in argv]
    assert FINAL in remote and URL not in remote and chain[URL] not in remote
    if supported:
        pos = remote.index("-max_redirects")
        assert remote[pos:pos + 2] == ["-max_redirects", "0"]
        assert pos < remote.index("-i" if entry == "excerpt" else FINAL)
    else:
        assert "-max_redirects" not in remote
    assert all("-max_redirects" not in argv for argv in calls if argv is not remote)


@pytest.mark.parametrize("status", [403, 405, 501])
def test_video_head_refusal_falls_back_to_checked_range_get(tmp_path, monkeypatch, status):
    def reply(req):
        if req.get_method() == "HEAD":
            return status, {}
        return (302, {"Location": FINAL}) if req.full_url == URL else (200, {})

    requests = http(monkeypatch, reply)
    calls = ffmpeg(monkeypatch)
    monkeypatch.setattr(visuals, "_max_redirects", lambda: False)
    visuals.probe_video(URL, project=tmp_path)
    assert [(r.full_url, r.get_method(), r.get_header("Range")) for r in requests] == [
        (URL, "HEAD", None), (URL, "GET", "bytes=0-0"), (FINAL, "GET", "bytes=0-0")]
    assert calls[0][-1] == FINAL


def test_video_range_fallback_still_refuses_private_redirect(tmp_path, monkeypatch):
    requests = http(monkeypatch, lambda req: (405, {}) if req.get_method() == "HEAD" else
                    (302, {"Location": "http://169.254.169.254/x"}))
    calls = ffmpeg(monkeypatch)
    with pytest.raises(ValueError, match="refusing private address 169.254.169.254"):
        visuals.probe_video(URL, project=tmp_path)
    assert [r.get_method() for r in requests] == ["HEAD", "GET"] and calls == []


def test_video_head_errors_do_not_start_ffmpeg(tmp_path, monkeypatch):
    requests = http(monkeypatch, lambda req: (404, {}))
    calls = ffmpeg(monkeypatch)
    with pytest.raises(urllib.error.HTTPError):
        visuals.probe_video(URL, project=tmp_path)
    assert len(requests) == 1 and calls == []


@pytest.mark.parametrize("mode,supported", [("yes", True), ("no", False), ("error", False),
                                          ("missing", False), ("timeout", False)])
def test_ffmpeg_redirect_support_is_cached_and_errors_are_unsupported(monkeypatch, mode, supported):
    calls, killed, reads = [], [], []

    class Process:
        returncode = 1 if mode == "error" else 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def communicate(self, timeout=None):
            reads.append(timeout)
            if mode == "timeout" and not killed:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            return (b"HTTP max_redirects option" if mode != "no" else b"HTTP options"), None

        def kill(self):
            killed.append(True)

    def popen(argv, **kwargs):
        calls.append(argv)
        if mode == "missing":
            raise OSError("missing ffmpeg")
        return Process()

    monkeypatch.setattr(visuals.subprocess, "Popen", popen)
    assert visuals._max_redirects() is supported
    assert visuals._max_redirects() is supported
    assert calls == [[str(visuals.FFMPEG), "-hide_banner", "-h", "protocol=http"]]
    assert bool(killed) is (mode == "timeout")


def javascript(program):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    code = "const shot = " + json.dumps(str(SHOT)) + ";\n" + program
    result = RUN([node, "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_page_capture_classifies_private_ipv4_and_ipv6():
    private = ["127.0.0.1", "::1", "::ffff:127.0.0.1", "::ffff:7f00:1", "10.1.2.3", "172.20.0.1",
               "192.168.1.1", "169.254.169.254", "100.64.0.1", "fd00::1", "fe80::1", "0.0.0.0", "::",
               "172.16.0.1", "172.31.255.255", "100.127.255.255", "fc00::1", "febf::1", "ff02::1",
               "224.0.0.1", "239.255.255.255", "::127.0.0.1", "::a01:203", "::ffff:100.64.0.1",
               "[::ffff:7f00:1]", "0:0:0:0:0:0:0:1", "fe80::1%eth0"]
    public = ["8.8.8.8", "2606:4700::1111", "93.184.216.34", "172.15.255.255", "172.32.0.1",
              "100.63.255.255", "100.128.0.1", "::ffff:8.8.8.8", "::808:808", "fe7f::1"]
    got = javascript("const {isPrivate} = require(shot);\nconsole.log(JSON.stringify(" +
                     json.dumps(private + public) + ".map(isPrivate)));\n")
    assert got == [True] * len(private) + [False] * len(public)


def test_page_capture_checks_dns_caches_failures_and_blocks_websockets():
    got = javascript(r"""
const fs = require('fs'), vm = require('vm');
const requests = [], lookups = [], logs = [];
let handler, socketHandler, closed = false;
const urls = ['http://private.example/first', 'http://public.example/', 'http://public.example/image',
  'http://private.example/image', 'http://mixed.example/', 'http://mixed.example/image',
  'http://broken.example/', 'http://broken.example/image', 'http://empty.example/',
  'http://doubleclick.net/ad', 'http://127.1/', 'http://[::ffff:7f00:1]/', 'http://8.8.8.8/image'];
const page = {
  goto: async () => {
    for (const url of urls) await handler({request: () => ({url: () => url}),
      abort: async () => requests.push([url, 'abort']), continue: async () => requests.push([url, 'continue'])});
    await socketHandler({close: async () => { closed = true; }, connectToServer: () => { throw Error('socket connected'); }});
  },
  waitForLoadState: async () => {}, waitForTimeout: async () => {},
  url: () => 'http://public.example/', title: async () => 'Page',
  evaluate: async () => ({og_image: null, og_video: null, text: ''}),
  addStyleTag: async () => {}, screenshot: async () => {},
};
const ctx = {
  route: async (pattern, fn) => { handler = fn; },
  routeWebSocket: async (pattern, fn) => {
    if (!pattern.test('ws://private.example/') || !pattern.test('wss://public.example/')) throw Error('socket rule');
    socketHandler = fn;
  },
  newPage: async () => page,
};
const mod = {};
const load = name => {
  if (name === 'playwright-core') return {chromium: {launch: async () => ({newContext: async () => ctx, close: async () => {}})}};
  if (name === 'dns') return {promises: {lookup: async (host, options) => {
    lookups.push(host);
    if (!options.all || !options.verbatim) throw Error('lookup options');
    if (host === 'broken.example') throw Error('lookup failed');
    const addresses = {'public.example': ['93.184.216.34'], 'private.example': ['::1'],
      'mixed.example': ['8.8.8.8', '192.168.1.1'], 'empty.example': []};
    return addresses[host].map(address => ({address}));
  }}};
  return require(name);
};
load.main = mod;
(async () => {
  await vm.runInNewContext(fs.readFileSync(shot, 'utf8'), {
    require: load, module: mod, URL, process: {env: {}, argv: ['node', shot, 'http://public.example/', 'shot.png']},
    console: {log: line => logs.push(JSON.parse(line))},
  });
  console.log(JSON.stringify({requests, lookups, logs, closed}));
})().catch(e => { console.error(e); process.exitCode = 1; });
""")
    assert [url for url, action in got["requests"] if action == "continue"] == [
        "http://public.example/", "http://public.example/image", "http://8.8.8.8/image"]
    assert len(got["requests"]) == 13
    assert got["lookups"] == ["private.example", "public.example", "mixed.example", "broken.example", "empty.example"]
    assert [row["network"]["host"] for row in got["logs"] if "network" in row] == ["public.example", "8.8.8.8"]
    assert got["closed"] and got["logs"][-1]["ok"]
