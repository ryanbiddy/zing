"""Context links and a guest approval page stay local and follow the rendered clips."""
from __future__ import annotations

import html
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from myzing.factory import approval, command, judge, pipeline, postcopy, render, source


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


def copy():
    return {**dict.fromkeys(postcopy.FIELDS, "{SOURCE_URL}"), "first_comment": "Full talk {SOURCE_URL} at {TIMESTAMP}"}


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc&t=125s"),
    ("https://youtu.be/abc", "https://youtu.be/abc?t=125s"),
    ("https://youtube.com/watch?v=abc&t=3m", "https://youtube.com/watch?v=abc&t=125s"),
    ("https://youtu.be/abc?t=9&si=share&t=10", "https://youtu.be/abc?si=share&t=125s"),
    ("https://www.youtube.com/watch?list=PL123&v=abc&index=2",
     "https://www.youtube.com/watch?list=PL123&v=abc&index=2&t=125s"),
    ("https://youtu.be/abc?list=PL123&index=2&t=20", "https://youtu.be/abc?list=PL123&index=2&t=125s"),
    ("https://youtube.com/watch?v=abc&t=4&feature=share#chapter",
     "https://youtube.com/watch?v=abc&feature=share&t=125s#chapter"),
    ("http://m.youtube.com/watch?v=abc&feature=", "http://m.youtube.com/watch?v=abc&feature=&t=125s"),
    ("https://www.youtu.be/abc?si=share", "https://www.youtu.be/abc?si=share&t=125s"),
])
def test_first_comment_links_to_the_full_moment(url, expected):
    answer = copy()
    post = postcopy.finalize(answer, {"start": 125.9}, {"url": url})
    assert post["first_comment"] == f"Full talk {expected} at 2:05"
    assert all(post[k] == url for k in postcopy.FIELDS if k != "first_comment")
    assert answer == copy()


@pytest.mark.parametrize("url", [
    "https://x.com/person/status/123?t=5", "https://example.org/talk?list=1&t=5#part",
    "https://youtube.com.example.org/watch?v=abc", "https://notyoutube.com/watch?v=abc",
    "https://youtube.com/playlist?list=PL123", "https://youtube.com/shorts/abc",
    "https://youtube.com/watch?list=PL123", "https://youtu.be/", "https://[broken", "",
])
def test_other_links_are_unchanged(url):
    post = postcopy.finalize(copy(), {"start": 125.9}, {"url": url})
    assert post["first_comment"] == f"Full talk {url} at 2:05"


def test_links_start_at_zero_and_at_the_first_launch_span():
    src = {"url": "https://youtu.be/abc?t=9"}
    assert postcopy.finalize(copy(), {"start": 0.9}, src)["first_comment"].endswith("abc?t=0s at 0:00")
    words = {"start": 5, "spans": [[305.4, 320], [5, 20]]}
    assert postcopy.finalize(copy(), words, src)["first_comment"].endswith("abc?t=305s at 5:05")


@pytest.mark.parametrize("location", ["source", "factory", "both"])
def test_copy_uses_the_project_source_url(tmp_path, location):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"\0")
    root = tmp_path / "project"
    url = "https://www.youtube.com/watch?v=abc"
    cfg = pipeline.init(root, media, url=url if location != "factory" else "")["settings"]
    if location != "source":
        cfg["url"] = url if location == "factory" else "https://youtu.be/other"
        (root / "factory.json").write_text(json.dumps(cfg), encoding="utf-8")
    d = root / "clip01"
    d.mkdir()
    (d / "cams.json").write_text("{}", encoding="utf-8")
    (d / "words.json").write_text(json.dumps({"start": 125, "duration": 2,
                                              "words": [{"w": "Hello.", "os": 0, "oe": 1}]}), encoding="utf-8")
    ask = judge.Judge(root)
    ask.save("clip01-copy", copy())
    assert pipeline._clip(root, 1, {"hook": "Hello"}, ask, media, cfg, [], lambda m: None) == ["clip01-plan"]
    post = json.loads((d / "post.json").read_text(encoding="utf-8"))
    assert post["first_comment"] == f"Full talk {url}&t=125s at 2:05"


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def project(tmp_path, pack="zing"):
    root = tmp_path / "Show #1 & guests"
    root.mkdir()
    (root / "source.json").write_text(json.dumps({"name": "Show <1> & guests"}), encoding="utf-8")
    (root / "factory.json").write_text(json.dumps({"pack": pack}), encoding="utf-8")
    (root / "moments.json").write_text(json.dumps({"moments": [{"hook": h} for h in
                                       ("Old hook", "Second hook", "Square only", "Not rendered")]}), encoding="utf-8")
    for i in (1, 2, 3):
        d = root / f"clip{i:02d}"
        d.mkdir()
        (d / f"clip{render.suffix('1x1' if i == 3 else '9x16', pack)}.mp4").write_bytes(b"\0")
        text = f"Every word from clip {i}. <img src=x onerror=alert(1)> & the last word."
        (d / "words.json").write_text(json.dumps({"words": [{"w": w} for w in text.split()]}), encoding="utf-8")
    (root / "clip01" / "plan.json").write_text(json.dumps({"hook": '<script>alert("hi")</script>'}), encoding="utf-8")
    (root / "clip01" / "context.json").write_text(json.dumps({"text": {"before": "Before <b>this</b> & that.",
                                                              "after": "After </p><script>bad()</script>."}}), encoding="utf-8")
    return root


@pytest.mark.parametrize("pack", ["zing", "launch", "swiss"])
def test_approval_includes_rendered_portrait_clips_and_escapes_all_text(tmp_path, pack):
    root = project(tmp_path, pack)
    out = approval.build(root)
    assert out == root / "approval.html"
    text = out.read_text(encoding="utf-8")
    page = Page(text)
    assert [a["data-clip"] for t, a in page.tags if t == "article"] == ["clip01", "clip02"]
    paths = [a["src"].removesuffix("#t=0.5") for t, a in page.tags if t == "video"]
    assert paths == [f"clip{i:02d}/clip{render.suffix('9x16', pack)}.mp4" for i in (1, 2)]
    assert all((out.parent / unquote(p)).is_file() and not urlsplit(p).scheme for p in paths)
    assert html.escape('<script>alert("hi")</script>') in text and "Old hook" not in text
    assert "Second hook" in text and "Square only" not in text and "Not rendered" not in text
    assert "Show &lt;1&gt; &amp; guests" in text
    for i in (1, 2):
        assert html.escape(f"Every word from clip {i}. <img src=x onerror=alert(1)> & the last word.") in text
    assert "Before &lt;b&gt;this&lt;/b&gt; &amp; that." in text
    assert "After &lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;." in text
    assert sum(t == "script" for t, a in page.tags) == 1
    assert not any(t in {"img", "link", "iframe"} or (t == "script" and "src" in a) for t, a in page.tags)
    votes = [a for t, a in page.tags if t == "input"]
    assert [(a["name"], a["value"]) for a in votes] == [(f"clip{i:02d}", v) for i in (1, 2) for v in ("Yes", "No")]
    assert all("checked" not in a for a in votes)
    assert "Copy my answers" in text and "output.select()" in text


@pytest.mark.parametrize("custom", [False, True])
def test_approval_cli_and_relative_paths_from_the_output_folder(tmp_path, capsys, custom):
    root = project(tmp_path)
    out = tmp_path / "review copies" / "guest.html" if custom else root / "approval.html"
    assert command.run(["approval", str(root), *(["--out", str(out)] if custom else [])]) == 0
    assert Path(json.loads(capsys.readouterr().out)["approval"]) == out
    paths = [a["src"].removesuffix("#t=0.5") for t, a in Page(out.read_text(encoding="utf-8")).tags if t == "video"]
    assert len(paths) == 2
    for i, path in enumerate(paths, 1):
        assert not urlsplit(path).scheme and not Path(path).is_absolute() and "\\" not in path
        assert (out.parent / unquote(path)).resolve() == (root / f"clip{i:02d}" / "clip.mp4").resolve()
    if custom:
        assert "%23" in paths[0] and "%20" in paths[0] and not (root / "approval.html").exists()


def test_approval_without_renders_or_a_project(tmp_path, capsys):
    assert "No rendered 9x16 clips yet." in approval.build(tmp_path).read_text(encoding="utf-8")
    assert command.run(["approval", str(tmp_path / "missing")]) == 2
    assert "project folder does not exist" in capsys.readouterr().err
    assert not (tmp_path / "missing").exists()
