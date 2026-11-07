"""Scripts learn from matched recordings without a live judge."""
from __future__ import annotations

from datetime import timedelta

import pytest

from myzing.channels import brief, command, registry
from myzing.factory import pipeline

from test_channels_brief import NOW, SCRIPT, Scripts, channel, folder, local, make  # noqa: F401

EMPTY = {"words": 0, "script_words": 0, "kept": 0, "added": 0,
         "hook_kept": False, "seconds": 0, "opening": ""}


def words(text):
    return [{"w": w, "s": 2 + i * .4, "e": 2 + (i + 1) * .4} for i, w in enumerate(text.split())]


def take(n=1, hook="Script opening", **values):
    return {"n": n, "hook": hook, "status": "recorded",
            "take": {"words": 100, "script_words": 100, "kept": .8, "added": .2,
                     "hook_kept": True, "seconds": 40, "opening": "Spoken opening", **values}}


def save(channel, *items, day="2026-11-06"):
    pipeline._write(folder(channel, day) / "brief.json", {"items": list(items)})


def test_compare_counts_content_sets_and_timing():
    item = {"script": "The bright sparks carry quiet stories. Stories!", "hook": "Bright sparks carry quiet stories"}
    assert brief.compare(item, words("Bright sparks spark new stories stories")) == {
        "words": 6, "script_words": 7, "kept": .6, "added": .25, "hook_kept": True,
        "seconds": 2.4, "opening": "Bright sparks spark new stories stories"}
    result = brief.compare({"script": "bright sparks carry", "hook": "bright sparks carry"}, words("bright fresh"))
    assert result["kept"] == .33 and result["added"] == .5 and result["hook_kept"] is False


@pytest.mark.parametrize("item,spoken", [
    ({}, []), ({"script": None, "hook": None}, []), ({}, None), (None, None),
    ({"script": 3, "hook": []}, [{}, None, "bad", {"w": None}, {"w": 4}, {"w": " \t"}]),
    ({}, {"w": "bright"}), ({}, "bright"),
])
def test_compare_empty_and_odd_input(item, spoken):
    assert brief.compare(item, spoken) == EMPTY


def test_compare_missing_text_and_content_words():
    assert brief.compare({"script": "Bright sparks"}, []) == {**EMPTY, "script_words": 2}
    assert brief.compare({"script": None}, [{"w": "Bright"}]) == {
        **EMPTY, "words": 1, "added": 1, "opening": "Bright"}
    assert brief.compare({"script": "This is that", "hook": "This"}, words("is that")) == {
        **EMPTY, "words": 2, "script_words": 3, "seconds": .8, "opening": "is that"}


@pytest.mark.parametrize("timing", [
    {}, {"s": 2}, {"e": 4}, {"s": None, "e": 4}, {"s": "bad", "e": 4},
    {"s": [], "e": 4}, {"s": 5, "e": 4}, {"s": 0, "e": float("nan")}, {"s": 0, "e": float("inf")},
])
def test_compare_bad_timing_keeps_the_words(timing):
    assert brief.compare({}, [{"w": "Bright", **timing}]) == {**EMPTY, "words": 1, "added": 1, "opening": "Bright"}


def test_compare_opening_uses_twenty_words_and_limits_text():
    item = {"script": "Bright", "hook": "Bright"}
    result = brief.compare(item, words("the " * 20 + "Bright"))
    assert result["words"] == 21 and result["kept"] == 1 and result["hook_kept"] is False
    assert result["opening"] == " ".join(["the"] * 20)
    result = brief.compare(item, words("abcdefghijk " * 19 + "Bright end"))
    assert result["hook_kept"] is True and result["opening"] == ("abcdefghijk " * 19)[:200]
    assert brief.compare({}, [{"w": "  Bright\n\t sparks ", "s": 1.04, "e": 3.36}]) == {
        **EMPTY, "words": 2, "added": 1, "seconds": 2.3, "opening": "Bright sparks"}


def test_recorded_saves_comparison_and_repeating_it_changes_nothing(channel, tmp_path):
    data = make(channel, judge=Scripts())
    project = tmp_path / "project"
    spoken = words(SCRIPT)
    pipeline._write(project / "words.json", spoken)
    matched = {"brief": data["date"], "item": 1}
    brief.recorded(channel["slug"], project, matched)
    saved = pipeline._read(folder(channel) / "brief.json")
    item = saved["items"][0]
    assert item["status"] == "recorded" and item["project"] == str(project)
    assert item["take"] == brief.compare(data["items"][0], spoken)
    assert item["take"]["kept"] == 1 and item["take"]["hook_kept"] is True
    brief.recorded(channel["slug"], project, matched)
    assert pipeline._read(folder(channel) / "brief.json") == saved


@pytest.mark.parametrize("payload", [None, b"{broken", b"\xff", b"{}", b"null", b"12", b'"words"'])
def test_recorded_survives_missing_corrupt_and_non_list_words(channel, tmp_path, payload):
    data = make(channel, judge=Scripts())
    project = tmp_path / "project"
    project.mkdir()
    if payload is not None:
        (project / "words.json").write_bytes(payload)
    brief.recorded(channel["slug"], project, {"brief": data["date"], "item": 1})
    item = pipeline._read(folder(channel) / "brief.json")["items"][0]
    assert item["status"] == "recorded" and item["project"] == str(project)
    assert item["take"] == {**EMPTY, "script_words": len(SCRIPT.split())}


def test_recorded_survives_unreadable_words(channel, tmp_path, monkeypatch):
    data = make(channel, judge=Scripts())
    read = brief._read

    def unreadable(path, default=None):
        if path.name == "words.json":
            raise OSError("cannot read transcript")
        return read(path, default)
    monkeypatch.setattr(brief, "_read", unreadable)
    brief.recorded(channel["slug"], tmp_path, {"brief": data["date"], "item": 1})
    assert pipeline._read(folder(channel) / "brief.json")["items"][0]["status"] == "recorded"


@pytest.mark.parametrize("count", [0, 1, 2])
def test_voice_needs_three_takes(channel, count):
    save(channel, *(take(i, hook_kept=False, kept=.2) for i in range(count)), {"n": 9, "status": "recorded"})
    assert brief.voice(channel["slug"], NOW) == []


def test_voice_reports_all_signals_in_order(channel):
    save(channel, *(take(i, hook=f"Hook {i}", words=60, script_words=100, seconds=30,
                        kept=.5, hook_kept=False, opening=f"Opening {i}") for i in range(1, 4)))
    assert brief.voice(channel["slug"], NOW) == [
        "The owner speaks about 2.0 words a second. Aim for about 70 spoken words.",
        "Recorded takes ran about 60% of the script length.",
        "The owner rewrote 3 of the last 3 hooks when recording.",
        "The owner kept about 50% of the script's words. Write closer to how they talk.",
        "Script hook: Hook 3 | Said instead: Opening 3",
        "Script hook: Hook 2 | Said instead: Opening 2",
        "Script hook: Hook 1 | Said instead: Opening 1",
    ]


def test_voice_rate_uses_median_and_ignores_short_takes(channel):
    save(channel, take(1, words=10, seconds=5), take(2, words=30, seconds=10),
         take(3, words=10_000, seconds=100), take(4, words=100_000, seconds=4.9))
    assert brief.voice(channel["slug"], NOW)[0] == (
        "The owner speaks about 3.0 words a second. Aim for about 105 spoken words.")
    save(channel, take(1, seconds=4.9), take(2, seconds=0), take(3, seconds=1))
    assert brief.voice(channel["slug"], NOW) == []


@pytest.mark.parametrize("count,expected", [(84, 84), (85, None), (100, None), (115, None), (116, 116)])
def test_voice_length_thresholds(channel, count, expected):
    save(channel, take(1, words=count, seconds=0), take(2, words=count, seconds=0),
         take(3, words=10_000, seconds=0), take(4, script_words=0, seconds=0))
    assert brief.voice(channel["slug"], NOW) == (
        [f"Recorded takes ran about {expected}% of the script length."] if expected is not None else [])


def test_voice_has_no_length_signal_without_script_counts(channel):
    save(channel, *(take(i, script_words=0, seconds=0) for i in range(3)))
    assert brief.voice(channel["slug"], NOW) == []


@pytest.mark.parametrize("kept,expected", [(.59, 59), (.6, None), (.61, None)])
def test_voice_kept_threshold_uses_median(channel, kept, expected):
    save(channel, take(1, kept=kept, seconds=0), take(2, kept=kept, seconds=0), take(3, kept=0, seconds=0))
    assert brief.voice(channel["slug"], NOW) == (
        [f"The owner kept about {expected}% of the script's words. Write closer to how they talk."]
        if expected is not None else [])


@pytest.mark.parametrize("kept", [0, 1, 2, 3, 4])
def test_voice_hooks_threshold_is_strictly_less_than_half(channel, kept):
    save(channel, *(take(i, seconds=0, hook_kept=i < kept) for i in range(4)))
    lines = brief.voice(channel["slug"], NOW)
    assert [line for line in lines if line.startswith("The owner rewrote")] == (
        [f"The owner rewrote {4 - kept} of the last 4 hooks when recording."] if kept < 2 else [])
    assert len([line for line in lines if line.startswith("Script hook:")]) == min(3, 4 - kept)


def test_voice_openings_sort_by_date_then_item_and_collapse_text(channel):
    save(channel, take(1, hook="yesterday", hook_kept=False), day="2026-11-05")
    save(channel, take(99, hook="older", hook_kept=False), day="2026-11-04")
    save(channel, take(2, hook="  second\n hook  ", opening="  said\t second ", hook_kept=False),
         take(10, hook=" long\t" * 40, opening=" said\n" * 40, hook_kept=False), take(20))
    assert [line for line in brief.voice(channel["slug"], NOW) if line.startswith("Script hook:")] == [
        f"Script hook: {('long ' * 40)[:120]} | Said instead: {('said ' * 40)[:120]}",
        "Script hook: second hook | Said instead: said second",
        "Script hook: yesterday | Said instead: Spoken opening",
    ]


def test_voice_window_uses_channel_local_dates_and_skips_bad_briefs(channel):
    now = NOW.replace(hour=7, minute=59) + timedelta(days=1)
    save(channel, take(), day="2026-11-06")
    save(channel, take(), day="2026-10-08")
    save(channel, take(hook="too old", hook_kept=False), day="2026-10-07")
    save(channel, take(hook="tomorrow", hook_kept=False), day="2026-11-07")
    save(channel, take(), day="not-a-date")
    for day, payload in (("2026-11-05", b"{bad"), ("2026-11-04", b"null"), ("2026-11-03", b"[]"),
                         ("2026-11-02", b'{"items": null}'), ("2026-11-01", b"\xff")):
        path = folder(channel, day) / "brief.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
    assert brief.voice(channel["slug"], now) == []
    save(channel, take(), day="2026-10-09")
    assert brief.voice(channel["slug"], now) == [
        "The owner speaks about 2.5 words a second. Aim for about 88 spoken words."]


def test_prompt_includes_takes_as_guidance_at_the_requested_time(channel):
    save(channel, *(take(i, hook="literal {TAKES}", hook_kept=False) for i in range(3)), day="2026-10-08")
    scripts = Scripts()
    make(channel, judge=scripts)
    prompt = scripts.calls[0][1]
    expected = "\n".join("- " + line for line in brief.voice(channel["slug"], NOW))
    assert f"Prior title lessons\nNone yet.\n\nHow the owner records\n{expected}\n" in prompt
    assert "Script hook: literal {TAKES}" in prompt
    assert "Prior title lessons and recording notes are guidance, not facts about this item." in prompt


def test_prompt_has_no_takes_yet(channel):
    scripts = Scripts()
    make(channel, judge=scripts)
    assert "How the owner records\nNone yet.\n" in scripts.calls[0][1]


def test_page_shows_the_comparison_only_for_recorded_items(channel):
    data = make(channel, judge=Scripts())
    item = data["items"][0]
    item["take"] = {**EMPTY, "kept": .72, "seconds": 41.0, "opening": "<script>bad</script>"}
    brief._page(folder(channel), channel, data)
    assert "Recorded" not in (folder(channel) / "brief.html").read_text(encoding="utf-8")
    item["status"] = "recorded"
    brief._page(folder(channel), channel, data)
    page = (folder(channel) / "brief.html").read_text(encoding="utf-8")
    assert "<p>Recorded. Kept 72% of the script in 41 seconds.</p>" in page and "<script>bad</script>" not in page
    del item["take"]
    brief._page(folder(channel), channel, data)
    assert "<p>Recorded</p>" in (folder(channel) / "brief.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("count", [0, 2, 3])
def test_cli_takes_prints_notes_without_making_a_brief(channel, monkeypatch, capsys, count):
    save(channel, *(take(i) for i in range(count)))
    before = (folder(channel) / "brief.json").read_bytes()
    monkeypatch.setattr(brief, "make", lambda *a, **kw: pytest.fail("made a brief"))
    monkeypatch.setattr(brief, "answer", lambda *a, **kw: pytest.fail("saved an answer"))
    monkeypatch.setattr(command.webbrowser, "open", lambda *a: pytest.fail("opened a page"))
    assert command.run(["brief", channel["slug"], "--takes", "--date", "2026-11-06", "--open"]) == 0
    assert capsys.readouterr().out == (
        "The owner speaks about 2.5 words a second. Aim for about 88 spoken words.\n" if count == 3
        else "Fewer than 3 recorded takes in the last 30 days.\n")
    assert (folder(channel) / "brief.json").read_bytes() == before
    assert not (folder(channel) / "brief.html").exists()
