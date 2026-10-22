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
import sys
from pathlib import Path

import pytest

from myzing import storage


def _guard_live_uoink(event, args):
    """Fail before any real socket or filesystem access to Ryan's Uoink."""
    if event in {"socket.connect", "socket.getaddrinfo"}:
        address = args[1] if event == "socket.connect" else args[:2]
        if isinstance(address, tuple) and len(address) > 1 and str(address[1]) == "5179":
            raise AssertionError("Tests must never contact the live Uoink port")
    if event in {"open", "os.listdir", "os.scandir", "os.remove", "os.rename", "os.mkdir"}:
        for value in args[:2] if event == "os.rename" else args[:1]:
            if not isinstance(value, (str, bytes, os.PathLike)):
                continue
            path = os.fsdecode(value).replace("\\", "/").lower().rstrip("/")
            if (path == "e:/uoink" or path.startswith("e:/uoink/")
                    or "/appdata/local/uoink/" in path or path.endswith("/appdata/local/uoink")):
                raise AssertionError("Tests must never access the live Uoink library")


sys.addaudithook(_guard_live_uoink)


@pytest.fixture(autouse=True)
def isolated_uoink_transport(monkeypatch):
    """Default peer requests must be mocked; never inherit real credentials."""
    import urllib.error
    import urllib.request
    from myzing import suite_peer, uoink_bridge

    monkeypatch.delenv("UOINK_TOKEN", raising=False)
    monkeypatch.delenv("UOINK_URL", raising=False)
    monkeypatch.setattr(suite_peer, "UOINK_DEFAULT_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(uoink_bridge, "UOINK_DEFAULT_URL", "http://127.0.0.1:1")
    original = urllib.request.urlopen

    def offline_peer(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.startswith("http://127.0.0.1:1/"):
            raise urllib.error.URLError("isolated test peer is offline")
        if ":5179" in url:
            raise AssertionError("Patch peer discovery before making test requests")
        return original(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", offline_peer)


@pytest.fixture(autouse=True)
def preserve_v1_contract_bytes(monkeypatch):
    """Check every existing fixture/golden that constructs or serializes v1."""
    from myzing.schemas import Breakdown, EDL, StyleProfile
    from test_composition_v1_compat import assert_v1_bytes

    for cls in (EDL, Breakdown, StyleProfile):
        original = cls.to_dict

        def checked(self, serialize=original):
            result = serialize(self)
            if self.schema_version == 1:
                assert_v1_bytes(self, result)
            return result

        monkeypatch.setattr(cls, "to_dict", checked)

    initialize = EDL.__init__

    def checked_init(self, *args, **kwargs):
        initialize(self, *args, **kwargs)
        # Also cover render goldens that pass EDL objects directly to FFmpeg.
        # Malformed non-JSON test objects remain the renderer validator's job.
        try:
            self.to_dict()
        except (TypeError, KeyError):
            pass

    monkeypatch.setattr(EDL, "__init__", checked_init)

pytest_plugins = ["pytester"]

FFMPEG_TOOLS = ("ffmpeg", "ffprobe")
REQUIRE_ENV_VAR = "ZING_REQUIRE_FFMPEG"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_private_ocr: original lexical calibration requires unredistributed "
        "third-party text (SEC1-OCR; see tests/PRIVATE-FIXTURES.md)",
    )
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


@pytest.fixture(autouse=True)
def isolated_suite_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Never let a test inherit a real per-user suite runtime lease."""
    from myzing import suite_peer

    root = tmp_path / "suite-services"
    monkeypatch.setattr(
        suite_peer,
        "lease_paths",
        lambda service_id: [root / f"{service_id}.json"],
    )
    return root


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
