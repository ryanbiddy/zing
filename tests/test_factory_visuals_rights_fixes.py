"""Visual rights, credits and ranking without downloads or model calls."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from myzing.channels import gate, registry
from myzing.factory import judge, pick, pipeline, visuals


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(visuals.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(visuals, "get_key", lambda name: None)


class Http:
    def __init__(self, data):
        self.data, self.urls = data, []

    def get_json(self, url, **kwargs):
        self.urls.append(url)
        return self.data


@pytest.mark.parametrize("license", [
    "CC BY-NC 4.0", "CC BY-ND 4.0", "CC BY-NC-SA 2.0", "CC BY-NC-ND 4.0",
    "Attribution-NonCommercial", "Attribution-Non-Commercial", "Attribution-NoDerivatives",
    "Attribution No Derivatives", "cc by-nc 4.0", "ATTRIBUTION-NODERIVATIVES",
    "https://creativecommons.org/licenses/by-nd/4.0/",
])
def test_restricted_licenses_are_unknown(license):
    c = visuals.cand("commons", "image", title="Moonrise", license=license)
    assert visuals.rights_for(c)[0] == "unknown"


@pytest.mark.parametrize("license", ["CC BY 4.0", "CC BY-SA 4.0", "Public domain", ""])
@pytest.mark.parametrize("term", ["by-nc", "by-nd", "by-nc-sa", "BY-NC-ND"])
def test_restricted_license_url_overrides_the_label(license, term):
    c = visuals.cand("openverse", "image", title="Moonrise", license=license,
                     license_url=f"https://creativecommons.org/licenses/{term}/4.0/")
    assert visuals.rights_for(c)[0] == "unknown"


@pytest.mark.parametrize("license", ["CC BY 4.0", "CC BY-SA 4.0"])
def test_unrestricted_attribution_stays_attribution(license):
    c = visuals.cand("commons", "image", title="Moonrise", license=license, creator="Jane Doe")
    rights, credit = visuals.rights_for(c)
    assert rights == "attribution" and license in credit


def test_openverse_requests_commercial_use_and_modification():
    http = Http({"results": [{"title": "Moonrise", "url": "https://example.org/moon.jpg",
                              "width": 1920, "height": 1080, "license": "by-sa", "license_version": "4.0"}]})
    q = visuals.Query({"query": "moonrise"}, "photo", "context")
    found = visuals.search_openverse(SimpleNamespace(http=http), q)
    query = parse_qs(urlsplit(http.urls[0]).query)
    assert query["license_type"] == ["commercial,modification"]
    assert len(found) == 1 and visuals.rights_for(found[0])[0] == "attribution"


@pytest.mark.parametrize("field", ["desc", "title", "creator"])
@pytest.mark.parametrize("marker", ["© Jane Doe, used with permission", "© Jane Doe", "Copyright Jane Doe",
                                    "ALL RIGHTS RESERVED", "Used With Permission"])
def test_nasa_third_party_markers_are_unknown(field, marker):
    c = visuals.cand("nasa", "image", title="Moonrise", license=visuals.NASA_LICENSE, creator="NASA")
    c[field] = "Moonrise " * 20 + marker
    assert visuals.rights_for(c)[0] == "unknown"


def test_nasa_search_keeps_the_description_for_the_rights_check():
    http = Http({"collection": {"items": [
        {"data": [{"title": "Moonrise", "description": "© Jane Doe, used with permission"}]},
        {"data": [{"title": "Moon landing", "description": "Astronauts on the Moon."}]},
    ]}})
    q = visuals.Query({"query": "moon"}, "photo", "context")
    found = visuals.search_nasa(SimpleNamespace(http=http), q, "image")
    assert [visuals.rights_for(c)[0] for c in found] == ["unknown", "cleared"]


@pytest.mark.parametrize("saved", [False, True])
def test_long_attribution_credit_keeps_the_whole_license(tmp_path, saved):
    c = visuals.cand("commons", "image", title="Moonrise " * 25, creator="Jane Doe " * 25,
                     license="CC BY-SA 4.0", path="moon.jpg", rights="attribution")
    if saved:
        c["rights"], c["credit_text"] = visuals.rights_for(c)
    credit = pick.chosen(tmp_path, [], {"v1": [c]}, {})["v1"]["credit"]
    assert len(credit) <= 80 and credit.endswith(" · CC BY-SA 4.0")
    assert "Jane Doe" in credit


def test_a_200_character_credit_keeps_its_license(tmp_path):
    license = "CC BY 4.0"
    credit = "A" * (200 - len(license) - 3) + " · " + license
    c = {"path": "moon.jpg", "rights": "attribution", "creator": "Jane Doe",
         "license": license, "credit_text": credit}
    found = pick.chosen(tmp_path, [], {"v1": [c]}, {})["v1"]
    assert len(found["credit"]) <= 80 and found["credit"].endswith(" · " + license)


@pytest.mark.parametrize("rights", ["cleared", "editorial", "unknown"])
def test_other_credits_keep_the_existing_cut(tmp_path, rights):
    c = {"path": "moon.jpg", "rights": rights, "credit_text": "A" * 200, "license": "CC0 1.0"}
    assert pick.chosen(tmp_path, [], {"v1": [c]}, {})["v1"]["credit"] == "A" * 80


def test_short_attribution_credit_stays_unchanged(tmp_path):
    c = visuals.cand("commons", "image", title="Moonrise", creator="Jane Doe", license="CC BY 4.0", path="moon.jpg")
    c["rights"], c["credit_text"] = visuals.rights_for(c)
    assert pick.chosen(tmp_path, [], {"v1": [c]}, {})["v1"]["credit"] == c["credit_text"]


@pytest.mark.parametrize("size", [{"width": "1920", "height": 1080}, {"width": 1920, "height": "1080"},
                                  {"width": None, "height": 1080}, {}, {"width": [], "height": 1080}])
def test_bad_dimensions_do_not_stop_ranking(size):
    cands = [visuals.cand("pexels", "image", title="Moonrise", stock=True, **size),
             visuals.cand("pexels", "image", title="Moon landing", stock=True, width=1920, height=1080)]
    q = visuals.Query({"query": "moon"}, "photo", "context")
    found = visuals.rank(cands, q, {"rejected": []})
    assert [c["title"] for c in found] == ["Moon landing", "Moonrise"]
    assert all(isinstance(c["score"], float) for c in found)


def test_public_search_and_channel_gate_reject_restricted_visuals(tmp_path, monkeypatch):
    cands = [visuals.cand("commons", "image", title="Moonrise", license="CC BY-NC 4.0", base=1.0),
             visuals.cand("nasa", "image", title="Moon landing", license=visuals.NASA_LICENSE,
                          desc="© Jane Doe, used with permission", base=1.0),
             visuals.cand("commons", "image", title="Moon", license="CC BY-SA 4.0", base=1.0)]
    q = visuals.Query({"query": "moon"}, "photo", "context")
    ctx = visuals.Ctx(tmp_path, public=True)
    ctx.log = {"rejected": []}
    ranked = visuals.rank(cands, q, ctx.log)
    fetched = []
    monkeypatch.setattr(visuals, "fetch_candidate", lambda ctx, c, folder, hashes: fetched.append(c["title"]))
    assert visuals.download_ranked(ctx, ranked, q, tmp_path) == [cands[2]]
    assert fetched == ["Moon"]

    monkeypatch.setattr(registry, "paused", lambda slug: False)
    channel = {"slug": "moon", "visuals": "cleared", "approval": {"policy": "manual"}}
    d = tmp_path / "clip01"
    pipeline._write(tmp_path / "factory.json", {"rights": "own"})
    pipeline._write(tmp_path / "ratings.json", {"clip01": {"v": "post"}})
    pipeline._write(d / "context.json", {"flags": []})
    pipeline._write(d / "post.json", {})
    (d / "clip.mp4").write_bytes(b"video")
    for c in cands:
        pipeline._write(d / "visuals" / "manifest.json", {"v1": [c]})
        result = gate.check(tmp_path, "clip01", channel)
        assert result["publishable"] is (c is cands[2])
        if c is not cands[2]:
            assert any("Picked visuals" in b for b in result["blockers"])
