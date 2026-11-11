"""Place names in visual ranking, pick sheets and unanswered rows."""
from __future__ import annotations

import socket
from copy import deepcopy

import pytest
from PIL import Image, ImageDraw

from myzing.factory import judge, pick, pipeline, visuals


TITLES = [
    ("Louisiana State Police Patrol Car 2025", "louisiana"),
    ("MF-07-84(Macau Police Patrol Car) 25-04-2019", "macau"),
    ("MD-08-61(Macau Police Patrol Car) 25-04-2019", "macau"),
    ("Kyiv patrol police car at Institutska street", "kyiv"),
    ("Royal Thai Police, Toyota Hilux patrol car.", "thailand"),
]
WORDS = "The story mentions Ferguson, Missouri."
REJECT = ("- names or shows a particular place, police force, team or company the speaker isn't talking about "
          "(lettering on a car, a sign or a jersey counts);")


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
def request_row():
    return {"id": "v2", "query": "police patrol car", "kind": "photo",
            "context": "The officer put the arrested woman into the patrol car and drove her to the station"}


def candidate(title, **kwargs):
    return visuals.cand("commons", "image", title=title, license="CC0", **kwargs)


@pytest.mark.parametrize("title,place", TITLES)
def test_rank_flags_the_five_patrol_cars(request_row, title, place):
    q = visuals.Query(request_row, "photo", "context", words=WORDS)
    foreign, neutral = candidate(title), candidate("Patrol car")
    log = {"rejected": []}
    assert visuals.rank([foreign, neutral], q, log) == [neutral, foreign]
    assert foreign["places_off"] == [place]
    assert foreign["score"] < neutral["score"]
    assert log["rejected"] == []


@pytest.mark.parametrize("extra", [{}, {"base": 1.2}, {"stock": True}])
@pytest.mark.parametrize("field", ["title", "desc", "description"])
def test_rank_penalizes_places_in_metadata(request_row, field, extra):
    q = visuals.Query(request_row, "photo", "context")
    foreign = candidate("Police patrol car", **extra)
    foreign[field] = "Louisiana police patrol car"
    neutral = candidate("Patrol car")
    assert visuals.rank([foreign, neutral], q, {"rejected": []}) == [neutral, foreign]
    assert foreign["places_off"] == ["louisiana"]
    assert foreign["score"] < neutral["score"]


@pytest.mark.parametrize("field", ["query", "context", "entity", "words"])
def test_rank_keeps_a_place_named_in_the_request_or_clip(request_row, field):
    if field != "words":
        request_row[field] = request_row.get(field, "") + " Missouri"
    q = visuals.Query(request_row, "photo", "context", **({"words": WORDS} if field == "words" else {}))
    c = candidate("Missouri State Highway Patrol car")
    log = {"rejected": []}
    assert visuals.rank([c], q, log) == [c]
    assert not c.get("places_off")
    assert log["rejected"] == []


@pytest.mark.parametrize("text,names", [
    ("Essex police", {"essex"}),
    ("Georgia patrol car", {"georgia"}),
    ("NEW YORK police car", {"new york"}),
    ("Hong_Kong police car", {"hong kong"}),
    ("West Virginia road", {"west virginia"}),
    ("New Mexico road", {"new mexico"}),
    ("Kyiv Ukrainian police", {"kyiv", "ukraine"}),
    ("Kiev patrol car", {"kyiv"}),
    ("Royal Thai Police", {"thailand"}),
    ("Macao patrol car", {"macau"}),
    ("New Yorkshire photothailand Macauley", set()),
])
def test_place_names_use_whole_words_and_aliases(text, names):
    assert set(visuals.places(text)) == names


@pytest.mark.parametrize("query,title", [("Thailand police", "Royal Thai Police"),
                                         ("Ukrainian patrol car", "Ukraine patrol car"),
                                         ("Essex police", "Essex police"),
                                         ("Georgia police", "Georgia police")])
def test_rank_matches_place_aliases(query, title):
    c = candidate(title)
    log = {"rejected": []}
    assert visuals.rank([c], visuals.Query({"query": query}, "photo", "context"), log) == [c]
    assert not c.get("places_off") and log["rejected"] == []


@pytest.mark.parametrize("extra", [{}, {"base": 1.2}, {"stock": True}])
@pytest.mark.parametrize("query,title", [("Ferguson Missouri street", "Ferguson Louisiana street"),
                                         ("Thailand patrol car", "Ukrainian patrol car"),
                                         ("New York street", "New Mexico street")])
def test_named_place_request_rejects_another_place(query, title, extra):
    c = candidate(title, **extra)
    q = visuals.Query({"query": query}, "photo", "context")
    log = {"rejected": []}
    assert visuals.rank([c], q, log) == []
    assert log["rejected"] == [{"title": title, "source": "commons", "why": "names another place"}]


def test_clip_words_do_not_override_a_named_place_request():
    q = visuals.Query({"query": "Ferguson Missouri street"}, "photo", "context", words="Louisiana")
    log = {"rejected": []}
    assert visuals.rank([candidate("Ferguson Louisiana street")], q, log) == []
    assert log["rejected"][0]["why"] == "names another place"


def test_finalization_keeps_the_penalty_and_description_flag(tmp_path, request_row):
    q = visuals.Query(request_row, "photo", "context")
    foreign = candidate("Police patrol car", desc="Louisiana", path=tmp_path / "foreign.jpg")
    neutral = candidate("Patrol car", path=tmp_path / "neutral.jpg")
    ranked = visuals.rank([foreign, neutral], q, {"rejected": []})
    found = visuals.finalize(ranked, q, tmp_path, 5)
    assert [c["title"] for c in found] == ["Patrol car", "Police patrol car"]
    assert found[1]["places_off"] == ["louisiana"]
    assert found[0]["score"] > found[1]["score"]
    assert pick.chosen(tmp_path, [request_row], {"v2": [found[1]]}, {}) == {}


@pytest.mark.parametrize("kind", ["photo", "video", "screenshot"])
def test_pipeline_passes_clip_words_through_search_and_fallbacks(tmp_path, monkeypatch, request_row, kind):
    request_row["kind"] = kind
    d = tmp_path / "clip01"
    pipeline._write(tmp_path / "factory.json", {"offline": True})
    pipeline._write(d / "cams.json", {})
    pipeline._write(d / "post.json", {})
    pipeline._write(d / "words.json", {"duration": 10, "words": [{"w": WORDS, "os": 0, "oe": 10}]})
    ask = judge.Judge(tmp_path)
    ask.save("clip01-plan", {"hook": "A body camera", "shots": [{"from": 0, "layout": "solo"}],
                             "visual_requests": [request_row]})
    monkeypatch.setattr(visuals, "gather", lambda *args: [candidate(TITLES[0][0], base=1.2),
                                                        candidate("Missouri State Highway Patrol car", base=1.2)])
    download = visuals.download_ranked
    monkeypatch.setattr(visuals, "download_ranked",
                        lambda ctx, ranked, q, folder: [] if q.wants_video else download(ctx, ranked, q, folder))

    def fetch(ctx, c, folder, hashes):
        c["path"] = folder / f"{c['title']}.jpg"
        Image.new("RGB", (1600, 900)).save(c["path"])
        c.update(width=1600, height=900)
    monkeypatch.setattr(visuals, "fetch_candidate", fetch)
    assert pipeline._clip(tmp_path, 1, {"hook": "A body camera"}, ask, tmp_path / "episode.mp4",
                          {"mode": "context"}, [], lambda m: None) == ["clip01-pick"]
    manifest = pipeline._read(d / "visuals" / "manifest.json")
    good, bad = manifest["v2"]
    assert good["title"] == "Missouri State Highway Patrol car" and not good.get("places_off")
    assert bad["places_off"] == ["louisiana"] and bad["score"] < good["score"]
    assert pick.chosen(d / "visuals", [request_row], manifest, {})["v2"]["path"] == str(d / "visuals" / good["path"])


def test_sheet_title_label_is_short_and_one_line():
    assert pick.title_label({"title": "  Louisiana\n State  Police\tPatrol Car 2025 "}) == TITLES[0][0]
    assert pick.title_label({"title": "x" * 80}) == "x" * 40
    assert pick.title_label({}) == pick.title_label({"title": None}) == ""


def test_sheet_draws_titles_below_tiles_without_overlapping(tmp_path, monkeypatch):
    labels = []
    draw_text = ImageDraw.ImageDraw.text

    def text(self, xy, value, *args, **kwargs):
        labels.append((value, self.textbbox(xy, value, font=kwargs["font"])))
        return draw_text(self, xy, value, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    monkeypatch.setattr(pick, "_thumb", lambda path: Image.new("RGB", (pick.TW, pick.TH)))
    titles = [TITLES[0][0], "W" * 40]
    manifest = {rid: [candidate(t, path=f"{i}.jpg") for i, t in enumerate(titles)] for rid in ("v1", "v2")}
    out = pick.sheet(tmp_path, [{"id": "v1"}, {"id": "v2"}], manifest)
    with Image.open(out) as im:
        for row in range(2):
            y = 10 + row * (pick.TH + pick.BAND + 16)
            drawn = [(s, box) for s, box in labels if y + pick.BAND - 26 + pick.TH <= box[1] < y + pick.TH + pick.BAND + 16]
            assert len(drawn) == 2 and drawn[0][0] == TITLES[0][0]
            for i, (s, box) in enumerate(drawn):
                assert "\n" not in s and len(s) <= 40
                assert box[2] <= 220 + i * (pick.TW + 12) + pick.TW
                assert box[3] < min(im.height, y + pick.TH + pick.BAND + 16)


@pytest.mark.parametrize("mode", ["context", "documentary", "fun"])
def test_prompt_rejects_places_and_affiliations(tmp_path, mode):
    assert REJECT in pick.prompt(tmp_path / "sheet.jpg", mode, None)


@pytest.mark.parametrize("has_neutral", [False, True])
def test_unanswered_row_skips_candidates_with_places_off(tmp_path, request_row, has_neutral):
    cands = [candidate(TITLES[0][0], path="foreign.jpg", places_off=["louisiana"])]
    if has_neutral:
        cands.append(candidate("Patrol car", path="neutral.jpg"))
    manifest = {"v2": cands}
    before = deepcopy(manifest)
    found = pick.chosen(tmp_path, [request_row], manifest, {})
    assert manifest == before
    assert (found["v2"]["path"] == str(tmp_path / "neutral.jpg")) if has_neutral else found == {}


@pytest.mark.parametrize("idx", [0, None, -1, 2])
def test_answered_rows_keep_the_judges_choice(tmp_path, request_row, idx):
    c = candidate(TITLES[0][0], path="foreign.jpg", places_off=["louisiana"])
    found = pick.chosen(tmp_path, [request_row], {"v2": [c]}, {"v2": {"pick": idx}})
    assert (found["v2"]["path"] == str(tmp_path / "foreign.jpg")) if idx == 0 else found == {}


@pytest.mark.parametrize("title", ["Roast turkey on a Thanksgiving table", "Michael Jordan dunks for the Bulls"])
def test_everyday_words_are_not_places(title):
    assert visuals.places(title) == {}


def test_america_counts_as_the_united_states():
    assert visuals.places("Made in America") == visuals.places("American flag")


def test_a_named_place_request_keeps_a_candidate_that_names_it_too():
    q = visuals.Query({"id": "v5", "query": "Ferguson Missouri street", "kind": "photo"}, "photo", "context")
    both, other = candidate("Missouri and Illinois border at St. Louis"), candidate("Main Street, Illinois")
    log = {"rejected": []}
    assert visuals.rank([both, other], q, log) == [both]
    assert [r["why"] for r in log["rejected"]] == ["names another place"]
