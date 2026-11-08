"""Scene timeouts, failed pages, unreadable caches and atomic color output."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import doctor
from myzing.factory import judge, network, render, tools, visuals
from myzing.layout import vision_models

RUN = subprocess.run
SHOT = Path(__file__).resolve().parents[1] / "tools" / "factory-sidecar" / "shot.cjs"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)


@pytest.fixture
def sidecar(tmp_path, monkeypatch):
    def env(tmp):
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "profile").write_bytes(b"temporary")
        return {}
    monkeypatch.setattr(render, "node_sidecar", lambda: ("node", tmp_path))
    monkeypatch.setattr(render, "sidecar_env", env)


@pytest.mark.parametrize("duration,fps,samples,timeout", [
    (2, 30, None, 480), (10, 60, None, 2100), (1.26, 24, None, 390),
    (60, 30, [0, 120, 600], 309), (60, 30, [], 300), (2, None, None, 480),
])
def test_capture_timeout_counts_only_requested_frames(tmp_path, monkeypatch, sidecar, duration, fps, samples, timeout):
    calls = []
    monkeypatch.setattr(render, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    data = {"duration": duration, "captureFrames": [0], **({"fps": fps} if fps is not None else {})}
    render.capture(data, tmp_path / "data.json", tmp_path / "frames", samples=samples)
    (args, kwargs), = calls
    assert kwargs["timeout"] == timeout
    assert args[1] == tools.data_path("render.cjs")
    assert not (tmp_path / "_tmp").exists()


def test_capture_timeout_becomes_factory_error_and_cleans_up(tmp_path, monkeypatch, sidecar):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    monkeypatch.setattr(render, "run", run)
    with pytest.raises(tools.FactoryError, match="scene render timed out") as caught:
        render.capture({"duration": 1, "fps": 30}, tmp_path / "data.json", tmp_path / "frames")
    assert isinstance(caught.value.__cause__, subprocess.TimeoutExpired)
    assert not (tmp_path / "_tmp").exists()


@pytest.mark.parametrize("reply", [
    {"ok": False, "http_status": 404}, {"ok": False, "http_status": 500},
    {"ok": True, "http_status": 404, "frames": 180, "og_image": "error.png"},
    {"ok": True, "blocked": True},
])
def test_site_rejects_failed_pages_and_removes_old_screenshot(tmp_path, monkeypatch, reply):
    url = "https://public.example/page"
    shot = tmp_path / f"screenshot_{visuals.h8(url)}.png"
    shot.write_bytes(b"old screenshot")
    ctx = SimpleNamespace(tmp=tmp_path / "_tmp", log={}, health=visuals.Health(), http=None,
                          network=network.Network(tmp_path))
    monkeypatch.setattr(tools, "node_sidecar", lambda: ("node", tmp_path))
    monkeypatch.setattr(tools, "sidecar_env", lambda tmp: {})
    monkeypatch.setattr(visuals, "_check_host", lambda url: None)
    calls, fallback = [], []

    def run(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(reply), "")
    monkeypatch.setattr(visuals, "run", run)
    monkeypatch.setattr(visuals, "_og_from_html", lambda *args: fallback.append(args))
    assert visuals.capture_site(ctx, url, tmp_path, 1, "request") == []
    assert len(calls) == 1 and fallback == []
    assert not shot.exists() and not list(ctx.tmp.glob("frames_*"))
    assert ctx.health.d["screenshot"]["ok"] == 0
    assert ctx.health.d["screenshot"]["errors"]
    if "http_status" in reply:
        assert ctx.log["site"]["http_status"] == reply["http_status"]
        assert str(reply["http_status"]) in ctx.health.d["screenshot"]["errors"][0]


@pytest.mark.parametrize("status", [None, 200, 399, 400, 404, 500])
def test_shot_checks_navigation_before_screenshot(tmp_path, status):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    shot = tmp_path / "shot.png"
    code = "const [shot, out, status] = " + json.dumps([str(SHOT), str(shot), status]) + ";\n" + r"""
const fs = require('fs'), vm = require('vm'), http = require('http');
const logs = [];
let closed = false, screenshots = 0;
const server = http.createServer((req, res) => { res.writeHead(status || 200); res.end('Page'); });
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const url = `http://127.0.0.1:${server.address().port}/page`;
    const page = {
      goto: async () => status === null ? null : new Promise((resolve, reject) => {
        http.get(url, res => { res.resume(); resolve({status: () => res.statusCode}); }).on('error', reject);
      }),
      url: () => url, title: async () => 'Page',
      waitForLoadState: async () => {}, waitForTimeout: async () => {},
      evaluate: async () => ({og_image: null, og_video: null, text: 'Page'}),
      addStyleTag: async () => {},
      screenshot: async ({path}) => { screenshots++; fs.writeFileSync(path, 'screenshot'); },
    };
    const ctx = {route: async () => {}, routeWebSocket: async () => {}, newPage: async () => page};
    const mod = {};
    const load = name => name === 'playwright-core' ? {chromium: {launch: async () => ({
      newContext: async () => ctx, close: async () => { closed = true; },
    })}} : require(name);
    load.main = mod;
    await vm.runInNewContext(fs.readFileSync(shot, 'utf8'), {
      require: load, module: mod, URL, process: {env: {}, argv: ['node', shot, url, out]},
      console: {log: line => logs.push(JSON.parse(line))},
    });
    console.log(JSON.stringify({result: logs.at(-1), closed, screenshots}));
  } finally { await new Promise(resolve => server.close(resolve)); }
})().catch(e => { console.error(e); process.exitCode = 1; });
"""
    proc = RUN([node, "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    ok = status is not None and status < 400
    assert got["result"]["ok"] is ok
    assert got["result"]["http_status"] == status
    assert got["closed"] and got["screenshots"] == int(ok)
    assert shot.exists() is ok
    assert got["result"]["frames"] == 0
    if not ok:
        assert got["result"]["error"]


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("unreadable")])
def test_layout_reports_unreadable_vision_cache(monkeypatch, error, capsys):
    def inventory():
        raise error
    monkeypatch.setattr(vision_models, "inventory", inventory)
    check = doctor.check_layout()
    assert check.name == "layout" and check.tier == doctor.OPTIONAL and not check.ok
    assert "vision model cache could not be read" in check.detail
    assert check.data["network_used"] is False
    monkeypatch.setattr(doctor, "run_checks", lambda: [doctor.check_layout()])
    assert doctor.run(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["checks"][0]["ok"] is False


@pytest.fixture
def cube():
    pytest.importorskip("numpy", reason="install myzing[color] for color tests")
    from myzing.color import cube
    return cube


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["write", "replace"])
def test_cube_failure_leaves_target_untouched(tmp_path, monkeypatch, cube, existing, failure):
    target = tmp_path / "look.cube"
    if existing:
        target.write_bytes(b"previous cube")
    fdopen = cube.os.fdopen

    @contextmanager
    def opened(*args, **kwargs):
        with fdopen(*args, **kwargs) as file:
            def write(text):
                file.write(text[:20])
                raise OSError("disk full")
            yield SimpleNamespace(write=write)

    def replace(src, dst):
        assert Path(src).parent == target.parent and Path(dst) == target
        raise OSError("cannot replace")
    if failure == "write":
        monkeypatch.setattr(cube.os, "fdopen", opened)
    else:
        monkeypatch.setattr(cube.os, "replace", replace)
    with pytest.raises(OSError, match="disk full|cannot replace"):
        cube.write_cube(cube.Cube(2, [[0, 0, 0]] * 8), target)
    assert sorted(tmp_path.iterdir()) == ([target] if existing else [])
    if existing:
        assert target.read_bytes() == b"previous cube"


@pytest.mark.parametrize("failure", [None, "copy", "replace"])
def test_graded_video_is_published_only_after_copy(tmp_path, monkeypatch, cube, failure):
    from myzing.color import media
    lut = cube.write_cube(cube.Cube(2, [[0, 0, 0]] * 8), tmp_path / "look.cube")
    source, output = tmp_path / "source.mp4", tmp_path / "graded.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(media, "probe", lambda path: (1, 16, 16, {
        "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709"}))

    def run(argv, **kwargs):
        assert not output.exists()
        if argv[-1] != "-":
            Path(argv[-1]).write_bytes(b"graded video")
        return b""
    monkeypatch.setattr(media, "run_media", run)
    copy, replace = media.shutil.copyfileobj, media.os.replace

    def copied(src, dest):
        assert not output.exists()
        if failure == "copy":
            dest.write(b"partial")
            raise OSError("disk full")
        copy(src, dest)

    def replaced(src, dst):
        if Path(dst) == output:
            assert Path(src).parent == output.parent and not output.exists()
            assert Path(src).read_bytes() == b"graded video"
            if failure == "replace":
                raise OSError("cannot replace")
        replace(src, dst)
    monkeypatch.setattr(media.shutil, "copyfileobj", copied)
    monkeypatch.setattr(media.os, "replace", replaced)
    if failure == "replace":  # a volume without hard links falls back to replace
        def no_link(src, dst):
            raise OSError("hard links unsupported")
        monkeypatch.setattr(media.os, "link", no_link)
    if failure:
        with pytest.raises(OSError, match="disk full|cannot replace"):
            media.apply_video(lut, source, output)
    else:
        got = media.apply_video(lut, source, output)
        assert output.read_bytes() == b"graded video"
        assert got["sha256"] == media.sha256(output)
    assert set(tmp_path.iterdir()) == {lut, source} | ({output} if not failure else set())
    assert source.read_bytes() == b"source"


def test_graded_video_never_replaces_a_file_created_during_the_render(tmp_path, monkeypatch, cube):
    from myzing.color import ColorError, media
    lut = cube.write_cube(cube.Cube(2, [[0, 0, 0]] * 8), tmp_path / "look.cube")
    source, output = tmp_path / "source.mp4", tmp_path / "graded.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(media, "probe", lambda path: (1, 16, 16, {
        "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709"}))

    def run(argv, **kwargs):
        if argv[-1] != "-":
            Path(argv[-1]).write_bytes(b"graded video")
        else:
            output.write_bytes(b"another run")  # appears after the up-front existence check
        return b""
    monkeypatch.setattr(media, "run_media", run)
    with pytest.raises(ColorError, match="already exists"):
        media.apply_video(lut, source, output)
    assert output.read_bytes() == b"another run"
    assert set(tmp_path.iterdir()) == {lut, source, output}
