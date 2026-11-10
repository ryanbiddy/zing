"""4K factory output keeps the scene layout and the source pixels."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import mcp_server
from myzing.factory import command, cutout, depth, judge, pipeline, render, source
from myzing.factory.tools import FactoryError


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "ep.mp4"
    path.write_bytes(b"mp4")
    return path


def clip(root, name="clip01"):
    d = root / name
    raw = {"hook": "A talk", "shots": [{"from": 0, "layout": "solo"}], "visuals": {}}
    judge.Judge(root).save(f"{name}-plan", raw)
    pipeline._write(d / "plan.json", raw)
    pipeline._write(d / "words.json", {"words": [{"w": "Hello.", "os": 0, "oe": 1.55}], "duration": 2})
    pipeline._write(d / "cams.json", {"frames": 60, "size": [3840, 2160], "cams": []})
    pipeline._write(d / "post.json", {})
    return d


def probe(monkeypatch, size):
    calls = []

    def run(*argv, **kwargs):
        assert argv[0] == "ffprobe"
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps({"streams": [{"width": size[0], "height": size[1]}]}))

    monkeypatch.setattr(render, "ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(render, "run", run)
    return calls


def test_cli_and_mcp_save_uhd(tmp_path, media, capsys):
    root = tmp_path / "cli"
    assert command.run(["new", str(root), "--media", str(media), "--4k"]) == 0
    assert json.loads(capsys.readouterr().out)["settings"]["uhd"] is True
    assert pipeline._read(root / "factory.json")["uhd"] is True
    result = mcp_server.h_factory_new(str(tmp_path / "mcp"), str(media), uhd=True)
    assert result["ok"] and pipeline._read(tmp_path / "mcp" / "factory.json")["uhd"] is True
    assert pipeline.init(tmp_path / "plain", media)["settings"]["uhd"] is False


@pytest.mark.parametrize("bad", ["true", "false", 1, 0, None, []])
def test_uhd_must_be_a_json_boolean(tmp_path, media, bad):
    root = tmp_path / "proj"
    with pytest.raises(FactoryError, match="uhd must be true or false"):
        pipeline.init(root, media, uhd=bad)
    assert not root.exists()
    result = mcp_server.h_factory_new(str(root), str(media), uhd=bad)
    assert not result["ok"] and "uhd" in result["error"]
    d = clip(root)
    pipeline._write(root / "factory.json", {"uhd": bad})
    with pytest.raises(FactoryError, match="uhd must be true or false"):
        render.scene_data(d, "9x16", "zing", parallax=False, front=False, sharpen=False)
    with pytest.raises(FactoryError, match="uhd must be true or false"):
        render.warn_uhd(root)


def test_mcp_uhd_is_optional_and_tool_count_stays_44():
    pytest.importorskip("mcp")
    tools = asyncio.run(mcp_server.build_server().list_tools())
    assert len(tools) == 44
    schema = next(t.model_dump(by_alias=True)["inputSchema"] for t in tools if t.name == "factory_new")
    assert schema["properties"]["uhd"]["type"] == "boolean"
    assert schema["properties"]["uhd"]["default"] is False and "uhd" not in schema["required"]


@pytest.mark.parametrize("uhd", [None, False, True])
@pytest.mark.parametrize("shape,size", [("9x16", (2160, 3840)), ("16x9", (3840, 2160)),
                                        ("1x1", (2160, 2160)), ("4x5", (2160, 2700))])
def test_sidecar_gets_scale_without_changing_layout_or_names(tmp_path, monkeypatch, uhd, shape, size):
    d = clip(tmp_path)
    pipeline._write(tmp_path / "factory.json", {} if uhd is None else {"uhd": uhd})
    calls, data = [], []

    def run(*argv, **kwargs):
        calls.append(argv)
        if argv[0] == "node":
            data.append(pipeline._read(argv[3]))
        else:
            Path(argv[-1]).write_bytes(b"mp4")

    def sheet(argv, **kwargs):
        assert "-frames:v" in argv

    monkeypatch.setattr(render, "run", run)
    monkeypatch.setattr(render.subprocess, "run", sheet)
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render, "node_sidecar", lambda: ("node", tmp_path / "sidecar"))
    monkeypatch.setattr(render, "sidecar_env", lambda tmp: {})
    out = render.render(d, shape, parallax=False, front=False, sharpen=False)
    assert out == d / f"clip{render.suffix(shape, 'zing')}.mp4" and out.is_file()
    got = data[0]
    assert (got["W"], got["H"]) == render.SHAPES[shape]
    assert got["srcSize"] == [3840, 2160]
    assert ("scale" in got) == bool(uhd)
    assert (got["W"] * got.get("scale", 1), got["H"] * got.get("scale", 1)) == (size if uhd else render.SHAPES[shape])
    enc = calls[-1]
    assert enc[enc.index("-c:v") + 1] == "libx264" and enc[enc.index("-pix_fmt") + 1] == "yuv420p"
    assert enc[enc.index("-crf") + 1] == 20
    if uhd:
        assert enc[enc.index("-level:v") + 1] == "5.1" and enc[enc.index("-profile:v") + 1] == "high"
        assert enc[enc.index("-maxrate") + 1] == "40M" and enc[enc.index("-bufsize") + 1] == "80M"
        assert enc[enc.index("-vf") + 1] == "scale=in_range=pc:out_range=tv" and enc[enc.index("-color_range") + 1] == "tv"
    else:
        assert "-level:v" not in enc


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (2560, 1440), (3840, 2160), (2160, 3840)])
def test_small_source_warns_once_per_run_and_keeps_rendering(tmp_path, media, monkeypatch, size):
    root = tmp_path / "proj"
    pipeline.init(root, media, uhd=True, shapes=list(render.SHAPES))
    for name in ("clip01", "clip02"):
        clip(root, name)
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 0, "end": 2, "hook": "A talk", "snapped": True} for _ in range(2)]})
    calls = probe(monkeypatch, size)
    rendered, log = [], []
    monkeypatch.setattr(render, "render", lambda d, shape, pack: rendered.append((d.name, shape)))
    result = pipeline.run(root, judge.Judge(root), say=log.append)
    assert result["state"] == "done" and not result["failed"] and len(rendered) == 8
    assert len(calls) == 1
    warnings = [m for m in log if "upscaled" in m]
    assert warnings == ([f"source is {min(size)}p; 4K output will be upscaled"] if min(size) < 2160 else [])


def test_render_flag_persists_and_next_run_replaces_other_resolutions(tmp_path, media, monkeypatch, capsys):
    root = tmp_path / "proj"
    pipeline.init(root, media, shapes=["9x16", "1x1"])
    d = clip(root)
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 0, "end": 2, "hook": "A talk", "snapped": True}]})
    rendered = []

    def make(d, shape, pack, **kwargs):
        tag = render.suffix(shape, pack)
        data = render.scene_data(d, shape, pack, parallax=False, front=False, sharpen=False)
        rendered.append((shape, data.get("scale", 1)))
        pipeline._write(d / f"data{tag}.json", data)
        out = d / f"clip{tag}.mp4"
        out.write_bytes(b"mp4")
        return out

    monkeypatch.setattr(render, "render", make)
    for _ in range(2):
        pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert rendered == [("9x16", 1), ("1x1", 1)]       # the default never probes the source
    calls = probe(monkeypatch, (1920, 1080))
    assert command.run(["render", str(d), "--4k"]) == 0
    assert pipeline._read(root / "factory.json")["uhd"] is True
    assert capsys.readouterr().err == "source is 1080p; 4K output will be upscaled\n"
    for _ in range(2):
        pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert rendered == [("9x16", 1), ("1x1", 1), ("9x16", 2), ("1x1", 2)]
    assert command.run(["render", str(d)]) == 0
    assert rendered[-1] == ("9x16", 2) and len(calls) == 4


@pytest.mark.parametrize("uhd", [False, True])
def test_scene_keeps_native_video_depth_and_mattes_in_uhd(tmp_path, monkeypatch, uhd):
    Image = pytest.importorskip("PIL.Image")
    d = clip(tmp_path)
    photo, video = d / "photo.jpg", d / "video.mp4"
    Image.new("RGB", (3840, 2160)).save(photo)
    video.write_bytes(b"mp4")
    pipeline._write(tmp_path / "factory.json", {"uhd": uhd})
    pipeline._write(d / "plan.json", {"hook": "A talk", "shots": [
        {"from": 0, "layout": "split", "visual": "v1"}, {"from": 1, "layout": "split", "visual": "v2"}],
        "visuals": {"v1": {"path": str(photo)}, "v2": {"path": str(video)}}})
    widths, filters = [], []

    def mattes(d, spans, **kwargs):
        widths.append(kwargs)
        return {"dir": d / "mattes"}

    def parallax(image, out, seconds, **kwargs):
        widths.append(kwargs)
        return out

    def extract(*argv, **kwargs):
        filters.append(argv[argv.index("-vf") + 1])
        Image.new("RGB", (3840, 2160)).save(Path(argv[-1]).parent / "00001.jpg")

    monkeypatch.setattr(cutout, "mattes", mattes)
    monkeypatch.setattr(depth, "parallax", parallax)
    monkeypatch.setattr(render, "run", extract)
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    data = render.scene_data(d, "9x16", "zing", parallax=True, front=True, sharpen=False)
    assert widths == ([{"width": None}, {"key": "v1", "width": None}] if uhd else [{}, {"key": "v1"}])
    assert filters == ["fps=30", "fps=30" if uhd else "fps=30,scale=1280:-2"]
    assert data["mattesDir"] and all(s["layout"] == "front" for s in data["shots"])


def test_native_mattes_replace_the_smaller_cache(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    d = clip(tmp_path)
    (d / "frames").mkdir()
    cv2.imwrite(str(d / "frames" / "00001.jpg"), np.zeros((2160, 3840, 3), np.uint8))
    sizes = []

    def segment(rgb):
        sizes.append(rgb.shape[:2])
        a = np.zeros(rgb.shape[:2], np.float32)
        a[:, :rgb.shape[1] // 2] = 1
        return a

    monkeypatch.setattr(cutout, "segment", segment)
    for width in (960, 960, None, None, 960):
        assert cutout.mattes(d, [(0, 0)], width=width)
        png = cv2.imread(str(d / "mattes" / "00001.png"), cv2.IMREAD_UNCHANGED)
        assert png.shape[:2] == ((2160, 3840) if width is None else (540, 960))
    assert sizes == [(540, 960), (2160, 3840), (540, 960)]


def test_native_depth_frames_replace_the_smaller_cache(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    photo, out = tmp_path / "photo.jpg", tmp_path / "move.mp4"
    cv2.imwrite(str(photo), np.zeros((2160, 3840, 3), np.uint8))
    sizes, encoded = [], []

    def estimate(rgb):
        sizes.append(rgb.shape[:2])
        return np.zeros(rgb.shape[:2], np.float32)

    class Encoder:
        def __init__(self, argv, **kwargs):
            encoded.append(argv[argv.index("-s") + 1])
            self.stdin, self.returncode = io.BytesIO(), 0

        def wait(self):
            out.write_bytes(b"mp4")

    monkeypatch.setattr(depth, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(depth.subprocess, "Popen", Encoder)
    monkeypatch.setattr(depth, "estimate", estimate)
    monkeypatch.setattr(depth, "flat", lambda d: False)
    monkeypatch.setattr(depth, "frames", lambda bgr, *args: [bgr[:1, :1]])
    for width in (1600, 1600, None, None, 1600):
        assert depth.parallax(photo, out, 2, width=width) == out
    assert sizes == [(900, 1600), (2160, 3840), (900, 1600)]
    assert encoded == ["1600x900", "3840x2160", "1600x900"]
