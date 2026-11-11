from __future__ import annotations

import json
import re
import shutil
from types import SimpleNamespace

import pytest

from myzing.factory import cut
from myzing.layout import detector

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")


@pytest.fixture
def clip(tmp_path, monkeypatch, zing_workspace):
    def detect(img):
        x = 30 if img[50, 50, 0] > 96 else 220
        return None, np.array([[x, 30, 40, 40]], dtype=np.float32)

    monkeypatch.setattr(detector, "require_model", lambda: tmp_path / "model")
    monkeypatch.setattr(cv2, "FaceDetectorYN", SimpleNamespace(create=lambda *a: SimpleNamespace(
        setInputSize=lambda size: None, detect=detect)))
    (tmp_path / "frames").mkdir()

    def make(graph):
        cut.run(cut.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", graph,
                "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv420p", tmp_path / "cut.mp4")
        cut.run(cut.ffmpeg(), "-v", "error", "-y", "-i", tmp_path / "cut.mp4",
                "-q:v", "2", tmp_path / "frames" / "%05d.jpg")
        return tmp_path

    return make


def shots(d):
    info = cut.cams(d)
    assert json.loads((d / "cams.json").read_text(encoding="utf-8")) == info
    return [(c["from"], c["to"]) for c in info["cams"]]


def test_similar_colored_hard_cut_reframes_each_shot(clip):
    d = clip("color=0x404040:s=320x180:r=30:d=4,"
             "drawbox=x=20:y=20:w=90:h=140:c=0x808080:t=fill:enable='lt(t,2)',"
             "drawbox=x=210:y=20:w=90:h=140:c=0x808080:t=fill:enable='gte(t,2)'")
    log = cut.run(cut.ffmpeg(), "-hide_banner", "-i", d / "cut.mp4", "-vf",
                  "select='gt(scene,0.15)',metadata=print:key=lavfi.scene_score", "-f", "null", "-",
                  capture_output=True, text=True).stderr
    scores = [float(x) for x in re.findall(r"lavfi.scene_score=([0-9.]+)", log)]
    assert len(scores) == 1 and .2 <= scores[0] <= .26
    assert shots(d) == [(0, 2), (2, 4)]
    cams = json.loads((d / "cams.json").read_text(encoding="utf-8"))["cams"]
    assert [c["cx"] for c in cams] == [50 / 320, 240 / 320]


@pytest.mark.parametrize("graph", [
    "testsrc2=s=320x180:r=30:d=4",
    "testsrc2=s=640x360:r=30:d=4,"
    "zoompan=z='1+on*.002':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=320x180:fps=30",
    "nullsrc=s=320x180:r=30:d=4,geq=lum='80+60*mod(N,3)':cb=128:cr=128",
], ids=["motion", "push_in", "repeated_changes"])
def test_motion_does_not_split_the_shot(clip, graph):
    assert shots(clip(graph)) == [(0, 4)]


@pytest.mark.parametrize("y,height", [(100, 80), (0, 180)], ids=["gesture", "lens_occlusion"])
def test_brief_occlusion_does_not_split_the_shot(clip, y, height):
    d = clip("color=0x404040:s=320x180:r=30:d=4,"
             "drawbox=x=20:y=20:w=90:h=140:c=0x808080:t=fill,"
             f"drawbox=x=40:y={y}:w=240:h={height}:c=0xb08060:t=fill:enable='between(t,2,2.3)'")
    assert shots(d) == [(0, 4)]


def test_short_insert_holds_crop_until_the_next_lasting_shot(clip):
    d = clip("color=0x404040:s=320x180:r=30:d=4,"
             "drawbox=x=20:y=20:w=90:h=140:c=0x808080:t=fill:enable='lt(t,2)',"
             "drawbox=x=0:y=0:w=320:h=180:c=white:t=fill:enable='between(t,2,2.3)',"
             "drawbox=x=210:y=20:w=90:h=140:c=0x808080:t=fill:enable='gt(t,2.3)'")
    assert shots(d) == [(0, 2.333), (2.333, 4)]


def test_separate_hard_cuts_keep_a_short_but_stable_shot(clip):
    d = clip("color=0x404040:s=320x180:r=30:d=4,"
             "drawbox=x=20:y=20:w=90:h=140:c=0x808080:t=fill:enable='not(between(t,2,2.7))',"
             "drawbox=x=210:y=20:w=90:h=140:c=0x808080:t=fill:enable='between(t,2,2.7)'")
    assert shots(d) == [(0, 2), (2, 2.733), (2.733, 4)]


@pytest.mark.parametrize("at", [.3, 3.7])
def test_short_edge_shots_keep_the_cut(clip, at):
    n = round(at * cut.FPS)
    d = clip("color=0x404040:s=320x180:r=30:d=4,"
             f"drawbox=x=20:y=20:w=90:h=140:c=0xc0c0c0:t=fill:enable='lt(n,{n})',"
             f"drawbox=x=210:y=20:w=90:h=140:c=0xc0c0c0:t=fill:enable='gte(n,{n})'")
    assert shots(d) == [(0, at), (at, 4)]


def test_strong_cut_inside_busy_motion_still_splits(clip):
    d = clip("nullsrc=s=320x180:r=30:d=4,geq=lum='80+30*mod(N,3)':cb=128:cr=128,"
             "drawbox=x=0:y=0:w=150:h=180:c=0xb4b4b4:t=fill:enable='lt(t,2)',"
             "drawbox=x=170:y=0:w=150:h=180:c=0xb4b4b4:t=fill:enable='gte(t,2)'")
    assert shots(d) == [(0, 2), (2, 4)]
