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
