"""User guidance follows fake peer states without probing a live helper."""

import pytest

from myzing import doctor, mcp_server


@pytest.mark.parametrize("state", ["available", "unconfigured", "absent", "unhealthy"])
def test_doctor_and_config_explain_suite_from_same_peer_state(monkeypatch, capsys, state):
    peer = {"state": state}
    if state == "unhealthy":
        peer["error"] = {"code": "authentication_failed", "message": "synthetic rejection"}
    monkeypatch.setattr(doctor, "_probe_uoink_cached", lambda: (peer, "fake probe"))
    check = doctor.check_uoink()
    monkeypatch.setattr(doctor, "run_checks", lambda: [check])
    monkeypatch.setattr(doctor, "_next_step", lambda: "")
    assert doctor.run([]) == 0
    doctor_output = capsys.readouterr().out
    assert mcp_server.run(["--print-config"]) == 0
    config_output = capsys.readouterr().out
    for output in (doctor_output, config_output):
        if state in {"available", "unconfigured"}:
            assert "zing project find-reference" in output
            assert "uoink:<id>" in output and "push_to_uoink" in output
            assert ("suite available" if state == "available" else "configure UOINK_TOKEN") in output
        else:
            assert "https://uoink.app" in output
            assert "suite available" not in output
    assert check.ok is (state == "available")
