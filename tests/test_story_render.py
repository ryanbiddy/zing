"""Offline story capture, cue parity and small real renders using factory's gates."""
from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from myzing.factory import tools
from myzing.story import StoryError, data_path
from myzing.story import render
from test_factory_brand_kit import browser_tools


def story_folder(tmp_path: Path) -> Path:
    story = {
        "slug": "paper-bird", "topic": "a paper bird", "handle": "",
        "sources": [{"title": "An invented example", "url": "https://example.test/story"}],
        "cast": {"nia": {"name": "Nia Penn"}}, "outro": 1,
        "beats": [{"id": f"beat-{i}", "chapter": "PAPER BIRD", "lines": [{"text": text}]}
                  for i, text in enumerate(["Nia folded paper.", "A bird took shape.", "One wing bent.", "It flew anyway."])],
        "panels": [{"from": "beat-0", "set": {"wall": "#FFD21F", "floor": "#17161C"},
                    "actors": [{"who": "nia", "x": 300, "pose": "wave"}],
                    "props": [{"prop": "star", "x": 800, "y": 800}],
                    "cards": [{"kind": "sticker", "text": "PAPER BIRD", "x": 70, "y": 190,
                               "size": 120, "at": 0}]}],
    }
    timings = {"duration": 1.5, "outro_start": .5, "provider": "lines", "voice": None, "beats": []}
    for i, beat in enumerate(story["beats"]):
        start, end = round(.1 + i * .1, 3), round(.2 + i * .1, 3)
        timings["beats"].append({"id": beat["id"], "start": start, "end": end,
                                 "lines": [{"text": beat["lines"][0]["text"], "start": start, "end": end}]})
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    (tmp_path / "timings.json").write_text(json.dumps(timings), encoding="utf-8")
    with wave.open(str(tmp_path / "narration.wav"), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 36000)
    return tmp_path


def node_page_script(body: str, tmp_path: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    script = tmp_path / "page-test.cjs"
    script.write_text("const fs=require('fs'),vm=require('vm');global.window={};\n"
                      "const html=fs.readFileSync(process.argv[2],'utf8');\n"
                      "vm.runInThisContext(html.match(/<script>([\\s\\S]*)<\\/script>/)[1]);\n" + body,
                      encoding="utf-8")
    result = subprocess.run([node, str(script), str(data_path("cutout.html"))], check=True,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    return json.loads(result.stdout)


def test_page_vocabulary_and_cues_match_python(tmp_path):
    from myzing.story.contract import cue_time

    timings = {"outro_start": 12, "beats": [{"id": "some-beat", "start": 2,
               "lines": [{"start": 2.3, "end": 4.3}, {"start": 5, "end": 9}]}]}
    cues = [0, 2.4, "some-beat", "some-beat:0", "some-beat:1:0.25", "some-beat:1:-0.3",
            "some-beat+0.2", "some-beat-0.2", "some-beat:1:0.5+0.2", "outro", "outro-0.3"]
    result = node_page_script(f"const T={json.dumps(timings)},cues={json.dumps(cues)};\n"
                              "console.log(JSON.stringify({vocabulary:window.storyVocabulary,"
                              "times:cues.map(c=>window.cueTime(c,T))}));", tmp_path)
    vocabulary = json.loads(data_path("vocabulary.json").read_text(encoding="utf-8"))
    for key in ("cards", "props", "poses"):
        assert set(result["vocabulary"][key]) == set(vocabulary[key])
    expected = [0, 2.4, 2, 2.3, 6, 4.7, 2.2, 1.8, 7.2, 12, 11.7]
    assert result["times"] == pytest.approx(expected)
    assert [cue_time(cue, timings) for cue in cues] == pytest.approx(result["times"])


def test_page_rejects_invalid_cues(tmp_path):
    result = node_page_script("const T={outro_start:12,beats:[{id:'beat',start:0,lines:[{start:0,end:1}]}]};\n"
                              "const cues=['missing','beat:1','beat:0:1.1','outro:0','beat:0:nope','beat:.5',null];\n"
                              "console.log(JSON.stringify({rejected:cues.map(c=>{try{window.cueTime(c,T);return false;}"
                              "catch{return true;}})}));", tmp_path)
    assert all(result["rejected"])


def test_page_has_only_local_assets_and_deterministic_clock():
    page = data_path("cutout.html").read_text(encoding="utf-8")
    assert "Math.random" not in page and "Date" not in page
    assert "src:url(../fonts/Anton-Regular.ttf)" in page
    assert "_proto" not in page and "https://" not in page
    assert "fetch(" not in page and "XMLHttpRequest" not in page


@pytest.mark.parametrize("stills", ["", "oops", "-0.1", "1.5", "NaN", "Infinity", []])
def test_stills_reject_bad_times(tmp_path, stills):
    with pytest.raises(StoryError, match="[Ss]till"):
        render.render(story_folder(tmp_path), stills=stills)


def test_render_refuses_audio_timing_mismatch(tmp_path):
    directory = story_folder(tmp_path)
    with wave.open(str(directory / "narration.wav"), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 12000)
    with pytest.raises(StoryError, match="different durations"):
        render.render(directory)


def test_failed_encoding_preserves_output(tmp_path, monkeypatch):
    directory = story_folder(tmp_path)
    output = directory / "story.mp4"
    output.write_bytes(b"previous good output")
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render, "capture", lambda *args: None)

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr=b"encoder failed")

    monkeypatch.setattr(render, "run", fail)
    with pytest.raises(StoryError, match="encoder failed"):
        render.render(directory)
    assert output.read_bytes() == b"previous good output"
    assert not list(directory.glob(".story-render-*"))


def test_real_stills_are_deterministic(tmp_path, browser_tools):
    directory = story_folder(tmp_path)
    images = render.render(directory, stills=[.4, 1.2, .4])
    assert len(images) == 3
    assert all(image.read_bytes().startswith(b"\xff\xd8") for image in images)
    assert images[0].read_bytes() == images[2].read_bytes()
    assert images[0].read_bytes() != images[1].read_bytes()


def test_real_page_fits_cards_and_resets_build(tmp_path, browser_tools):
    from myzing.story.outro import prepare

    directory = story_folder(tmp_path)
    story = json.loads((directory / "story.json").read_text(encoding="utf-8"))
    timings = json.loads((directory / "timings.json").read_text(encoding="utf-8"))
    # Hold the set still while measuring an unusually wide, legal sticker.
    timings["outro_start"] = 10
    timings["duration"] = 12
    story["panels"][0]["cards"][0].update(text="W" * 32, size=260, rot=12)
    story["panels"][0]["cards"].append({"kind": "doc", "text": "PAPER", "x": 500, "y": 600, "at": 0})
    data = {"story": prepare(story, timings), "timings": timings,
            "base": directory.as_uri() + "/", "vocabulary": json.loads(data_path("vocabulary.json").read_text(encoding="utf-8"))}
    data_file = directory / "page-data.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = directory / "inspect.cjs"
    script.write_text("""
const fs=require('fs'),{pathToFileURL}=require('url');
const {chromium}=require(require.resolve('playwright-core',{paths:[process.cwd()]}));
(async()=>{
  const data=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
  const browser=await chromium.launch({executablePath:process.env.ZING_BROWSER_PATH,args:['--allow-file-access-from-files']});
  try {
    const page=await browser.newPage({viewport:{width:1080,height:1920},offline:true});
    await page.goto(pathToFileURL(process.argv[2]).href);
    const result=await page.evaluate(async d=>{
      await window.build(d.story,d.timings,d.base,d.vocabulary);
      window.seek(3);
      const first=document.getElementById('world').innerHTML;
      await window.build(d.story,d.timings,d.base,d.vocabulary);
      window.seek(3);
      const rect=document.querySelector('.card').firstElementChild.getBoundingClientRect();
      const range=document.createRange();range.selectNodeContents(document.querySelector('.sticker'));
      const text=range.getBoundingClientRect();
      return {equal:first===document.getElementById('world').innerHTML,
        panels:document.querySelectorAll('.panel').length,
        box:{left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom},
        text:{left:text.left,top:text.top,right:text.right,bottom:text.bottom},
        left:document.getElementById('barL').textContent,right:document.getElementById('barR').style.display,
        document:document.querySelector('.doc').textContent};
    },data);
    await page.screenshot({path:process.argv[4],type:'jpeg'});
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
""", encoding="utf-8")
    node, sidecar = tools.node_sidecar()
    got = tools.run(node, script, data_path("cutout.html"), data_file, directory / "layout.jpg",
                    cwd=sidecar, env=tools.sidecar_env(directory / "browser"),
                    capture_output=True, text=True, encoding="utf-8", timeout=30)
    result = json.loads(got.stdout)
    assert result["equal"] and result["panels"] == 2
    assert 0 <= result["box"]["left"] < result["box"]["right"] <= 1080
    assert 0 <= result["box"]["top"] < result["box"]["bottom"] <= 1920
    assert result["box"]["left"] <= result["text"]["left"] < result["text"]["right"] <= result["box"]["right"]
    assert result["left"] == "zing · a paper bird" and result["right"] == "none"
    assert result["document"] == "PAPER"


def test_real_render_smoke(tmp_path, browser_tools):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg not installed")
    output = render.render(story_folder(tmp_path))
    result = tools.run(tools.ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json",
                       output, capture_output=True, text=True)
    probe = json.loads(result.stdout)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1080, 1920, "30/1")
    assert any(stream["codec_type"] == "audio" for stream in probe["streams"])
    assert float(probe["format"]["duration"]) == pytest.approx(1.5, abs=1 / 30)
