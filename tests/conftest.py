"""Shared fixtures for all lanes.

Use ``zing_workspace`` in any test that touches storage: it points the
workspace at a fresh tmp dir via the ZING_HOME env var, so tests never
read or write the real ~/.zing and pass offline on any machine.

ffmpeg-gated tests are marked ``@pytest.mark.ffmpeg``. On a machine
without ffmpeg/ffprobe they skip with an honest reason — EXCEPT when
``ZING_REQUIRE_FFMPEG=1`` is set (the dedicated CI ffmpeg jobs set it),
which turns the missing-tool skip into a hard failure so the real gates
can never silently degrade to mocked-only coverage (F-01 / C#8).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from myzing import storage

pytest_plugins = ["pytester"]

FFMPEG_TOOLS = ("ffmpeg", "ffprobe")
REQUIRE_ENV_VAR = "ZING_REQUIRE_FFMPEG"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "ffmpeg: needs real ffmpeg+ffprobe on PATH (skips when absent; "
        f"{REQUIRE_ENV_VAR}=1 turns that skip into a failure)",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("ffmpeg") is None:
        return
    missing = [tool for tool in FFMPEG_TOOLS if shutil.which(tool) is None]
    if not missing:
        return
    message = f"required tools missing from PATH: {', '.join(missing)}"
    if os.environ.get(REQUIRE_ENV_VAR) == "1":
        pytest.fail(
            f"{message} — {REQUIRE_ENV_VAR}=1 forbids skipping ffmpeg-gated "
            "tests (this job must run the real ffmpeg gates)",
            pytrace=False,
        )
    pytest.skip(message)


@pytest.fixture
def zing_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "zing-home"
    monkeypatch.setenv(storage.ENV_VAR, str(root))
    return root


class FakeHTTPResponse(__import__("io").BytesIO):
    """The one canonical urlopen-response stub (SG-3: this context-manager
    BytesIO was hand-defined in four places across the suite). Usable as
    `return FakeHTTPResponse(body_bytes)` from a monkeypatched urlopen."""

    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
