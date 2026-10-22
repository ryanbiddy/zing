"""`zing plan` is one command: drafts (director) and choose (choice memory)."""

from __future__ import annotations

import pytest

from myzing import cli
from myzing.director import command as director_command
from myzing.plan import command as plan_command


def test_plan_is_registered_once_and_routes_to_the_unified_module():
    assert cli._COMMANDS["plan"][0] == "myzing.plan.command"
    assert director_command.run is plan_command.run


@pytest.mark.parametrize("action", ["drafts", "choose"])
def test_plan_offers_both_subcommands(action, capsys):
    with pytest.raises(SystemExit) as exit_info:
        plan_command.run([action, "--help"])
    assert exit_info.value.code == 0
    assert f"zing plan {action}" in capsys.readouterr().out
