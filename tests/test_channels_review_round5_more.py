"""Round-5 review fixes that were left after the lane changes: brief pages, kit index, network ledger."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from myzing.channels import brief, kit
from myzing.factory import network

from test_channels_brief import NOW, Scripts, channel, folder, local, make  # noqa: F401


def test_a_brief_without_its_page_is_due_and_made_again(channel):
    make(channel, judge=Scripts())
    day = folder(channel)
    assert not brief.due(channel["slug"], NOW)
    (day / "brief.html").unlink()
    assert brief.due(channel["slug"], NOW)
    make(channel, judge=Scripts())
    assert (day / "brief.html").is_file() and not brief.due(channel["slug"], NOW)
    assert not list(day.parent.rglob(".*.tmp"))


def _kit(root, name, slot, *, copy=True):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "post.json").write_text(json.dumps({"slot": slot, "youtube_title": name}), encoding="utf-8")
    (folder / "video.mp4").write_bytes(b"video")
    (folder / "youtube.txt").write_text(f"{name}\n\nDescription", encoding="utf-8")
    if copy:
        for field in kit.TEXTS:
            if field != "youtube":
                (folder / f"{field}.txt").write_text(f"{field} copy", encoding="utf-8")
    return folder


def test_one_damaged_kit_never_hides_the_others(tmp_path):
    out = tmp_path / "kits"
    slot = datetime(2026, 11, 7, 18, tzinfo=timezone.utc).isoformat()
    _kit(out, "good", slot)
    _kit(out, "no-copy", slot, copy=False)
    (_kit(out, "bad-slot", slot) / "post.json").write_text('{"slot": "soon"}', encoding="utf-8")
    (_kit(out, "torn", slot) / "post.json").write_text('{"slot": ', encoding="utf-8")
    page = kit._index(out, {"name": "Test", "sources": []}, []).read_text(encoding="utf-8")
    assert "<h2>good</h2>" in page and page.count("<article>") == 1
    for name in ("no-copy", "bad-slot", "torn"):
        assert f"Skipped a damaged kit: {name}" in page


def test_network_summary_skips_torn_and_odd_ledger_lines(tmp_path):
    (tmp_path / "factory.json").write_text("{}", encoding="utf-8")
    good = {"host": "example.org", "purpose": "news feed", "bytes": 10}
    (tmp_path / "network.jsonl").write_text(
        json.dumps(good) + "\n" + '{"host": "torn", "purp' + "\n" + json.dumps({"host": "x"}) + "\n[1, 2]\n",
        encoding="utf-8")
    result = network.summary(tmp_path)
    assert result["requests"] == 1 and result["purposes"] == {"news feed": 1}
