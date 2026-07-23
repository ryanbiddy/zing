"""Shared fixtures for all lanes.

Use ``zing_workspace`` in any test that touches storage: it points the
workspace at a fresh tmp dir via the ZING_HOME env var, so tests never
read or write the real ~/.zing and pass offline on any machine.

ffmpeg-gated tests are marked ``@pytest.mark.ffmpeg``. On a machine
without ffmpeg/ffprobe they skip with an honest reason — EXCEPT when
``ZING_REQUIRE_FFMPEG=1`` is set (the dedicated CI ffmpeg jobs set it),
which turns every skip or xfail into a hard failure. The jobs also pass
``--expected-ffmpeg-tests`` so silently deselecting a real gate is fatal
(F-01 / C#8).
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


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("ffmpeg gate")
    group.addoption(
        "--expected-ffmpeg-tests",
        type=int,
        default=None,
        metavar="COUNT",
        help="fail collection unless exactly COUNT tests remain selected",
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    expected = session.config.getoption("--expected-ffmpeg-tests")
    if expected is None:
        return
    actual = len(session.items)
    if actual != expected:
        raise pytest.UsageError(
            "ffmpeg gate expected exactly "
            f"{expected} selected tests, but collected {actual}"
        )


def pytest_sessionfinish(session: pytest.Session) -> None:
    if (
        os.environ.get(REQUIRE_ENV_VAR) != "1"
        or session.config.getoption("--expected-ffmpeg-tests") is None
    ):
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = list(reporter.stats.get("skipped", ())) if reporter else []
    xfailed = list(reporter.stats.get("xfailed", ())) if reporter else []
    if not skipped and not xfailed:
        return
    if reporter:
        reporter.write_sep(
            "=",
            "required ffmpeg gate recorded "
            f"{len(skipped)} skip(s) and {len(xfailed)} xfail(s)",
        )
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
):
    outcome = yield
    report = outcome.get_result()
    if (
        os.environ.get(REQUIRE_ENV_VAR) != "1"
        or item.get_closest_marker("ffmpeg") is None
    ):
        return
    was_xfail = hasattr(report, "wasxfail")
    if not report.skipped and not was_xfail:
        return
    kind = "xfail" if was_xfail else "skip"
    reason = getattr(report, "wasxfail", None) or str(report.longrepr)
    if was_xfail:
        del report.wasxfail
    report.outcome = "failed"
    report.longrepr = (
        f"{REQUIRE_ENV_VAR}=1 forbids skipping or xfail in ffmpeg-gated tests: "
        f"{kind} from "
        f"{item.nodeid} ({reason})"
    )


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
