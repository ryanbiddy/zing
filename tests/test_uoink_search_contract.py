"""Zing accepts the upstream search wire fixture verbatim and rejects drift."""

import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from myzing.uoink_bridge import parse_search_response

FIXTURES = Path(__file__).parent / "fixtures" / "uoink_corpus_v1"


def provider():
    return json.loads((FIXTURES / "provider.json").read_bytes())


def search_body():
    return provider()["operations"]["search_all"]


def test_vendored_provider_bytes_match_recorded_source():
    source = json.loads((FIXTURES / "provider.source.json").read_text(encoding="utf-8"))
    assert source["source_path"] == "tests/fixtures/corpus_contract_v1/provider.json"
    assert len(source["commit"]) == 40
    assert hashlib.sha256((FIXTURES / "provider.json").read_bytes()).hexdigest() == source["sha256"]


@pytest.mark.parametrize("operation", ["search_all", "search_filtered", "search_no_matches"])
def test_upstream_search_wire_response_passes_unchanged(operation):
    body = provider()["operations"][operation]
    original = copy.deepcopy(body)
    results = [{"item_ref": "uoink://item/" + quote(item["id"], safe=""),
                "title": item["title"], "source_url": item["source_url"]}
               for item in body["data"]["items"]]
    assert parse_search_response(body) == {"ok": True, "results": results, "selected": None}
    assert body == original


@pytest.mark.parametrize("path", [(), ("data",), ("data", "page"),
                                 ("data", "items", 0), ("data", "items", 0, "credit"),
                                 ("data", "items", 0, "facets"), ("data", "items", 0, "preview")])
@pytest.mark.parametrize("extra", ["unknown", "citations", "search_mode", "requested_mode", "fallback_reason"])
def test_search_rejects_extra_keys_at_every_wire_level(path, extra):
    body = search_body()
    target = body
    for key in path:
        target = target[key]
    target[extra] = None
    assert parse_search_response(body)["code"] == "contract_mismatch"


@pytest.mark.parametrize("path,value", [
    (("ok",), 1), (("version",), True), (("operation",), "get"),
    (("data", "page", "state"), "invented"), (("data", "page", "total"), True),
    (("data", "page", "offset"), -1), (("data", "items", 0, "id"), ""),
    (("data", "items", 0, "title"), None), (("data", "items", 0, "author"), 3),
    (("data", "items", 0, "duration_seconds"), True),
    (("data", "items", 0, "source_url"), "https://user:secret@example.test"),
    (("data", "items", 0, "credit", "source_url"), "file:///private"),
    (("data", "items", 0, "facets", "topic"), []),
    (("data", "items", 0, "preview", "byte_length"), -1),
    (("data", "items", 0, "preview", "href"), ""),
])
def test_search_rejects_invalid_wire_values(path, value):
    body = search_body()
    target = body
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert parse_search_response(body)["code"] == "contract_mismatch"


def test_search_keeps_twenty_result_limit():
    body = search_body()
    item = body["data"]["items"][0]
    body["data"]["items"] = [item] * 20
    assert parse_search_response(body)["ok"] is True
    body["data"]["items"].append(item)
    assert parse_search_response(body)["code"] == "contract_mismatch"


def test_search_maps_raw_ids_to_canonical_refs():
    body = search_body()
    body["data"]["items"][0]["id"] = "saved item"
    assert parse_search_response(body)["results"][0]["item_ref"] == "uoink://item/saved%20item"
