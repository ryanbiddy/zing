"""Exercise Zing's real corpus.read/1 search client against an isolated peer."""

from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
from unittest.mock import patch

from myzing import suite_peer, uoink_bridge


SEARCH_CASES = (
    ("exact_title", "Suite smoke fixture"),
    ("forgiving", "the suite smoke fixture"),
    ("no_match", "zzzxqnonexistent"),
)


def collect_search_evidence() -> dict:
    """Observe actual request/response bytes; never opt into search details."""
    base = uoink_bridge.credential_safe_url(uoink_bridge.helper_url())
    status, manifest = suite_peer._get_json(base + "/.well-known/suite-service.json")
    if (status != 200 or suite_peer._manifest_defect(manifest) is not None
            or manifest["service"]["id"] != "uoink"):
        raise ValueError("search discovery failed")
    capabilities = manifest["service"]["capabilities"]
    if uoink_bridge.SEARCH_CAPABILITY not in capabilities:
        raise ValueError("Uoink does not advertise corpus.read/1")
    evidence = {"capabilities": capabilities, "status": "checked", "queries": []}

    transport = urllib.request.urlopen
    evidence["status"] = "checked"
    for case, query in SEARCH_CASES:
        exchanges = []

        def observe(request, *args, **kwargs):
            url = urllib.parse.urlsplit(request.full_url)
            if url.path != "/api/corpus/v1/search":
                return transport(request, *args, **kwargs)
            with transport(request, *args, **kwargs) as response:
                raw = response.read(1024 * 1024 + 1)
            exchanges.append({"request": {"method": request.get_method(),
                                          "params": urllib.parse.parse_qs(url.query),
                                          "body": request.data},
                              "response": json.loads(raw)})
            return io.BytesIO(raw)

        with patch.object(urllib.request, "urlopen", observe):
            parsed = uoink_bridge.search_references(query)
        if len(exchanges) != 1 or parsed.get("ok") is not True:
            raise ValueError("Zing rejected advertised search v1: " + case)
        hits = len(parsed["results"])
        evidence["queries"].append({"case": case, **exchanges[0], "hit_count": hits})
        if case == "forgiving":
            # The extra word is absent from the seeded corpus. Older peers use
            # AND matching; 3.11 defaults to forgiving keyword matching. Record
            # the observed result without asserting a particular peer policy.
            evidence["matching_behavior"] = "forgiving_query_matched" if hits else "forgiving_query_no_matches"
    return evidence


if __name__ == "__main__":
    print(json.dumps(collect_search_evidence()))
