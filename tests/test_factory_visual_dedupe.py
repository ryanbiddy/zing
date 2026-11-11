"""Use each picture once per clip without changing the judge's other choices."""
from __future__ import annotations

import io
import json
import socket
from copy import deepcopy

import pytest
from PIL import Image, ImageDraw

from myzing.factory import pick, visuals


RULE = "Never pick the same picture for two rows because the same picture can appear in more than one row."


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
def requests():
    return [{"id": rid, "query": "body camera", "kind": "photo"} for rid in ("v1", "v2", "v3")]


def candidate(path, **kwargs):
    return visuals.cand("commons", "image", path=path, title="Body camera", license="CC0", **kwargs)


@pytest.fixture
def manifest():
    return {"v1": [candidate("camera.jpg")],
            "v2": [candidate("camera.jpg"), candidate("other.jpg")]}


def test_chosen_drops_a_duplicate_pick_without_substituting(tmp_path, requests, manifest):
    picks = {rid: {"pick": 0} for rid in manifest}
    before = deepcopy((manifest, picks, requests))
    found = pick.chosen(tmp_path, requests, manifest, picks)
    assert list(found) == ["v1"]
    assert found["v1"]["path"] == str(tmp_path / "camera.jpg")
    assert (manifest, picks, requests) == before


def test_chosen_uses_request_order(tmp_path, requests, manifest):
    found = pick.chosen(tmp_path, list(reversed(requests)), manifest,
                        {rid: {"pick": 0} for rid in manifest})
    assert list(found) == ["v2"]


def test_chosen_resolves_paths_before_comparing(tmp_path, requests, manifest):
    manifest["v2"][0]["path"] = str(tmp_path / "camera.jpg")
    found = pick.chosen(tmp_path, requests, manifest, {rid: {"pick": 0} for rid in manifest})
    assert list(found) == ["v1"]


@pytest.mark.parametrize("key,value", [
    ("file_url", "https://example.org/camera.jpg"),
    ("source_url", "https://example.org/camera"),
    ("source_id", "camera-123"),
    ("sha256", "a" * 64),
    ("hash", "b" * 64),
    ("phash", "0123456789abcdef"),
    ("dhash", 0),
])
def test_chosen_dedupes_identity_across_paths(tmp_path, requests, manifest, key, value):
    for rid, cands in manifest.items():
        cands[0].update(path=f"{rid}/camera.jpg", **{key: value})
    found = pick.chosen(tmp_path, requests, manifest, {rid: {"pick": 0} for rid in manifest})
    assert list(found) == ["v1"]


@pytest.mark.parametrize("answered", [False, True])
@pytest.mark.parametrize("has_unused", [False, True])
def test_unanswered_row_uses_the_next_unused_unflagged_candidate(tmp_path, requests, manifest, answered, has_unused):
    manifest["v2"] = [manifest["v2"][0], candidate("unsafe.jpg", desc="Nude portrait"),
                      candidate("foreign.jpg", places_off=["louisiana"])]
    if has_unused:
        manifest["v2"].append(candidate("unused.jpg"))
    before = deepcopy(manifest)
    found = pick.chosen(tmp_path, requests, manifest, {"v1": {"pick": 0}} if answered else {})
    expected = {"v1": str(tmp_path / "camera.jpg")}
    if has_unused:
        expected["v2"] = str(tmp_path / "unused.jpg")
    assert {rid: c["path"] for rid, c in found.items()} == expected
    assert manifest == before


def test_chosen_keeps_three_different_pictures(tmp_path, requests):
    manifest = {r["id"]: [candidate(f"{r['id']}.jpg", file_url=f"https://example.org/{r['id']}.jpg",
                                   source_url="https://example.org/gallery")]
                for r in requests}
    found = pick.chosen(tmp_path, requests, manifest, {rid: {"pick": 0} for rid in manifest})
    assert {rid: c["path"] for rid, c in found.items()} == {rid: str(tmp_path / f"{rid}.jpg") for rid in manifest}


def test_chosen_does_not_reserve_an_unselected_picture(tmp_path, requests, manifest):
    manifest["v1"].append(candidate("first.jpg"))
    found = pick.chosen(tmp_path, requests, manifest, {"v1": {"pick": 1}, "v2": {"pick": 0}})
    assert {rid: c["path"] for rid, c in found.items()} == {
        "v1": str(tmp_path / "first.jpg"), "v2": str(tmp_path / "camera.jpg")}


def test_sheet_still_draws_a_picture_in_both_rows(tmp_path, monkeypatch, requests, manifest):
    seen = []

    def thumb(path):
        seen.append(path)
        return Image.new("RGB", (pick.TW, pick.TH))
    monkeypatch.setattr(pick, "_thumb", thumb)
    assert pick.sheet(tmp_path, requests, manifest).is_file()
    assert seen == [tmp_path / name for name in ("camera.jpg", "camera.jpg", "other.jpg")]


@pytest.mark.parametrize("mode", ["context", "documentary", "fun"])
@pytest.mark.parametrize("reason", [None, "war"])
def test_prompt_rejects_reusing_a_picture(tmp_path, mode, reason):
    assert RULE in pick.prompt(tmp_path / "sheet.jpg", mode, reason).splitlines()


@pytest.mark.parametrize("source", ["commons", "screenshot", "local"])
def test_fetched_picture_keeps_its_hash_in_the_manifest(tmp_path, monkeypatch, requests, source):
    image = Image.new("RGB", (1000, 600), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 500, 300), fill="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()
    ctx = visuals.Ctx(tmp_path)
    monkeypatch.setattr(ctx.http, "get_bytes", lambda *args: data)
    manifest = {}
    for r in requests[:2]:
        folder = tmp_path / r["id"]
        folder.mkdir()
        c = visuals.cand(source, "image", title="Body camera", license="CC0", score=1,
                         file_url=f"https://example.org/{r['id']}.png")
        if source in ("screenshot", "local"):
            path = tmp_path / f"{r['id']}.png"
            path.write_bytes(data)
            c["local_path" if source == "local" else "path"] = path
        visuals.fetch_candidate(ctx, c, folder, [])
        manifest[r["id"]] = visuals.finalize([c], visuals.Query(r, "photo", "context"), folder, 5)
    manifest = json.loads(json.dumps(manifest))
    assert [manifest[rid][0].get("dhash") for rid in manifest] == [visuals.dhash(data)] * 2
    found = pick.chosen(tmp_path, requests, manifest, {rid: {"pick": 0} for rid in manifest})
    assert list(found) == ["v1"]
