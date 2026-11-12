"""Regressions from the factory review, with no model calls or downloads."""
from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import wave
from http.server import ThreadingHTTPServer

import pytest

from myzing.factory import cutout, judge, learn, pick, pipeline, plan, render, review, scout, serve, source
from myzing.factory.tools import data_path

RUN = subprocess.run
TOKEN = "factory-test-session"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    pipeline._write(root / "factory.json", {**pipeline.SETTINGS, "moments": 0, "shapes": ["9x16"]})
    pipeline._write(root / "source.json", {"media": str(root / "ep.mp4"), "name": "Show"})
    pipeline._write(root / "transcript.json", [{"s": 0, "e": 300, "text": "We built a rocket."}])
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 100, "end": 130, "hook": "Rocket", "snapped": True}]})
    return root


def prepared(root):
    d = root / "clip01"
    pipeline._write(d / "cams.json", {})
    pipeline._write(d / "words.json", {"duration": 30, "words": [
        {"w": w, "os": i, "oe": i + .5} for i, w in enumerate("We built a rocket.".split())]})
    pipeline._write(d / "post.json", {"x": "Rocket"})
    raw = {"hook": "Rocket", "shots": [{"from": 0, "layout": "split", "visual": "v1"}],
           "visual_requests": [{"id": "v1", "query": "rocket", "kind": "photo"}]}
    manifest = {"v1": [{"path": "a.jpg", "source": "nasa"}, {"path": "b.jpg", "source": "nasa"}]}
    pipeline._write(d / "visuals" / "manifest.json", manifest)
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"v1": {"pick": 0}}})
    pipeline._write(d / "plan-raw.json", raw)
    j = judge.Judge(root)
    j.save("clip01-plan", raw)
    j.save("clip01-pick", {"v1": {"pick": 1}})
    plan.finalize(d, raw, pick.chosen(d / "visuals", raw["visual_requests"], manifest, {"v1": {"pick": 0}}))
    return d


@pytest.mark.parametrize("start,end,add", [(50, 130, False), (100, 170, False), (125, 170, True)])
def test_extended_moments_get_words_at_both_ends(project, monkeypatch, start, end, add):
    pipeline._write(project / "words.json", [{"w": "Old.", "s": t, "e": t + .5} for t in range(100, 130)])
    if add:
        pipeline.add_clip(project, start, end)
    else:
        pipeline.trim(project, "clip01", start, end)
    asked = []

    def transcribe(media, pieces):
        asked.extend(pieces)
        return [{"w": "New.", "s": t, "e": t + .5} for t in range(start, end)]
    monkeypatch.setattr(source, "transcribe_moments", transcribe)
    got = pipeline._moments(project, judge.Judge(project), project / "ep.mp4", {"moments": 0}, lambda m: None)
    assert asked == [{"start": start, "end": end}]
    assert got[-1]["start"] == pytest.approx(start - .05)
    assert got[-1]["end"] > end - 1


def test_redo_scout_discards_every_old_clip(project):
    d = prepared(project)
    pipeline._write(d / "mattes" / "meta.json", {"why": "missing speaker"})
    pipeline._write(project / "pending" / "clip02-plan.md", {})
    pipeline._write(project / "answers" / "clip02-copy.json", {})
    pipeline._write(project / "answers" / "keep.json", {})
    pipeline.redo(project, "scout")
    assert not d.exists()
    assert not (project / "moments.json").exists()
    assert not list((project / "answers").glob("clip*"))
    assert not list((project / "pending").glob("clip*"))
    assert (project / "answers" / "keep.json").is_file()


def test_redo_plan_forgets_visual_choices_and_mattes(project):
    d = prepared(project)
    pipeline._write(d / "mattes" / "meta.json", {"why": "missing speaker"})
    pipeline._write(project / "pending" / "clip01-pick.md", {})
    pipeline.redo(project, "clip01-plan")
    assert judge.Judge(project).cached("clip01-pick") is None
    assert not (project / "pending" / "clip01-pick.md").exists()
    assert not (d / "mattes").exists() and not (d / "visuals").exists()
    assert not (d / "plan.json").exists()


def test_redo_pick_discards_the_saved_choice(project):
    d = prepared(project)
    pipeline.redo(project, "clip01-pick")
    assert not (d / "visuals" / "picks.json").exists()


@pytest.mark.parametrize("action", ["visual", "text"])
def test_dashboard_edits_keep_brand_graphics_and_labels(project, monkeypatch, action):
    d = prepared(project)
    cfg = pipeline._read(project / "factory.json")
    brand = {"name": "Acme", "url": "acme.com", "cta": "Try it now"}
    pipeline._write(project / "factory.json", {**cfg, "brand": brand})
    raw = pipeline._read(d / "plan-raw.json")
    raw["shots"] += [{"from": 2, "layout": "graphic", "graphic": {"kind": "title", "text": "Acme"},
                       "label": {"name": "Acme"}},
                      {"from": 5, "layout": "graphic", "graphic": {"kind": "endcard", **brand, "line": brand["cta"]}}]
    pipeline._write(d / "plan-raw.json", raw)
    plan.finalize(d, raw, {}, brand)
    studio = serve.Studio(project)
    monkeypatch.setattr(studio, "_rerender", lambda d: None)
    if action == "visual":
        studio.visual({"clip": "clip01", "request": "v1", "index": 1})
    else:
        studio.text({"clip": "clip01", "field": "hook", "text": "We built a rocket"})
    studio.jobs.get_nowait()[1]()
    shots = pipeline._read(d / "plan.json")["shots"]
    assert [s["layout"] for s in shots[-2:]] == ["graphic", "graphic"]
    assert shots[-2]["label"] == {"name": "Acme"}


@pytest.mark.parametrize("order", [("hook", "visual"), ("visual", "hook")])
def test_dashboard_hook_and_visual_survive_run(project, monkeypatch, order):
    d = prepared(project)
    monkeypatch.setattr(pick, "sheet", lambda *a: d / "visuals" / "pick_sheet.jpg")
    monkeypatch.setattr(render, "render", lambda *a: None)
    studio = serve.Studio(project)
    for action in order:
        if action == "hook":
            studio.text({"clip": "clip01", "field": "hook", "text": "We built a rocket"})
        else:
            studio.visual({"clip": "clip01", "request": "v1", "index": 1})
    while not studio.jobs.empty():
        studio.jobs.get_nowait()[1]()
    pipeline.run(project, judge.Judge(project), say=lambda m: None)
    assert pipeline._read(d / "plan-raw.json")["hook"] == "We built a rocket"
    assert pipeline._read(d / "plan.json")["hook"] == "We built a rocket"
    assert pipeline._read(d / "visuals" / "picks.json")["picks"]["v1"]["pick"] == 1
    assert pipeline._read(d / "plan.json")["visuals"]["v1"]["path"].endswith("b.jpg")


def test_newer_picks_rebuild_the_final_plan(project, monkeypatch):
    d = prepared(project)
    monkeypatch.setattr(pick, "sheet", lambda *a: d / "visuals" / "pick_sheet.jpg")
    monkeypatch.setattr(render, "render", lambda *a: None)
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"v1": {"pick": 1}}})
    old = (d / "plan.json").stat().st_mtime - 10
    os.utime(d / "plan.json", (old, old))
    os.utime(project / "answers" / "clip01-plan.json", (old - 1, old - 1))
    pipeline.run(project, judge.Judge(project), say=lambda m: None)
    assert pipeline._read(d / "plan.json")["visuals"]["v1"]["path"].endswith("b.jpg")


def test_queued_bench_clicks_keep_their_original_moments(project, monkeypatch):
    data = pipeline.load_moments(project)
    bench = [{"start": a, "end": a + 20, "hook": str(a)} for a in (10, 40, 70)]
    pipeline._write(project / "moments.json", {**data, "bench": bench})
    studio = serve.Studio(project)
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: None)
    studio.bench({"index": 0})
    studio.bench({"index": 1})
    while not studio.jobs.empty():
        studio.jobs.get_nowait()[1]()
    data = pipeline.load_moments(project)
    assert [m["start"] for m in data["moments"][-2:]] == [10, 40]
    assert [m["start"] for m in data["bench"]] == [70]


DOM = r"""
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.nodeType = 1; this.children = []; this.attrs = {}; this.events = {};
    this.style = {setProperty(k, v) { this[k] = v; }}; this.dataset = {}; this.textContent = '';
    this.classList = {add() {}, remove() {}, toggle() {}};
  }
  set innerHTML(v) { throw Error('HTML text insertion'); }
  setAttribute(k, v) { this.attrs[k] = v; if (k === 'value') this.value = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  toggleAttribute(k, v) { if (v) this.attrs[k] = ''; else delete this.attrs[k]; }
  addEventListener(k, fn) { this.events[k] = fn; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  scrollIntoView() {}
  querySelector(sel) { return nodes[sel] ||= new Element(); }
}
const nodes = {}, timers = new Map(); let nextTimer = 0;
const document = {createElement: tag => new Element(tag), createTextNode: text => ({nodeType: 3, textContent: text}),
  querySelector: sel => nodes[sel] ||= new Element(), documentElement: new Element(), body: new Element(),
  fonts: {load: async () => []}};
const location = {search: ''};
const requestAnimationFrame = () => {};
const setTimeout = (fn, ms) => { timers.set(++nextTimer, {fn, ms}); return nextTimer; };
const clearTimeout = id => timers.delete(id);
const all = n => [n, ...(n.children || []).flatMap(c => typeof c === 'object' ? all(c) : [])];
"""


def javascript(page, code, data=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    script = data_path(page).read_text(encoding="utf-8").split("<script>")[-1].split("</script>")[0]
    if page == "dashboard.html":
        script = script.rsplit("\nload();", 1)[0]
    else:
        script = script.split("// Geometry per delivery shape.")[0]
    program = DOM + "\nconst window = {DATA: " + json.dumps(data or {"words": [], "fps": 30}) + "};\n" + script
    program += "\n(async () => {\n" + code + "\n})().catch(e => { console.error(e); process.exitCode = 1; });"
    result = RUN([node, "-"], input=program, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("state,jobs", [("running", []), ("done", ["clip01"])])
def test_dashboard_polls_until_work_is_done(state, jobs):
    got = javascript("dashboard.html", """
      render = () => {};
      api.project = async () => ({state: STATE, jobs: JOBS});
      await load(); await load();
      const pending = [...timers.values()].map(t => t.ms);
      api.project = async () => ({state: 'done', jobs: []});
      const tick = [...timers.values()][0];
      if (tick) await tick.fn();
      console.log(JSON.stringify({pending, left: timers.size}));
    """.replace("STATE", json.dumps(state)).replace("JOBS", json.dumps(jobs)))
    assert got == {"pending": [1500], "left": 0}


def test_dashboard_shows_worker_errors_as_text():
    got = javascript("dashboard.html", """
      ui.project = {state: 'done', clips: [], error: '<img src=x onerror=alert(1)>'};
      render();
      console.log(JSON.stringify(Object.values(nodes).flatMap(all).map(n => n.textContent)));
    """)
    assert "<img src=x onerror=alert(1)>" in got


def test_dashboard_loads_ratings_and_keeps_saved_reasons():
    got = javascript("dashboard.html", """
      ui.project = {settings: {pack: 'zing'}};
      const c = {clip: 'clip01', videos: {'clip.mp4': ''}, rating: {v: 'fix', why: 'Tighter'}};
      let sent;
      api.rate = async (...args) => { sent = args; };
      act = async (button, call) => call();
      const card = clipCard(c), parts = all(card);
      const reason = parts.find(n => n.attrs && n.attrs.id === 'why-clip01');
      const buttons = parts.filter(n => n.tagName === 'button');
      const fix = buttons.find(n => n.children.some(c => c.textContent === 'Post with edits'));
      await buttons.find(n => n.children.some(c => c.textContent === 'Post')).events.click({currentTarget: new Element()});
      ui.why.clip01 = '';
      const cleared = all(clipCard(c)).find(n => n.attrs && n.attrs.id === 'why-clip01');
      console.log(JSON.stringify([reason.value, fix.attrs['aria-pressed'], sent, cleared.value]));
    """)
    assert got == ["Tighter", "true", ["clip01", "post", "Tighter"], ""]


def test_dashboard_plays_the_selected_style_pack():
    got = javascript("dashboard.html", """
      ui.project = {settings: {pack: 'zing'}}; ui.pack.clip01 = 'swiss'; ui.shape.clip01 = '4x5';
      const c = {clip: 'clip01', videos: {'clip.mp4': '', 'clip-4x5-swiss.mp4': ''}};
      console.log(JSON.stringify([shapesFor(c).map(s => s.id),
        all(clipCard(c)).find(n => n.tagName === 'video').attrs.src]));
    """)
    assert got == [["4x5"], "/media/clip01/clip-4x5-swiss.mp4"]


@pytest.mark.parametrize("path,kind,want", [("v1/a.mp4", "video", "v1/a.pick.jpg"),
                                              ("v1/a.webm", "video", "v1/a.pick.jpg"),
                                              ("v1/a.jpg", "image", "v1/a.jpg")])
def test_dashboard_uses_video_posters(path, kind, want):
    got = javascript("dashboard.html", """
      const c = {clip: 'clip01', candidates: {v1: [CANDIDATE]}};
      const block = requestBlock(c, {id: 'v1', query: '<img src=x>'});
      console.log(JSON.stringify(all(block).find(n => n.tagName === 'img').attrs.src));
    """.replace("CANDIDATE", json.dumps({"path": path, "media_type": kind})))
    assert got == "/media/clip01/visuals/" + want


def test_dashboard_trim_includes_the_last_transcript_line():
    got = javascript("dashboard.html", """
      ui.lines = [{s: 0, e: 4, text: 'First'}, {s: 4, e: 8, text: 'Last'}];
      await startTrim({clip: 'clip01', start: 0, end: 8.5});
      console.log(JSON.stringify([ui.pick.a, ui.pick.b]));
    """)
    assert got == [0, 1]


@pytest.mark.parametrize("values", [[500, 50, 0], [10, 0, -10], [0, 0, 0]])
def test_funnel_widths_stay_finite(values):
    got = javascript("scene.html", """
      const rows = VALUES.map(() => ({style: {}, children: [{style: {}}, {style: {}}]}));
      const el = {dataset: {id: 'g'}, querySelectorAll: () => rows};
      drawGraphic({id: 'g', kind: 'funnel', from: 0, rows: VALUES.map(value => ({value}))}, 10, el);
      console.log(JSON.stringify(rows.map(r => parseFloat(r.children[0].style.width))));
    """.replace("VALUES", json.dumps(values)))
    assert all(isinstance(w, (int, float)) and 0 < w <= 960 for w in got)
    assert got == sorted(got, reverse=True)


@pytest.mark.parametrize("graphic,want", [({"value": 3.5, "suffix": "%"}, "3.5%"),
                                          ({"value": 3.5, "decimals": 0}, "4"),
                                          ({"value": 1886, "format": "year"}, "1886")])
def test_counter_preserves_decimal_values(graphic, want):
    got = javascript("scene.html", """
      const num = {style: {}}, lab = {style: {}};
      const el = {dataset: {id: 'g'}, querySelector: s => s === '.g-num' ? num : lab};
      drawGraphic({id: 'g', kind: 'counter', from: 0, ...GRAPHIC}, 10, el);
      console.log(JSON.stringify(num.textContent));
    """.replace("GRAPHIC", json.dumps(graphic)))
    assert got == want


@pytest.mark.parametrize("quick", ["small", None])
def test_only_the_discarded_scout_pass_gets_a_duration(project, monkeypatch, quick):
    from myzing.study import transcribe
    from myzing.schemas import Word
    calls = []

    def extract(*args):
        with wave.open(str(args[-1]), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0" * 32000 * 200)

    def speech(wav, **kwargs):
        calls.append(kwargs)
        return transcribe.TranscribeResult(words=[Word(text="Rocket.", start=0, end=1)])
    monkeypatch.setattr(source, "run", extract)
    monkeypatch.setattr(source, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(source, "scout_model", lambda: quick)
    monkeypatch.setattr(transcribe, "transcribe", speech)
    (project / "transcript.json").unlink()
    pipeline._transcript(project, project / "ep.mp4", lambda m: None)
    assert calls[0]["duration"] == (200 if quick else 0)
    assert (project / "words.json").exists() is (quick is None)
    source._speech(project / "ep.mp4", 20, 230, language="en")
    assert calls[-1]["duration"] == 210 and calls[-1]["language"] == "en"


MEASURED = {"captions": 10, "text_height": .05, "cap_y": .7, "words": 2, "upper": 0,
            "fill": [255, 255, 255], "plate": {"present": False}, "outline": {"present": False}}


@pytest.mark.parametrize("base,want", [({}, "#FFFFFF"), ({"cap_ink": "#EEEEEE"}, "#EEEEEE")])
def test_learn_style_accepts_an_unknown_fill(base, want):
    assert learn.to_pack({**MEASURED, "fill": None}, "mine", base)["cap_ink"] == want


def test_landscape_learned_caption_size_matches_the_reference():
    pack = learn.to_pack({**MEASURED, "shape": "16x9"}, "mine", {})
    got = javascript("scene.html", "console.log(JSON.stringify(document.documentElement.style['--cap-size']));",
                     {"words": [], "fps": 30, "W": 1920, "H": 1080, "theme": pack})
    assert float(got[:-2]) == pytest.approx(.05 * 1080 / .72, abs=1)


@pytest.mark.parametrize("pack", ["launch", "documentary"])
def test_review_defaults_to_the_project_pack(project, pack):
    d = prepared(project)
    cfg = pipeline._read(project / "factory.json")
    pipeline._write(project / "factory.json", {**cfg, "pack": pack})
    (d / f"clip-{pack}.mp4").write_bytes(b"video")
    assert f"clip01/clip-{pack}.mp4" in review.build(project).read_text(encoding="utf-8")
    assert f"clip01/clip-{pack}.mp4" not in review.build(project, "zing").read_text(encoding="utf-8")


def test_snap_never_starts_before_the_episode():
    got = scout.snap({"start": 0, "end": 1}, [{"w": "Hello.", "s": 0, "e": .5}])
    assert got["start"] == 0


def test_snap_keeps_the_end_after_leading_fillers():
    got = scout.snap({"start": 0, "end": 1}, [{"w": "Um", "s": 0, "e": .4},
                                             {"w": "So", "s": .5, "e": .9},
                                             {"w": "Rocket", "s": 2, "e": 2.5}])
    assert 0 <= got["start"] < got["end"] and got["end"] == 2.55


def test_rejected_cutouts_are_retried_for_different_frames(project, monkeypatch):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    d = prepared(project)
    pipeline._write(d / "cams.json", {"frames": 60})
    monkeypatch.setattr(cv2, "imread", lambda *a: np.zeros((20, 20, 3), np.uint8))
    monkeypatch.setattr(cv2, "imwrite", lambda *a: True)
    monkeypatch.setattr(cutout, "tidy", lambda a: a)
    calls = []

    def segment(rgb):
        calls.append(1)
        return np.zeros((20, 20), np.float32)
    monkeypatch.setattr(cutout, "segment", segment)
    assert cutout.mattes(d, [(0, .1)]) is None
    count = len(calls)
    assert cutout.mattes(d, [(0, .1)]) is None and len(calls) == count
    alpha = np.zeros((20, 20), np.float32)
    alpha[:, :8] = 1
    monkeypatch.setattr(cutout, "segment", lambda rgb: alpha)
    got = cutout.mattes(d, [(1, 1.1)])
    assert got is not None and got["frames"] == [31, 32, 33, 34]


@pytest.fixture
def dashboard(project, monkeypatch):
    prepared(project)
    (project / "clip01" / "clip.mp4").write_bytes(b"video")
    monkeypatch.setattr(secrets, "token_urlsafe", lambda n: TOKEN)
    servers, printed = [], []
    ready = threading.Event()

    def server(*args):
        result = ThreadingHTTPServer(*args)
        servers.append(result)
        return result

    def say(line):
        printed.append(line)
        ready.set()
    monkeypatch.setattr(serve, "ThreadingHTTPServer", server)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    thread = threading.Thread(target=serve.serve, args=(project, port), kwargs={"say": say}, daemon=True)
    thread.start()
    assert ready.wait(5)
    yield port, printed
    servers[0].shutdown()
    thread.join(5)


def request(port, method, path, cookie=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, None,
                     {"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {}), **(headers or {})})
        res = conn.getresponse()
        return res.status, res.read(), dict(res.getheaders())
    finally:
        conn.close()


@pytest.mark.parametrize("path", ["/", "/api/project", "/api/transcript", "/media/clip01/clip.mp4"])
def test_dashboard_requires_the_session_cookie(dashboard, path):
    port, _ = dashboard
    status, body, headers = request(port, "GET", path)
    assert status == 403 and headers["Content-Type"].startswith("text/plain")
    assert b"zing factory serve" in body and len(body.splitlines()) == 1
    assert request(port, "GET", path, f"zing_dash_{port}=wrong")[0] == 403
    assert request(port, "HEAD", path)[0] == 403


@pytest.mark.parametrize("path", ["/", "/api/project", "/media/clip01/clip.mp4"])
def test_dashboard_token_sets_cookie_and_redirects(dashboard, path):
    port, printed = dashboard
    assert f"http://127.0.0.1:{port}/?t={TOKEN}" in printed[0]
    status, _, headers = request(port, "GET", path + f"?t={TOKEN}&theme=dark")
    assert status == 303 and headers["Location"] == path
    assert headers["Set-Cookie"] == f"zing_dash_{port}={TOKEN}; HttpOnly; SameSite=Strict; Path=/"
    assert request(port, "GET", path, headers["Set-Cookie"].split(";", 1)[0])[0] == 200


def test_dashboard_refuses_wrong_tokens_and_unauthenticated_posts(dashboard):
    port, _ = dashboard
    assert request(port, "GET", "/?t=wrong")[0] == 403
    assert request(port, "GET", "/?t=wrong", f"zing_dash_{port}={TOKEN}")[0] == 403
    assert request(port, "POST", f"/api/run?t={TOKEN}")[0] == 403
    assert request(port, "POST", "/api/run", f"zing_dash_{port}=wrong")[0] == 403
    assert request(port, "GET", "/?t=" + TOKEN, headers={"Host": "evil.example"})[0] == 403
    assert request(port, "POST", "/api/run", f"zing_dash_{port}={TOKEN}", {"Origin": "https://evil.example"})[0] == 403
