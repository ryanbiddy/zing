"""Regression tests for F-01: the ffmpeg gate must be un-skippable in CI.

The ffmpeg-marked subset may skip honestly on a dev box without ffmpeg,
but when ZING_REQUIRE_FFMPEG=1 (set by the CI ffmpeg jobs) a missing
ffmpeg must FAIL the run — "CI green" may never again mean "the real
gates silently skipped".
"""

from __future__ import annotations

from pathlib import Path

import pytest

CONFTEST = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
MARKED_TEST = """
import pytest


@pytest.mark.ffmpeg
def test_needs_real_ffmpeg():
    pass
"""
SKIPPING_MARKED_TEST = """
import pytest


@pytest.mark.ffmpeg
def test_skips_despite_available_tools():
    pytest.skip("mutation")
"""
XFAILING_MARKED_TEST = """
import pytest


@pytest.mark.ffmpeg
@pytest.mark.xfail(reason="mutation")
def test_expected_failure():
    assert False
"""
TWO_MARKED_TESTS = """
import pytest


@pytest.mark.ffmpeg
def test_first():
    pass


@pytest.mark.ffmpeg
def test_second():
    pass
"""
COLLECTION_SKIPPING_MODULE = """
import pytest

pytest.skip("mutation", allow_module_level=True)
"""


def _run_marked_test_without_ffmpeg(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    *,
    require: bool,
) -> pytest.RunResult:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(MARKED_TEST)
    # Simulate a runner with no ffmpeg/ffprobe anywhere on PATH.
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: None)
    if require:
        monkeypatch.setenv("ZING_REQUIRE_FFMPEG", "1")
    else:
        monkeypatch.delenv("ZING_REQUIRE_FFMPEG", raising=False)
    return pytester.runpytest_inprocess("-q")


def test_missing_ffmpeg_skips_honestly_by_default(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run_marked_test_without_ffmpeg(pytester, monkeypatch, require=False)

    result.assert_outcomes(skipped=1)
    assert result.ret == 0


def test_missing_ffmpeg_fails_loudly_when_required(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run_marked_test_without_ffmpeg(pytester, monkeypatch, require=True)

    outcomes = result.parseoutcomes()
    assert outcomes.get("skipped", 0) == 0
    assert outcomes.get("passed", 0) == 0
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*ZING_REQUIRE_FFMPEG=1 forbids skipping*"])


def test_generic_skip_fails_loudly_when_ffmpeg_is_required(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(SKIPPING_MARKED_TEST)
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: "available")
    monkeypatch.setenv("ZING_REQUIRE_FFMPEG", "1")

    result = pytester.runpytest_inprocess("-q")

    outcomes = result.parseoutcomes()
    assert outcomes.get("skipped", 0) == 0
    assert outcomes.get("passed", 0) == 0
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*ZING_REQUIRE_FFMPEG=1 forbids skipping*"])


def test_xfail_fails_loudly_when_ffmpeg_is_required(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(XFAILING_MARKED_TEST)
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: "available")
    monkeypatch.setenv("ZING_REQUIRE_FFMPEG", "1")

    result = pytester.runpytest_inprocess("-q")

    result.assert_outcomes(failed=1)
    assert result.ret != 0
    result.stdout.fnmatch_lines(
        ["*ZING_REQUIRE_FFMPEG=1 forbids skipping or xfail*"]
    )


def test_expected_ffmpeg_count_accepts_exact_collection(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(TWO_MARKED_TESTS)
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: "available")
    monkeypatch.setenv("ZING_REQUIRE_FFMPEG", "1")

    result = pytester.runpytest_inprocess(
        "-q", "-m", "ffmpeg", "--expected-ffmpeg-tests", "2"
    )

    result.assert_outcomes(passed=2)
    assert result.ret == 0


def test_expected_ffmpeg_count_rejects_deselection(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(TWO_MARKED_TESTS)
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: "available")
    monkeypatch.setenv("ZING_REQUIRE_FFMPEG", "1")

    result = pytester.runpytest_inprocess(
        "-q", "-m", "ffmpeg", "--expected-ffmpeg-tests", "3"
    )

    assert result.ret != 0
    result.stderr.fnmatch_lines(
        ["*expected exactly 3 selected tests, but collected 2*"]
    )


def test_collection_skip_fails_counted_ffmpeg_gate(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(COLLECTION_SKIPPING_MODULE)
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: "available")
    monkeypatch.setenv("ZING_REQUIRE_FFMPEG", "1")

    result = pytester.runpytest_inprocess(
        "-q", "-m", "ffmpeg", "--expected-ffmpeg-tests", "0"
    )

    assert result.ret != 0
    result.stdout.fnmatch_lines(
        ["*required ffmpeg gate recorded 1 skip(s) and 0 xfail(s)*"]
    )
