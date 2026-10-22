"""Observe the real client against strict and forgiving fake peers."""

import copy
import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import FakeHTTPResponse
from test_suite_peer import make_manifest
from test_uoink_search_contract import search_body
from tools.eval import suite_search, suite_smoke


@pytest.fixture(params=["strict", "forgiving"])
def fake_search_peer(monkeypatch, request):
    calls = []
    matching = request.param
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:61983")
    monkeypatch.setenv("UOINK_TOKEN", "synthetic-smoke-token")

    def respond(request, *args, **kwargs):
        calls.append(request)
        if request.full_url.endswith("suite-service.json"):
            return FakeHTTPResponse(json.dumps(make_manifest()).encode())
        url = urlsplit(request.full_url)
        params = parse_qs(url.query)
        assert url.path == "/api/corpus/v1/search"
        assert set(params) == {"q", "limit"}
        assert params["limit"] == ["20"]
        assert request.get_method() == "GET" and request.data is None
        body = search_body()
        item = body["data"]["items"][0]
        item.update(id="suite-smoke-fixture", title="Suite smoke fixture")
        query = params["q"][0]
        hits = query != "zzzxqnonexistent" and (matching == "forgiving" or query == "Suite smoke fixture")
        body["data"]["items"] = [item] if hits else []
        body["data"]["page"].update(state="matches" if hits else "no_matches", total=int(hits), corpus_total=1)
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(suite_search.urllib.request, "urlopen", respond)
    return matching, calls


def test_search_uses_exact_get_parameters_and_records_matching(fake_search_peer):
    matching, calls = fake_search_peer
    evidence = suite_search.collect_search_evidence()
    assert suite_smoke._search_contract_issues({"search": evidence}) == []
    assert suite_smoke._search_details_issues({"search": evidence}) == []
    searches = [call for call in calls if "/search?" in call.full_url]
    assert len(searches) == 3
    for call, (_, query) in zip(searches, suite_search.SEARCH_CASES):
        assert call.full_url.startswith("http://127.0.0.1:61983/api/corpus/v1/search?")
        assert parse_qs(urlsplit(call.full_url).query) == {"q": [query], "limit": ["20"]}
        assert call.data is None and call.get_method() == "GET"
    assert evidence["queries"][1]["hit_count"] == int(matching == "forgiving")
    assert evidence["matching_behavior"] == (
        "forgiving_query_matched" if matching == "forgiving" else "forgiving_query_no_matches")


@pytest.mark.parametrize("defect", ["extra_data", "missing_exact", "count", "details", "mode", "behavior"])
def test_evaluator_rejects_bad_search_evidence(fake_search_peer, defect):
    evidence = copy.deepcopy(suite_search.collect_search_evidence())
    if defect == "extra_data":
        evidence["queries"][0]["response"]["data"]["citations"] = []
    elif defect == "missing_exact":
        evidence["queries"][0]["response"]["data"]["items"] = []
    elif defect == "count":
        evidence["queries"][1]["hit_count"] = 10
    elif defect in ("details", "mode"):
        name = "search_details" if defect == "details" else "mode"
        evidence["queries"][0]["request"]["params"][name] = ["true"]
        if defect == "details":
            assert suite_smoke._search_details_issues({"search": evidence})
    else:
        evidence["matching_behavior"] = "guessed"
    assert suite_smoke._search_contract_issues({"search": evidence})
