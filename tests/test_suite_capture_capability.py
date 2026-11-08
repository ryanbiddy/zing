"""Uoink #418 adds uoink.capture/1. The suite smoke runs against Uoink main, so the
lease and manifest checks must accept that optional capability and still reject drift."""
from __future__ import annotations

import copy

import pytest

from tools.eval.suite_contracts import load_fixture_case, validate_contract_payload


@pytest.mark.parametrize(("case_id", "contract", "where"), [
    ("runtime_lease_valid_uoink", "ryan.suite.runtime-lease/1", ("capabilities",)),
    ("service_valid_uoink", "ryan.suite.service/1", ("service", "capabilities")),
])
@pytest.mark.parametrize(("change", "passed"), [
    ("capture", True), ("unknown", False), ("missing", False), ("unsorted", False)])
def test_optional_capture_capability(case_id, contract, where, change, passed):
    case = load_fixture_case(case_id)
    payload = copy.deepcopy(case["payload"])
    holder = payload
    for key in where[:-1]:
        holder = holder[key]
    caps = list(holder[where[-1]])
    if change == "capture":
        caps = sorted([*caps, "uoink.capture/1"])
    elif change == "unknown":
        caps = sorted([*caps, "uoink.unknown/1"])
    elif change == "missing":
        caps = [c for c in caps if c != "uoink.media.handoff/1"]
    else:
        caps = [*sorted(caps), "uoink.capture/1"] if caps[-1] > "uoink.capture/1" else caps[::-1]
    holder[where[-1]] = caps
    assert validate_contract_payload(contract, payload, **case.get("context", {}))["passed"] is passed
