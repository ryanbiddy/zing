"""Shared fixtures for all lanes.

Use ``zing_workspace`` in any test that touches storage: it points the
workspace at a fresh tmp dir via the ZING_HOME env var, so tests never
read or write the real ~/.zing and pass offline on any machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myzing import storage


@pytest.fixture
def zing_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "zing-home"
    monkeypatch.setenv(storage.ENV_VAR, str(root))
    return root
