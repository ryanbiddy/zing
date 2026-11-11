"""Visual safety for new searches and saved manifests."""
from __future__ import annotations

import socket
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image, ImageDraw

from myzing.factory import pick, visuals


TITLE = "Marlboro Man Nude Photograph by Victor Arimondi-NYC-1980"
REJECT = "- shows nudity, sexual content, or anything not safe for a general audience;"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(visuals.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(visuals.urllib.request.OpenerDirector, "open", refuse)
    monkeypatch.setattr(visuals, "get_key", lambda name: None)


@pytest.fixture
def manifest():
    return {"v5": [visuals.cand("commons", "image", title=title, path=f"v5/{i}.jpg",
                                license="CC BY-SA 4.0", creator="Example photographer", rights="attribution")
                   for i, title in enumerate((TITLE, "Marlboro Man billboard", "Nude portrait", "Cowboy billboard"))]}


@pytest.mark.parametrize("extra", [{}, {"base": 1.2}, {"stock": True}])
def test_rank_rejects_the_marlboro_man_photograph_before_scoring(extra):
    c = visuals.cand("commons", "image", title=TITLE, license="CC BY-SA 4.0", **extra)
    q = visuals.Query({"query": "Marlboro Man"}, "photo", "context")
    log = {"rejected": []}
    assert visuals.rank([c], q, log) == []
    assert log["rejected"] == [{"title": TITLE, "source": "commons", "why": "not safe for work"}]
    assert "matched_terms" not in c and "score" not in c


@pytest.mark.parametrize("field", ["title", "desc", "credit_text"])
@pytest.mark.parametrize("word", "nude nudes nudity naked topless nsfw erotic erotica porn porno pornography "
                         "pornographic sex sexual sexy fetish bdsm bondage lingerie genitals genitalia penis "
                         "vagina nipple nipples striptease stripper orgy".split())
def test_rank_rejects_content_words_in_metadata(field, word):
    c = visuals.cand("commons", "image", title="Billboard", license="CC BY 4.0")
    c[field] = f"Billboard ({word.upper()}) photograph"
    q = visuals.Query({"query": "Billboard"}, "photo", "context")
    log = {"rejected": []}
    assert visuals.rank([c], q, log) == []
    assert log["rejected"][0]["why"] == "not safe for work"


@pytest.mark.parametrize("field", ["description", "credit", "attribution", "creator"])
def test_rank_checks_other_description_and_credit_fields(field):
    c = visuals.cand("commons", "image", title="Billboard", **{field: "A naked portrait"})
    q = visuals.Query({"query": "Billboard"}, "photo", "context")
    log = {"rejected": []}
    assert visuals.rank([c], q, log) == []
    assert log["rejected"][0]["why"] == "not safe for work"


@pytest.mark.parametrize("title", ["Essex", "Sussex", "Middlesex"])
def test_rank_keeps_county_names(title):
    c = visuals.cand("commons", "image", title=f"{title} countryside", license="CC0")
    q = visuals.Query({"query": title}, "photo", "context")
    log = {"rejected": []}
    assert visuals.rank([c], q, log) == [c]
    assert log["rejected"] == []


def test_chosen_default_skips_flagged_candidates(tmp_path, manifest):
    before = deepcopy(manifest)
    found = pick.chosen(tmp_path, [], manifest, {})
    assert found["v5"]["path"] == str(tmp_path / "v5/1.jpg")
    assert manifest == before


@pytest.mark.parametrize("idx", [0, 2])
def test_chosen_shows_nothing_for_a_flagged_pick(tmp_path, manifest, idx):
    before = deepcopy(manifest)
    assert pick.chosen(tmp_path, [], manifest, {"v5": {"pick": idx}}) == {}
    assert manifest == before


@pytest.mark.parametrize("picks", [{}, {"v5": {"pick": 0}}])
def test_chosen_omits_rows_without_safe_candidates(tmp_path, manifest, picks):
    manifest["v5"] = [manifest["v5"][0], manifest["v5"][2]]
    assert pick.chosen(tmp_path, [], manifest, picks) == {}


@pytest.mark.parametrize("idx", [None, -1, 4])
def test_chosen_keeps_none_and_invalid_picks_empty(tmp_path, manifest, idx):
    assert pick.chosen(tmp_path, [], manifest, {"v5": {"pick": idx}}) == {}


def test_chosen_keeps_the_original_index_of_a_safe_pick(tmp_path, manifest):
    found = pick.chosen(tmp_path, [], manifest, pick.picks_from({"v5": {"pick": 4}}))
    assert found["v5"]["path"] == str(tmp_path / "v5/3.jpg")


@pytest.mark.parametrize("kind", ["pick", "contact"])
def test_sheets_hide_flagged_candidates_and_keep_tile_numbers(tmp_path, monkeypatch, manifest, kind):
    seen, labels = [], []

    def thumb(path, *args):
        seen.append(path)
        return Image.new("RGB", (pick.TW, pick.TH))

    draw_text = ImageDraw.ImageDraw.text

    def text(self, xy, value, *args, **kwargs):
        labels.append(value)
        return draw_text(self, xy, value, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    monkeypatch.setattr(pick if kind == "pick" else visuals, "_thumb", thumb)
    reqs = [{"id": "v5", "_safe": "v5", "query": "Marlboro Man", "kind": "photo"}]
    before = deepcopy(manifest)
    path = pick.sheet(tmp_path, reqs, manifest) if kind == "pick" else \
        visuals.contact_sheet(manifest, tmp_path, reqs, "context")
    assert path.is_file()
    assert seen == [tmp_path / "v5/1.jpg", tmp_path / "v5/3.jpg"]
    if kind == "pick":
        assert [s for s in labels if s.isdigit()] == ["2", "4"]
    else:
        assert [s.split()[0] for s in labels if s.startswith("#")] == ["#2", "#4"]
    assert not any("nude" in s.lower() for s in labels)
    assert manifest == before


def test_pick_sheet_omits_rows_without_safe_candidates(tmp_path, manifest):
    manifest["v5"] = [manifest["v5"][0]]
    assert pick.sheet(tmp_path, [{"id": "v5"}], manifest) is None


@pytest.mark.parametrize("cands", [None, []])
def test_empty_manifest_rows_stay_empty(tmp_path, cands):
    manifest = {"v5": cands}
    assert pick.sheet(tmp_path, [{"id": "v5"}], manifest) is None
    assert pick.chosen(tmp_path, [], manifest, {}) == {}


@pytest.mark.parametrize("mode", ["context", "documentary", "fun"])
@pytest.mark.parametrize("reason", [None, "war"])
def test_pick_prompt_rejects_content_unsafe_for_a_general_audience(tmp_path, mode, reason):
    assert REJECT in pick.prompt(tmp_path / "sheet.jpg", mode, reason)


class Http:
    def __init__(self, data):
        self.data, self.urls = data, []

    def get_json(self, url, **kwargs):
        self.urls.append(url)
        return self.data


def test_openverse_excludes_mature_results_in_the_request_and_response():
    http = Http({"results": [{"title": "Billboard", "url": f"https://example.org/{mature}.jpg",
                              "width": 1920, "height": 1080, "mature": mature}
                             for mature in (True, False)]})
    q = visuals.Query({"query": "Billboard"}, "photo", "context")
    found = visuals.search_openverse(SimpleNamespace(http=http), q)
    assert parse_qs(urlsplit(http.urls[0]).query)["mature"] == ["false"]
    assert [c["file_url"] for c in found] == ["https://example.org/False.jpg"]


@pytest.mark.parametrize("video", [False, True])
def test_pixabay_keeps_safe_search(video):
    http = Http({"hits": []})
    q = visuals.Query({"query": "Billboard"}, "photo", "context")
    assert visuals.search_pixabay(SimpleNamespace(http=http), q, video) == []
    assert parse_qs(urlsplit(http.urls[0]).query)["safesearch"] == ["true"]
