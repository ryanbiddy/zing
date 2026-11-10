"""The release must include every change above the previous release."""
import re
import tomllib

import pytest

from test_release_packaging import ROOT, load


def test_current_release_has_no_unfolded_notes():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert re.search(rf"^## {re.escape(version)}$", text, re.M)
    unreleased = re.search(r"^## Unreleased\n(.*?)(?=^## |\Z)", text, re.M | re.S).group(1)
    assert not unreleased.strip(), "Fold Unreleased into the current release before publishing."
    section = load("release_notes").notes(version, text)
    end = int(re.search(r"PRs #\d+ through #(\d+)", section).group(1))
    scope = text[:text.index(section) + len(section)]
    assert end >= max(map(int, re.findall(r"#(\d+)\b", scope)))


@pytest.mark.parametrize("item", [
    "Keep original files when a copied match project omits them",
    "Reject invalid review ports",
    "Fit factory text cards",
    "Tighten automatic 9:16 match crops",
    "Keep match projects resumable",
    "zing explain --against",
    "Keep factory captions clear of faces",
    "zing factory serve",
    "Let moment suggestions cross sentence pauses",
    "Check supplied captions with up to five samples",
    "Group factory captions by phrase and pause",
    "Keep full meme and still topics",
    "Keep review headers compact",
    "Keep text cards and slides whole",
    "Add a long episode path",
    "PRs #401 through #578",
])
def test_rc1_includes_november_9_changes(item):
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert item in load("release_notes").notes("1.0.0rc1", text)


@pytest.mark.parametrize("text", [
    "## Unreleased\n- New fix #576\n## 1.0.0rc1\nPRs #401 through #575\n## 0.1.0\nOld.\n",
    "## Unreleased\n## 1.0.0rc1\nPRs #401 through #557\n- Fix #575\n## 0.1.0\nOld.\n",
])
def test_extraction_rejects_unfolded_or_truncated_release(text):
    with pytest.raises(ValueError):
        load("release_notes").notes("1.0.0rc1", text)


def test_previous_release_prs_do_not_extend_current_range():
    text = "## Unreleased\n## 1.0.0rc1\nPRs #401 through #575\n- Fix #575\n## 0.1.0\n- Old #900\n"
    assert "Old" not in load("release_notes").notes("1.0.0rc1", text)
