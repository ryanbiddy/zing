from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from myzing import ffmpeg_capabilities as capabilities


@pytest.fixture(autouse=True)
def clear_filter_cache():
    capabilities._filters_for_executable.cache_clear()
    yield
    capabilities._filters_for_executable.cache_clear()


@pytest.mark.parametrize(
    "listing,expected",
    [
        (" ... ass V->V Render ASS subtitles\n ... subtitles V->V Render text", "ass"),
        (" ... subtitles V->V Render text subtitles using libass", "subtitles"),
        (" TSC ass V->V Render ASS subtitles", "ass"),
        (" .. ass V->V Render ASS subtitles", "ass"),
        (" .. subtitles V->V Render text subtitles using libass", "subtitles"),
    ],
)
def test_selects_available_caption_filter(monkeypatch, tmp_path, listing, expected):
    executable = str(tmp_path / "ffmpeg")
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: executable)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(command, 0, listing, "")

    monkeypatch.setattr(capabilities.subprocess, "run", run)
    assert capabilities.caption_filter("ffmpeg") == expected
    assert capabilities.caption_filter(executable) == expected
    assert calls == [[str(Path(executable).resolve()), "-hide_banner", "-filters"]]


def test_filter_cache_follows_path_changes(monkeypatch, tmp_path):
    executable = tmp_path / "plain-ffmpeg"
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: str(executable))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        listing = " ... ass V->V Render subtitles" if "full-ffmpeg" in command[0] else ""
        return subprocess.CompletedProcess(command, 0, listing, "")

    monkeypatch.setattr(capabilities.subprocess, "run", run)
    for _ in range(2):
        with pytest.raises(capabilities.FFmpegCapabilityError, match="no libass") as error:
            capabilities.caption_filter()
    message = str(error.value)
    for remedy in ("brew install ffmpeg-full", "brew --prefix ffmpeg-full", "sudo port install ffmpeg", "HyperFrames"):
        assert remedy in message
    executable = tmp_path / "full-ffmpeg"
    assert capabilities.caption_filter() == "ass"
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["missing", "timeout", "oserror", "nonzero"])
def test_probe_failures_do_not_claim_libass_is_absent(monkeypatch, tmp_path, failure):
    executable = str(tmp_path / "ffmpeg")
    monkeypatch.setattr(
        capabilities.shutil, "which", lambda _: None if failure == "missing" else executable,
    )

    def run(command, **kwargs):
        if failure == "missing":
            pytest.fail("missing executable must not be launched")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 30)
        if failure == "oserror":
            raise OSError("cannot execute")
        return subprocess.CompletedProcess(command, 1, "", "broken binary")

    monkeypatch.setattr(capabilities.subprocess, "run", run)
    with pytest.raises(capabilities.FFmpegCapabilityError) as error:
        capabilities.caption_filter()
    assert "no libass" not in str(error.value)
    assert "not found" in str(error.value) or "could not probe" in str(error.value)


def test_filter_names_are_not_matched_in_descriptions(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: str(tmp_path / "ffmpeg"))
    monkeypatch.setattr(
        capabilities.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, " ... drawtext V->V description mentions ass and subtitles\n", "",
        ),
    )
    with pytest.raises(capabilities.FFmpegCapabilityError, match="no libass"):
        capabilities.caption_filter()
