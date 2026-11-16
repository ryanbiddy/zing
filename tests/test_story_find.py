"""Commons picture search and downloads use mocked HTTP and drawn images."""
from __future__ import annotations

import copy
import io
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest
from PIL import Image, ImageDraw

from myzing.factory import network, visuals
from myzing.story import StoryError, commons


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked network request")
    monkeypatch.setattr(visuals.socket, "getaddrinfo", refuse)
    monkeypatch.setattr(visuals.urllib.request, "build_opener", refuse)
    monkeypatch.setattr(visuals.urllib.request, "urlopen", refuse)


def page(*, title="File:Paper circle.png", license="CC BY 4.0", author="<a>Test artist</a>"):
    return {"title": title, "imageinfo": [{
        "mime": "image/png", "width": 900, "height": 600, "size": 12000,
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Paper_circle.png",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Paper_circle.png",
        "extmetadata": {"Artist": {"value": author}, "LicenseShortName": {"value": license},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                        "Credit": {"value": "Own work"}},
    }]}


def png(width=900, height=600):
    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).ellipse((width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill="gold")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def http(monkeypatch, pages, content=None):
    calls = []

    def get_json(client, url, **kwargs):
        calls.append(("json", url, client.allowed_hosts))
        return {"query": {"pages": copy.deepcopy(pages)}}

    def get_bytes(client, url, cap, **kwargs):
        calls.append(("bytes", url, cap, client.allowed_hosts))
        return png() if content is None else content

    monkeypatch.setattr(visuals.Http, "get_json", get_json)
    monkeypatch.setattr(visuals.Http, "get_bytes", get_bytes)
    return calls


def story_file(directory):
    story = {"topic": "A drawn circle", "cast": {"mira": {"name": "Mira", "jacket": "#123456"}}}
    (directory / "story.json").write_text(json.dumps(story), encoding="utf-8")
    return story


def test_find_lists_allowed_and_refused_licenses_with_plain_credits(monkeypatch):
    calls = http(monkeypatch, [page(author="<a>Test</a> &amp; <b>Artist</b>"),
                               page(license="CC BY-NC 4.0"), page(license="CC BY-ND 4.0"),
                               page(license="unknown"), page(license="Public domain")])
    found = commons.find("paper circle", limit=5)
    assert [item["accepted"] for item in found] == [True, False, False, False, True]
    assert found[0]["credit"] == "Test & Artist"
    assert found[0]["title"] == "File:Paper circle.png"
    assert found[0]["width"] == 900 and found[0]["height"] == 600 and found[0]["bytes"] == 12000
    assert found[0]["source_url"].startswith("https://commons.wikimedia.org/wiki/File:")
    assert found[0]["rights"] == "attribution" and found[0]["reason"] == ""
    assert all("refused" in item["reason"] for item in found[1:4])
    assert len(calls) == 1
    query = parse_qs(urlsplit(calls[0][1]).query)
    assert query["gsrsearch"] == ["paper circle"] and query["gsrnamespace"] == ["6"]
    assert query["gsrlimit"] == ["5"] and query["iiprop"] == ["url|size|mime|extmetadata"]
    assert calls[0][2] == commons.COMMONS_HOSTS


@pytest.mark.parametrize("limit", [0, 51, True, "4"])
def test_find_checks_its_limit_without_http(limit):
    with pytest.raises(StoryError, match="1 to 50"):
        commons.find("paper", limit=limit)


def test_find_marks_missing_metadata_as_refused(monkeypatch):
    http(monkeypatch, [page(author=""), page(license="")])
    found = commons.find("paper")
    assert not any(item["accepted"] for item in found)
    assert "no author" in found[0]["reason"] and found[0]["credit"] == ""
    assert "no license" in found[1]["reason"] and found[1]["license"] == ""


def test_fetch_photo_appends_real_metadata_and_preserves_story(tmp_path, monkeypatch):
    before = story_file(tmp_path)
    calls = http(monkeypatch, [page()])
    result = commons.fetch(tmp_path, "File:Paper_circle.png", "photo:mira")
    saved = json.loads((tmp_path / "story.json").read_text(encoding="utf-8"))
    entry = saved["cast"]["mira"]["photos"][0]
    assert entry == result["entry"]
    assert entry["credit"] == "Test artist" and entry["license"] == "CC BY 4.0"
    assert entry["source_url"] == "https://commons.wikimedia.org/wiki/File:Paper_circle.png"
    assert entry["path"].startswith("photos/mira-source-") and entry["path"].endswith(".png")
    assert (tmp_path / entry["path"]).read_bytes() == png()
    assert saved["topic"] == before["topic"] and saved["cast"]["mira"]["jacket"] == "#123456"
    assert result["target"] == "photo:mira" and result["width"] == 900 and result["height"] == 600
    assert parse_qs(urlsplit(calls[0][1]).query)["titles"] == ["File:Paper circle.png"]
    assert calls[1][2] == visuals.IMG_CAP and calls[1][3] == commons.COMMONS_HOSTS
    assert not list(tmp_path.glob(".story-*.tmp"))


@pytest.mark.parametrize("reference", ["https://commons.wikimedia.org/wiki/File:Paper_circle.png",
                                       "https://commons.wikimedia.org/w/index.php?title=File%3APaper_circle.png",
                                       "Paper circle.png"])
def test_fetch_image_writes_top_level_entry(tmp_path, monkeypatch, reference):
    story_file(tmp_path)
    calls = http(monkeypatch, [page()])
    result = commons.fetch(tmp_path, reference, "image:circle")
    saved = json.loads((tmp_path / "story.json").read_text(encoding="utf-8"))
    assert saved["images"]["circle"] == result["entry"]
    assert result["entry"]["path"].startswith("images/circle-source-")
    assert "photos" not in saved["cast"]["mira"]
    assert parse_qs(urlsplit(calls[0][1]).query)["titles"] == ["File:Paper circle.png"]


@pytest.mark.parametrize("author", ["", " ", "<span></span>", "unknown", "Unknown author"])
def test_fetch_refuses_missing_author_even_when_credit_says_own_work(tmp_path, monkeypatch, author):
    story_file(tmp_path)
    before = (tmp_path / "story.json").read_bytes()
    calls = http(monkeypatch, [page(author=author)])
    with pytest.raises(StoryError, match="no author"):
        commons.fetch(tmp_path, "File:Paper circle.png", "photo:mira")
    assert (tmp_path / "story.json").read_bytes() == before
    assert len(calls) == 1 and not (tmp_path / "photos").exists()


@pytest.mark.parametrize("license", ["", "unknown", "CC BY-NC 4.0", "CC BY-ND 4.0"])
def test_fetch_refuses_missing_or_forbidden_license(tmp_path, monkeypatch, license):
    story_file(tmp_path)
    calls = http(monkeypatch, [page(license=license)])
    with pytest.raises(StoryError, match="Refused"):
        commons.fetch(tmp_path, "File:Paper circle.png", "image:circle")
    assert len(calls) == 1 and not (tmp_path / "images").exists()


def test_fetch_respects_restricted_license_url(tmp_path, monkeypatch):
    story_file(tmp_path)
    item = page()
    item["imageinfo"][0]["extmetadata"]["LicenseUrl"]["value"] = "https://creativecommons.org/licenses/by-nc/4.0/"
    calls = http(monkeypatch, [item])
    with pytest.raises(StoryError, match="NC, ND"):
        commons.fetch(tmp_path, "File:Paper circle.png", "image:circle")
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["https://example.org/File:Circle.png", "file:///tmp/Circle.png",
                                 "https://commons.wikimedia.org.example.org/wiki/File:Circle.png",
                                 "https://name@commons.wikimedia.org/wiki/File:Circle.png",
                                 "https://commons.wikimedia.org:8080/wiki/File:Circle.png",
                                 "https://upload.wikimedia.org/File:Circle.png"])
def test_fetch_refuses_non_commons_page_urls_before_http(tmp_path, url):
    with pytest.raises(StoryError, match="Only Wikimedia Commons"):
        commons.fetch(tmp_path, url, "image:circle")


@pytest.mark.parametrize("field", ["url", "descriptionurl"])
def test_fetch_refuses_non_commons_metadata_urls(tmp_path, monkeypatch, field):
    story_file(tmp_path)
    item = page()
    item["imageinfo"][0][field] = "https://example.org/image.png"
    calls = http(monkeypatch, [item])
    with pytest.raises(StoryError, match="outside Commons"):
        commons.fetch(tmp_path, "File:Paper circle.png", "image:circle")
    assert len(calls) == 1


@pytest.mark.parametrize("target", ["photo:nope", "image:../escape", "image:UPPER", "other:circle"])
def test_fetch_checks_target_before_http(tmp_path, target):
    story_file(tmp_path)
    with pytest.raises(StoryError):
        commons.fetch(tmp_path, "File:Paper circle.png", target)


def test_fetch_keeps_existing_image_entry(tmp_path):
    story = story_file(tmp_path)
    story["images"] = {"circle": {"cut": "sticker", "box": [1, 2, 30, 40]}}
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    with pytest.raises(StoryError, match="already exists"):
        commons.fetch(tmp_path, "File:Paper circle.png", "image:circle")
    assert json.loads((tmp_path / "story.json").read_text(encoding="utf-8")) == story


@pytest.mark.parametrize("content, message", [(b"not an image", "unreadable"), (png(80, 60), "too small")])
def test_fetch_validates_downloaded_bytes(tmp_path, monkeypatch, content, message):
    story_file(tmp_path)
    http(monkeypatch, [page()], content)
    with pytest.raises(StoryError, match=message):
        commons.fetch(tmp_path, "File:Paper circle.png", "image:circle")
    assert not (tmp_path / "images").exists()


def test_fetch_does_not_replace_story_edited_during_download(tmp_path, monkeypatch):
    story_file(tmp_path)
    http(monkeypatch, [page()])
    updated = {"topic": "Saved while downloading"}

    def get_bytes(*args, **kwargs):
        (tmp_path / "story.json").write_text(json.dumps(updated), encoding="utf-8")
        return png()

    monkeypatch.setattr(visuals.Http, "get_bytes", get_bytes)
    with pytest.raises(StoryError, match="changed during"):
        commons.fetch(tmp_path, "File:Paper circle.png", "image:circle")
    assert json.loads((tmp_path / "story.json").read_text(encoding="utf-8")) == updated
    assert not list((tmp_path / "images").glob("*.png"))


def test_factory_http_allowlist_keeps_public_host_checks(monkeypatch):
    checked = []
    monkeypatch.setattr(visuals, "_check_host", checked.append)
    client = visuals.Http(allowed_hosts=commons.COMMONS_HOSTS)
    assert client._validate("https://upload.wikimedia.org/picture.png") == "https://upload.wikimedia.org/picture.png"
    assert checked == ["https://upload.wikimedia.org/picture.png"]
    with pytest.raises(ValueError, match="allowed hosts"):
        client._validate("https://example.org/picture.png")
    assert len(checked) == 1


def test_factory_http_allowlist_reaches_redirect_validation(monkeypatch):
    monkeypatch.setattr(visuals, "_check_host", lambda url: None)
    client = visuals.Http(min_interval=0, allowed_hosts=commons.COMMONS_HOSTS)

    def open_url(url, purpose, **kwargs):
        assert kwargs["validate"](url) == url
        handler = network._Redirect(SimpleNamespace(check=lambda purpose: None),
                                    {"purpose": purpose}, kwargs["validate"])
        stream = io.BytesIO()
        with pytest.raises(ValueError, match="allowed hosts"):
            handler.redirect_request(Request(url), stream, 302, "Found", {}, "https://example.org/picture.png")
        assert stream.closed
        return "mocked response"

    monkeypatch.setattr(client.network, "open", open_url)
    assert client.open("https://commons.wikimedia.org/w/api.php") == "mocked response"


def test_factory_http_without_allowlist_still_accepts_other_public_hosts(monkeypatch):
    checked = []
    monkeypatch.setattr(visuals, "_check_host", checked.append)
    assert visuals.Http()._validate("https://example.org/image.png") == "https://example.org/image.png"
    assert checked == ["https://example.org/image.png"]
