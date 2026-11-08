"""Download blocks and failure retries without media or network calls."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from myzing.playbook import command, measure
from myzing.playbook.common import read_json, write_json
from myzing.schemas import Breakdown, VideoMeta
from myzing.study.ingest import download_category
from myzing.study.proc import MediaError

BLOCK_HINT = "YouTube blocked downloads for now. Wait, then run measure --download --retry-failed."
BOT = ("yt-dlp could not fetch URL (exit 1):\nERROR: [youtube] x: "
       "Sign in to confirm you're not a bot. Use --cookies-from-browser")
PHRASES = [
    ("confirm you're not a bot", "download_bot_check", BLOCK_HINT),
    ("confirm you’re not a bot", "download_bot_check", BLOCK_HINT),
    ("sign in to confirm", "download_bot_check", BLOCK_HINT),
    ("http error 429", "download_rate_limited", BLOCK_HINT),
    ("too many requests", "download_rate_limited", BLOCK_HINT),
    ("rate-limit", "download_rate_limited", BLOCK_HINT),
    ("rate limit", "download_rate_limited", BLOCK_HINT),
    ("video unavailable", "download_unavailable", "The video cannot be downloaded."),
    ("private video", "download_unavailable", "The video cannot be downloaded."),
    ("this video has been removed", "download_unavailable", "The video cannot be downloaded."),
    ("members-only", "download_unavailable", "The video cannot be downloaded."),
    ("age-restricted", "download_unavailable", "The video cannot be downloaded."),
    ("confirm your age", "download_unavailable", "The video cannot be downloaded."),
    ("yt-dlp is not installed", "ytdlp_missing", "Install yt-dlp: zing doctor."),
]


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(measure.study_api, "study", refuse)
    monkeypatch.setattr(measure.time, "sleep", refuse)


def library(root, *ids):
    entries = [{"id": ident, "platform": "youtube", "channel": "Example", "set": "worked",
                "url": f"https://www.youtube.com/shorts/{ident}"} for ident in ids]
    write_json(root / "library.json", {"schema_version": 1, "entries": entries})
    return [entry["url"] for entry in entries]


def breakdown():
    return Breakdown(VideoMeta("file", "file", duration=10, width=1080, height=1920))


def failed(root, ident, reason="MediaError: download_bot_check"):
    path = root / "measured" / f"{ident}.failed.json"
    write_json(path, {"id": ident, "source": "measured", "status": "failed", "reason": reason})
    return path


def local(root, ident):
    path = root / f"{ident}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture; not a video")
    return str(path)


@pytest.mark.parametrize("phrase,category,hint", PHRASES)
def test_categories_and_safe_records(tmp_path, monkeypatch, phrase, category, hint):
    library(tmp_path, "v0")
    assert download_category(phrase) == category
    assert download_category(phrase.upper()) == category
    message = ("yt-dlp could not fetch https://example.org/private (exit 1):\n"
               f"ERROR: [youtube] stderr-id: {phrase.upper()}. Use --cookies-from-browser")
    def study(*args, **kwargs):
        raise MediaError(message)
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True)
    record = read_json(tmp_path / "measured/v0.failed.json")
    assert record == {"id": "v0", "source": "measured", "status": "failed",
                      "reason": f"MediaError: {category}", "hint": hint}
    assert read_json(tmp_path / "features.json")["entries"] == [record]
    assert result["failed"] == 1
    for text in (json.dumps(result), json.dumps(record), (tmp_path / "features.json").read_text()):
        assert all(value not in text for value in ("https://", "stderr-id", "ERROR", "exit 1", "cookies-from-browser"))


@pytest.mark.parametrize("text", ["", "HTTP Error 403", "bot detected", "sign in", "429", "missing yt-dlp"])
def test_unknown_errors_keep_fixed_reason(text):
    assert download_category(text) is None
    assert measure.failure_reason(MediaError(text)) == "MediaError: measurement failed; details omitted"


@pytest.mark.parametrize("link", ["__cause__", "__context__"])
def test_chained_errors_are_safe(tmp_path, monkeypatch, link):
    library(tmp_path, "v0")
    error = RuntimeError("private wrapper details")
    middle = ValueError("private intermediate details")
    setattr(error, link, middle)
    middle.__context__ = MediaError(BOT)
    def study(*args, **kwargs):
        raise error
    monkeypatch.setattr(measure.study_api, "study", study)
    measure.measure(tmp_path, download=True)
    record = read_json(tmp_path / "measured/v0.failed.json")
    assert record["reason"] == "RuntimeError: download_bot_check"
    assert record["hint"] == BLOCK_HINT
    assert "private" not in json.dumps(record) and "ERROR" not in json.dumps(record)


def test_failure_chain_order_cycles_and_timeout():
    error = RuntimeError("private details")
    error.__cause__ = error
    error.__context__ = MediaError("HTTP Error 429")
    assert measure.failure_reason(error) == "RuntimeError: download_rate_limited"
    error.__context__ = error
    assert measure.failure_reason(error) == "RuntimeError: measurement failed; details omitted"
    error.__cause__ = MediaError("private video")
    error.__context__ = MediaError(BOT)
    assert measure.failure_reason(error) == "RuntimeError: download_unavailable"
    error = MediaError(BOT)
    error.__cause__ = MediaError("HTTP Error 429")
    assert measure.failure_reason(error) == "MediaError: download_bot_check"
    assert measure.failure_reason(subprocess.TimeoutExpired(["private-command"], 60)) == "TimeoutExpired: tool timed out"


@pytest.mark.parametrize("message,category", [(BOT, "download_bot_check"), ("HTTP Error 429", "download_rate_limited")])
def test_blocks_pause_downloads_but_local_and_cache_continue(tmp_path, monkeypatch, message, category):
    urls = library(tmp_path, "v0", "v1", "v2", "v3", "local", "cached", "v4")
    media = local(tmp_path / "media", "local")
    cached = tmp_path / "measured/cached.json"
    write_json(cached, breakdown().to_dict())
    before = cached.read_bytes(), cached.stat().st_mtime_ns
    calls, sleeps = [], []
    def study(source, **kwargs):
        calls.append(source)
        if source == media:
            return breakdown()
        raise MediaError(message)
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True, sleep=sleeps.append)
    assert calls == urls[:3] + [media] and sleeps == [3, 3]
    assert {key: result[key] for key in ("done", "cached", "failed", "unmeasured", "paused", "stopped")} == {
        "done": 1, "cached": 1, "failed": 3, "unmeasured": 2, "paused": 2, "stopped": category}
    assert [row["status"] for row in result["entries"]] == [
        "failed", "failed", "failed", "unmeasured", "measured", "measured", "unmeasured"]
    for ident in ("v3", "v4"):
        assert next(row for row in result["entries"] if row["id"] == ident)["reason"] == "download paused after YouTube blocks"
        assert not (tmp_path / "measured" / f"{ident}.failed.json").exists()
    assert (cached.read_bytes(), cached.stat().st_mtime_ns) == before
    calls.clear()
    monkeypatch.setattr(measure.study_api, "study", lambda source, **kw: (calls.append(source), breakdown())[1])
    resumed = measure.measure(tmp_path, download=True, sleep=sleeps.append)
    assert calls == [urls[3], urls[6]]
    assert resumed["done"] == 2 and resumed["failed"] == 3 and resumed["paused"] == 0
    assert "stopped" not in resumed


@pytest.mark.parametrize("success", ["download", "local", "cached", "other_failure"])
def test_nonblock_between_blocks_resets_count(tmp_path, monkeypatch, success):
    urls = library(tmp_path, "v0", "v1", "middle", "v2", "v3", "v4", "v5")
    if success == "local":
        local(tmp_path / "media", "middle")
    if success == "cached":
        write_json(tmp_path / "measured/middle.json", breakdown().to_dict())
    calls = []
    def study(source, **kwargs):
        calls.append(source)
        if source == urls[2] or Path(source).stem == "middle":
            if success == "other_failure":
                raise MediaError("private video")
            return breakdown()
        raise MediaError(BOT if source != urls[4] else "Too many requests")
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True, gap=0)
    assert urls[5] in calls and urls[6] not in calls
    assert result["stopped"] == "download_bot_check" and result["paused"] == 1
    assert result["failed"] == (6 if success == "other_failure" else 5)


@pytest.mark.parametrize("gap", [0, 2.5])
def test_gap_only_before_later_downloads(tmp_path, monkeypatch, gap):
    urls = library(tmp_path, "local", "v0", "saved", "cached", "v1", "v2", "v3")
    media = local(tmp_path / "media", "local")
    failed(tmp_path, "saved")
    write_json(tmp_path / "measured/cached.json", breakdown().to_dict())
    events = []
    def study(source, **kwargs):
        events.append(source)
        if source == urls[5]:
            raise MediaError(BOT)
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True, max_blocks=1, gap=gap,
                             sleep=lambda seconds: events.append(("sleep", seconds)))
    expected = [media, urls[1]]
    for source in (urls[4], urls[5]):
        expected.extend([("sleep", gap)] if gap else [])
        expected.append(source)
    assert events == expected
    assert result["paused"] == 1


def test_retry_only_failures_preserves_measured_files(tmp_path, monkeypatch):
    urls = library(tmp_path, "cached", "download", "local", "fresh", "fresh_local")
    media = tmp_path / "other-media"
    local_source = local(media, "local")
    local(media, "fresh_local")
    cached = tmp_path / "measured/cached.json"
    sidecar = cached.with_suffix(".caption-geometry.json")
    write_json(cached, breakdown().to_dict())
    write_json(sidecar, {"frames": []})
    write_json(tmp_path / "working/cached/fixture/caption-geometry.json", {"frames": [], "changed": True})
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (cached, sidecar)}
    records = {ident: failed(tmp_path, ident, "MediaError: measurement failed; details omitted")
               for ident in ("download", "local")}
    write_json(tmp_path / "measured/download.json", breakdown().to_dict())
    calls = []
    def study(source, **kwargs):
        calls.append(source)
        ident = "download" if source == urls[1] else "local"
        assert records[ident].exists()              # kept until the retry succeeds
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True, media_dir=media, retry_failed=True)
    assert calls == [urls[1], local_source]
    assert result["done"] == 2 and result["cached"] == 1 and result["unmeasured"] == 2 and result["failed"] == 0
    assert all(not path.exists() for path in records.values())
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before} == before
    assert not (tmp_path / "measured/fresh.json").exists()
    assert not (tmp_path / "measured/fresh_local.json").exists()


def test_retry_local_without_download_and_keep_unattempted_failures(tmp_path, monkeypatch):
    library(tmp_path, "local", "missing")
    media = tmp_path / "other-media"
    source = local(media, "local")
    record = failed(tmp_path, "local")
    missing = failed(tmp_path, "missing")
    before = missing.read_bytes(), missing.stat().st_mtime_ns
    def study(value, **kwargs):
        assert value == source and record.exists()
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, media_dir=media, retry_failed=True)
    assert result["done"] == 1 and result["unmeasured"] == 1
    assert (missing.read_bytes(), missing.stat().st_mtime_ns) == before


def test_retry_block_replaces_attempted_record_only(tmp_path, monkeypatch):
    urls = library(tmp_path, "v0", "v1")
    first, second = failed(tmp_path, "v0"), failed(tmp_path, "v1")
    before = second.read_bytes(), second.stat().st_mtime_ns
    def study(source, **kwargs):
        assert source == urls[0] and first.exists()
        raise MediaError("Too many requests")
    monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True, retry_failed=True, max_blocks=1)
    assert read_json(first)["reason"] == "MediaError: download_rate_limited"
    assert result["failed"] == 1 and result["paused"] == 1
    assert (second.read_bytes(), second.stat().st_mtime_ns) == before


@pytest.mark.parametrize("kwargs,message", [
    ({"force": True, "retry_failed": True}, "use one of --force or --retry-failed"),
    ({"max_blocks": 0}, "--max-blocks"), ({"max_blocks": -1}, "--max-blocks"),
    ({"max_blocks": 1.5}, "--max-blocks"), ({"max_blocks": True}, "--max-blocks"),
    ({"gap": -1}, "--gap"), ({"gap": float("nan")}, "--gap"),
    ({"gap": float("inf")}, "--gap"), ({"gap": True}, "--gap"),
])
def test_invalid_options_do_not_write(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        measure.measure(tmp_path, **kwargs)
    assert not (tmp_path / "features.json").exists()


@pytest.mark.parametrize("flags,message", [
    (["--force", "--retry-failed"], "use one of --force or --retry-failed"),
    (["--gap", "-1"], "--gap"), (["--gap", "nan"], "--gap"),
    (["--max-blocks", "0"], "--max-blocks"),
])
def test_cli_rejects_invalid_options(tmp_path, capsys, flags, message):
    assert command.run(["measure", str(tmp_path), *flags]) == 2
    assert message in capsys.readouterr().out


def test_cli_category_counts_and_pause(tmp_path, monkeypatch, capsys):
    messages = ["private video", "yt-dlp is not installed", "HTTP Error 429", BOT, BOT, BOT]
    library(tmp_path, *(f"v{i}" for i in range(len(messages) + 1)))
    calls = []
    def study(source, **kwargs):
        calls.append(source)
        raise MediaError(messages[len(calls) - 1])
    monkeypatch.setattr(measure.study_api, "study", study)
    assert command.run(["measure", str(tmp_path), "--download", "--gap", "0", "--max-blocks", "4"]) == 1
    output = capsys.readouterr().out
    result, end = json.JSONDecoder().raw_decode(output)
    assert result["failed"] == 6 and result["paused"] == 1 and len(calls) == 6
    assert output[end:].strip().splitlines() == [
        f"3 failed: download_bot_check. {BLOCK_HINT}",
        f"1 failed: download_rate_limited. {BLOCK_HINT}",
        "1 failed: download_unavailable. The video cannot be downloaded.",
        "1 failed: ytdlp_missing. Install yt-dlp: zing doctor.",
        "Downloads paused after download_bot_check. 1 left unmeasured.",
    ]
    assert "cookies-from-browser" not in output and "ERROR" not in output
    calls.clear()
    assert command.run(["measure", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert f"3 failed: download_bot_check. {BLOCK_HINT}" in output and calls == []
    assert "Downloads paused" not in output


def test_cli_retry_and_custom_gap(tmp_path, monkeypatch, capsys):
    urls = library(tmp_path, "v0", "v1", "fresh")
    failed(tmp_path, "v0")
    failed(tmp_path, "v1")
    events = []
    monkeypatch.setattr(measure.time, "sleep", lambda seconds: events.append(seconds))
    monkeypatch.setattr(measure.study_api, "study", lambda source, **kw: (events.append(source), breakdown())[1])
    assert command.run(["measure", str(tmp_path), "--download", "--retry-failed", "--gap", "1.25"]) == 0
    assert events == [urls[0], 1.25, urls[1]]
    result = json.loads(capsys.readouterr().out)
    assert result["done"] == 2 and result["unmeasured"] == 1


def test_age_check_is_unavailable_not_a_bot_check():
    from myzing.study.ingest import download_category
    assert download_category("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate") == "download_unavailable"
    assert download_category("ERROR: [youtube] x: Sign in to confirm you're not a bot.") == "download_bot_check"
