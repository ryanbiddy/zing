"""Offline tests for learn-style (measure -> pack -> compare -> correct) and the local review dashboard."""
from __future__ import annotations

import http.client
import json
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from myzing.factory import learn, render, serve
from myzing.factory.tools import FactoryError

REF = {"captions": 40, "cap_y": 0.69, "text_height": 0.03, "words": 2.0, "upper": 0.1,
       "fill": [250, 250, 250], "plate": {"present": False}, "outline": {"present": True, "rgb": [10, 10, 10], "width": 0.003},
       "highlight": {"present": True, "mode": "active", "rgb": [230, 30, 40], "samples": 20, "with_color": 12}, "pop": {"measured": True, "ms": 100, "from": 0.8, "overshoot": False},
       "font": {"id": "anton", "family": "Anton", "weight": 400, "similarity": 0.7}, "layout": "speaker-full",
       "cuts_per_minute": 11.0}


def test_colors():
    assert learn.hex_of([255, 210.4, 63]) == "#FFD23F"
    assert learn.delta_e([255, 255, 255], [255, 255, 255]) == 0
    assert learn.delta_e([255, 0, 0], [0, 0, 255]) > 100


def test_caption_band_ignores_a_title_elsewhere():
    def track(i, y, text="word here"):
        return {"id": f"t{i}", "kind": "caption", "text": text,
                "samples": [{"t": i, "box": [0.2, y - 0.01, 0.8, y + 0.01]}]}
    tracks = [track(i, 0.7) for i in range(6)] + [track(9, 0.08, "SHOW NAME"), {"id": "x", "kind": "scene_text", "samples": []}]
    assert {t["id"] for t in learn.caption_band(tracks)} == {f"t{i}" for i in range(6)}


def test_pack_from_measurements():
    pack = learn.to_pack(REF, "red-word", render.theme("zing"))
    assert pack["cap_font"] == "Anton" and pack["cap_weight"] == 400
    assert pack["cap_y"] == 0.69 and pack["cap_words"] == 2 and pack["cap_upper"] is False
    assert pack["cap_ink"] == "#FAFAFA" and pack["cap_on"] == "#E61E28" and pack["accent"] == "#E61E28"
    assert pack["cap_bg"] == "none" and pack["cap_stroke"] == "#0A0A0A"
    assert pack["cap_pop_ms"] == 100 and pack["cap_pop_from"] == 0.8 and pack["cap_pop_overshoot"] is False
    assert pack["cap_size"] == round(0.03 * 1920 / 0.72)
    with pytest.raises(FactoryError):
        learn.to_pack({"captions": 0}, "x", {})


def test_emphasis_words_are_a_separate_mode():
    m = {**REF, "highlight": {"present": True, "mode": "emphasis", "rgb": [230, 30, 40], "samples": 24, "with_color": 6}}
    pack = learn.to_pack(m, "red-word", render.theme("zing"))
    assert pack["cap_emphasis"] == "#E61E28" and pack["cap_on"] == pack["cap_ink"] and pack["accent"] == "#E61E28"
    row = next(r for r in learn.compare(m, REF) if r["name"] == "word color")
    assert row["match"] is False and "6/24" in row["note"]


def test_layout_is_learned():
    pack = learn.to_pack({**REF, "layout": "speaker-top", "cap_y": 0.57, "header": False}, "split-top", render.theme("zing"))
    assert pack["split"] == "speaker-top" and pack["seam"] == 0.57 and pack["solo_fill"] and pack["hook_header"] is False
    plain = learn.to_pack({**REF, "header": True}, "plain", render.theme("zing"))
    assert "split" not in plain and plain["solo_fill"] and plain["hook_header"] is True
    rows = {r["name"]: r for r in learn.compare({**REF, "face_y": 0.3, "header": False}, {**REF, "face_y": 0.5, "header": True})}
    assert rows["speaker position"]["match"] is False and rows["title header"]["match"] is False


def test_compare_and_correct_converge():
    ours = {**REF, "cap_y": 0.75, "text_height": 0.036, "words": 3.0, "highlight": {"present": False},
            "pop": {"measured": True, "ms": 160, "from": 0.9, "overshoot": True}}
    rows = {r["name"]: r for r in learn.compare(REF, ours)}
    assert rows["caption position"]["match"] is False and rows["caption size"]["match"] is False
    assert rows["word color"]["match"] is False and rows["text color"]["match"] is True
    assert rows["pop-in time"]["match"] is True                      # 60 ms apart is within tolerance
    pack = learn.correct({"cap_size": 100, "cap_y": 0.69, "cap_words": 3, "cap_chars": 18, "cap_pop_ms": 100}, REF, ours)
    assert pack["cap_size"] == round(100 * 0.03 / 0.036) and pack["cap_y"] == pytest.approx(0.63)
    assert pack["cap_words"] == 2 and pack["cap_pop_ms"] == 40
    assert learn.compare(REF, {"captions": 0})[0]["match"] is False


def test_report_is_honest_about_unmeasured_traits():
    rows = learn.compare({**REF, "pop": {"measured": False}}, REF)
    assert next(r for r in rows if r["name"] == "pop-in time")["match"] is None
    md = learn.report_md("x", {"reference": REF, "matched": 8, "checked": 8,
                               "rounds": [{"comparison": rows}]})
    assert "not measured" in md and "original font, project and settings are unknown" in md


def test_learn_refuses_bad_inputs(tmp_path):
    with pytest.raises(FactoryError):
        learn.learn(tmp_path / "missing.mp4", "ok-name", tmp_path)
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"\0")
    with pytest.raises(FactoryError):
        learn.learn(ref, "Bad Name", tmp_path)
    with pytest.raises(FactoryError):
        learn.learn(ref, "ok-name", tmp_path)                        # not a clip folder


def test_user_packs_live_in_the_workspace(zing_workspace):
    render.user_packs().mkdir(parents=True)
    (render.user_packs() / "mine.json").write_text(json.dumps({"name": "Mine", "cap_y": 0.7}), encoding="utf-8")
    assert "mine" in render.themes() and render.theme("mine")["name"] == "Mine"
    with pytest.raises(FactoryError):
        render.theme("Mine")


# ---------------------------------------------------------------- dashboard
@pytest.fixture
def studio_server(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    clip = project / "clip01"
    (clip / "visuals" / "v1").mkdir(parents=True)
    (project / "factory.json").write_text(json.dumps({"shapes": ["9x16"], "pack": "zing"}), encoding="utf-8")
    (project / "source.json").write_text(json.dumps({"name": "Show"}), encoding="utf-8")
    (project / "moments.json").write_text(json.dumps({"moments": [{"start": 1, "end": 9, "hook": "*Hi*"}]}), encoding="utf-8")
    (clip / "clip.mp4").write_bytes(bytes(range(256)) * 4)
    (clip / "visuals" / "v1" / "a.jpg").write_bytes(b"\xff\xd8jpeg")
    (clip / "post.json").write_text(json.dumps({"x": "old"}), encoding="utf-8")
    (clip / "visuals" / "manifest.json").write_text(json.dumps({"v1": [{"path": "v1/a.jpg", "source": "nasa"}]}), encoding="utf-8")
    (clip / "plan-raw.json").write_text(json.dumps({"hook": "Hi", "shots": [{"from": 0, "layout": "split", "visual": "v1"}],
                                                    "visual_requests": [{"id": "v1", "query": "q"}]}), encoding="utf-8")
    (project / "secret.txt").write_text("no", encoding="utf-8")
    studio = serve.Studio(project)
    rendered = []
    monkeypatch.setattr(studio, "_rerender", lambda d: rendered.append(d.name))
    monkeypatch.setattr(serve.plan, "finalize", lambda d, raw, found: rendered.append(("final", sorted(found))))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), serve.handler(studio, port))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield port, project, studio, rendered
    server.shutdown()


def call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, json.dumps(body) if body is not None else None,
                 {"Content-Type": "application/json", **(headers or {})})
    res = conn.getresponse()
    data = res.read()
    return res.status, data, dict(res.getheaders())


def test_dashboard_serves_state_and_media(studio_server):
    port, project, _, _ = studio_server
    status, page, _ = call(port, "GET", "/")
    assert status == 200 and b'id="mock"' in page and b"zing-playbook" not in page
    status, data, _ = call(port, "GET", "/api/project")
    state = json.loads(data)
    assert state["project"] == "proj" and state["clips"][0]["videos"] == {"clip.mp4": "clip.mp4"}
    assert "zing" in state["packs"] and json.dumps(str(project))[1:-1] not in data.decode()
    status, data, headers = call(port, "GET", "/media/clip01/clip.mp4", headers={"Range": "bytes=10-19"})
    assert status == 206 and data == bytes(range(10, 20)) and headers["Content-Range"] == "bytes 10-19/1024"
    assert call(port, "GET", "/media/clip01/visuals/v1/a.jpg")[0] == 200
    for path in ("/media/clip01/../secret.txt", "/media/clip01/..%2F..%2Fsecret.txt", "/media/secret.txt", "/media/clip01/post.json"):
        assert call(port, "GET", path)[0] == 404, path


def test_dashboard_refuses_other_sites(studio_server):
    port, project, _, _ = studio_server
    assert call(port, "GET", "/api/project", headers={"Host": f"evil.example:{port}"})[0] == 403
    assert call(port, "POST", "/api/rate", {"clip": "clip01", "v": "post"}, {"Origin": "https://evil.example"})[0] == 403
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/api/rate", "clip=clip01", {"Content-Type": "application/x-www-form-urlencoded"})
    assert conn.getresponse().status == 415
    assert not (project / "ratings.json").exists()


def test_dashboard_actions(studio_server):
    port, project, studio, rendered = studio_server
    origin = {"Origin": f"http://127.0.0.1:{port}"}
    assert call(port, "POST", "/api/rate", {"clip": "clip01", "v": "fix", "why": "tighter"}, origin)[0] == 200
    assert json.loads((project / "ratings.json").read_text(encoding="utf-8"))["clip01"]["why"] == "tighter"
    assert call(port, "POST", "/api/rate", {"clip": "../x", "v": "post"}, origin)[0] == 400
    assert call(port, "POST", "/api/text", {"clip": "clip01", "field": "x", "text": "new copy"}, origin)[0] == 200
    assert json.loads((project / "clip01" / "post.json").read_text(encoding="utf-8"))["x"] == "new copy"
    assert call(port, "POST", "/api/text", {"clip": "clip01", "field": "evil", "text": "x"}, origin)[0] == 400
    assert call(port, "POST", "/api/visual", {"clip": "clip01", "request": "v1", "index": 3}, origin)[0] == 400
    assert call(port, "POST", "/api/visual", {"clip": "clip01", "request": "v1", "index": 0}, origin)[0] == 200
    for _ in range(50):
        if "clip01" in rendered:
            break
        threading.Event().wait(0.05)
    assert ("final", ["v1"]) in rendered and "clip01" in rendered
    picks = json.loads((project / "clip01" / "visuals" / "picks.json").read_text(encoding="utf-8"))
    assert picks["picks"]["v1"]["pick"] == 0
    assert call(port, "POST", "/api/render", {"clip": "clip01", "shape": "4x5"}, origin)[0] == 400
