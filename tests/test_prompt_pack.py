"""Prompt pack: integrity of the shipped files, loader, and the CLI.

The pack defines the judgment contract (frontmatter required_keys) that
save_judgment enforces — so the pack's own worked example must satisfy it,
and the shipped files must keep parsing. These tests run against the REAL
repo prompts/, not fixtures: a broken pack is a broken product.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from myzing import mcp_server, prompt_pack, storage
from myzing.schemas import Breakdown, VideoMeta

STUDY_REQUIRED = {"hook", "beats", "caption_style", "why_it_works"}


@pytest.fixture
def real_pack(monkeypatch):
    monkeypatch.delenv(prompt_pack.PROMPTS_DIR_ENV, raising=False)


# -- shipped pack integrity --------------------------------------------------

def test_pack_ships_expected_prompts(real_pack):
    assert prompt_pack.available_prompts() == ["compare", "direct", "study", "taste"]


def test_compare_frontmatter_and_example_contract(real_pack, zing_workspace):
    """S2: compare.md's own example must pass save_judgment(section='compare')."""
    meta, text = prompt_pack.load_prompt("compare")
    assert re.fullmatch(r"\d+\.\d+\.\d+", meta["version"])
    assert set(meta["required_keys"]) == {
        "fit", "rubric_scores", "deviations", "overall",
    }
    example = json.loads(
        re.search(
            r"<example_judgment>\s*(\{.*?\})\s*</example_judgment>", text, re.DOTALL
        ).group(1)
    )
    b = Breakdown(meta=VideoMeta(source_url="https://youtu.be/c", platform="youtube"))
    storage.save_breakdown(b, slug="youtube-c")
    result = mcp_server.h_save_judgment(
        "youtube-c", example, section="compare", model="test"
    )
    assert result["ok"] is True, result.get("error")
    assert result["prompt_version"] == meta["version"]
    # the example must practice band honesty: both numbers cited
    assert "vs profile" in json.dumps(example) or "vs band" in json.dumps(example)
    # B-Q13: rubric scores use the genre rubric's 1-5 scale with real
    # INDEX criterion ids — never study.md's 0-2 hook anchors
    numeric = [
        s["score"] for s in example["rubric_scores"]
        if isinstance(s["score"], int)
    ]
    assert numeric and all(1 <= s <= 5 for s in numeric)
    assert any(s > 2 for s in numeric), "scores that never exceed 2 suggest the 0-2 scale"
    assert all(
        s["criterion_id"].startswith("G-") for s in example["rubric_scores"]
    )


def test_study_frontmatter_contract(real_pack):
    meta, text = prompt_pack.load_prompt("study")
    assert meta["name"] == "study"
    assert re.fullmatch(r"\d+\.\d+\.\d+", meta["version"])
    assert set(meta["required_keys"]) == STUDY_REQUIRED
    assert meta["description"]
    assert len(text.splitlines()) < 500  # skills guidance: stay lean


def test_study_v04_transitions_and_tools_present(real_pack):
    """B-Q11: transitions vocabulary + honest-states rule + thumbs tool."""
    meta, text = prompt_pack.load_prompt("study")
    flat = " ".join(text.split())  # markdown wraps phrases across lines
    assert tuple(int(p) for p in meta["version"].split(".")) >= (0, 4, 0)
    assert "`transitions[]`" in flat
    assert "detector ran, found none" in flat          # three-states rule
    assert "no per-event confidence" in flat.lower()
    assert "audio_onset_delta" in flat
    assert "generate_thumbnails" in flat               # tools overview


def test_study_v02_wizard_of_oz_fixes_present(real_pack):
    """B-Q6: the four v0.2 additions from WIZARD-OF-OZ-2026-07-18 §4."""
    meta, text = prompt_pack.load_prompt("study")
    assert tuple(int(p) for p in meta["version"].split(".")) >= (0, 2, 0)
    assert "`curiosity_gap`" in text          # 1: open-loop hook label
    assert "sampling" in text.lower()         # 2: sync bounded by OCR resolution
    assert "watermark" in text.lower()        # 3: multi-layer OCR separation
    assert "`retake`" in text                 # 4: raw-footage beat vocabulary
    assert "## Changelog" in text


def test_direct_v1_contract(real_pack, zing_workspace):
    """S3: direct.md is the real contract now — its example must pass
    save_judgment(section='direct') and honor the plain-language rule."""
    meta, text = prompt_pack.load_prompt("direct")
    assert "STUB" not in meta["description"]
    assert tuple(int(p) for p in meta["version"].split(".")) >= (1, 0, 0)
    assert set(meta["required_keys"]) == {
        "verdict", "gaps", "shot_prompts", "keepers", "assembly_notes",
    }
    example = json.loads(
        re.search(
            r"<example_judgment>\s*(\{.*?\})\s*</example_judgment>", text, re.DOTALL
        ).group(1)
    )
    b = Breakdown(meta=VideoMeta(source_url="raw.mp4", platform="file"))
    storage.save_breakdown(b, slug="raw-take")
    result = mcp_server.h_save_judgment(
        "raw-take", example, section="direct", model="test"
    )
    assert result["ok"] is True, result.get("error")
    assert result["prompt_version"] == meta["version"]
    # gaps cite both sides and use the severity vocabulary, blocking first
    severities = [g["severity"] for g in example["gaps"]]
    assert set(severities) <= {"blocking", "important", "polish"}
    assert severities == sorted(
        severities, key=["blocking", "important", "polish"].index
    )
    for gap in example["gaps"]:
        assert gap["profile_evidence"] and gap["footage_evidence"]
    # shot prompts: plain language a human can film — no internal jargon,
    # <=2 sentences (the Lane C conformance heuristics' contract)
    for sp in example["shot_prompts"]:
        instruction = sp["instruction"]
        assert sp["closes_gap"] in {g["criterion_id"] for g in example["gaps"]}
        assert instruction.count(".") + instruction.count("!") <= 3
        for banned in ("criterion", "band", "p25", "breakdown", "profile"):
            assert banned not in instruction.lower(), (
                f"jargon '{banned}' in shot prompt"
            )
    # keepers cite measured evidence
    for keeper in example["keepers"]:
        assert "why" in keeper and keeper["end"] > keeper["start"]


def test_study_example_judgment_satisfies_its_own_contract(real_pack):
    """The worked example inside study.md must parse as JSON and carry every
    required key — otherwise the prompt teaches a shape save_judgment
    rejects."""
    meta, text = prompt_pack.load_prompt("study")
    m = re.search(
        r"<example_judgment>\s*(\{.*?\})\s*</example_judgment>", text, re.DOTALL
    )
    assert m, "study.md lost its <example_judgment> block"
    example = json.loads(m.group(1))
    assert set(meta["required_keys"]) <= set(example)
    # the example must practice what the prompt preaches:
    assert example["hook"]["evidence"], "example hook has no evidence"
    keys = list(example["hook"])
    assert keys.index("evidence") < keys.index("type"), (
        "evidence must precede verdict fields in the example"
    )


def test_example_judgment_accepted_by_save_judgment(real_pack, zing_workspace):
    """End-to-end: the shape the prompt teaches is the shape the tool takes."""
    b = Breakdown(meta=VideoMeta(source_url="https://youtu.be/x", platform="youtube"))
    storage.save_breakdown(b, slug="youtube-x")
    _meta, text = prompt_pack.load_prompt("study")
    example = json.loads(
        re.search(
            r"<example_judgment>\s*(\{.*?\})\s*</example_judgment>", text, re.DOTALL
        ).group(1)
    )
    result = mcp_server.h_save_judgment("youtube-x", example, model="test")
    assert result["ok"] is True, result.get("error")
    assert result["prompt_version"] == _meta["version"]


def test_mcp_prompts_capability_serves_the_real_pack(real_pack):
    pytest.importorskip("mcp")
    server = mcp_server.build_server()
    import anyio

    prompts = anyio.run(server.list_prompts)
    assert {p.name for p in prompts} == {"compare", "direct", "study", "taste"}


# -- CLI ---------------------------------------------------------------------

def test_cli_prints_prompt(real_pack, capsys):
    assert prompt_pack.run(["study"]) == 0
    out = capsys.readouterr().out
    assert "cannot_judge" in out and "save_judgment" in out


def test_cli_unknown_name_lists_available(real_pack, capsys):
    assert prompt_pack.run(["nope"]) == 1
    out = capsys.readouterr().out
    assert "study" in out and "direct" in out


def test_cli_no_args_shows_usage(real_pack, capsys):
    assert prompt_pack.run([]) == 2
    assert "usage" in capsys.readouterr().out


def test_cli_routes_from_zing(real_pack, capsys):
    from myzing import cli

    assert cli.main(["prompt", "study"]) == 0
    assert "Judging a Zing breakdown" in capsys.readouterr().out


def test_missing_pack_dir_is_honest(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(prompt_pack.PROMPTS_DIR_ENV, str(tmp_path / "void"))
    assert prompt_pack.run(["study"]) == 1
    assert "no prompt pack found" in capsys.readouterr().out


def test_cli_survives_legacy_windows_console(real_pack):
    """Regression: study.md contains characters (e.g. U+2192) outside
    cp1252; on a default Windows console `zing prompt study` crashed with
    UnicodeEncodeError. cli.main now replaces rather than crashes."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"  # simulate the legacy console
    proc = subprocess.run(
        [sys.executable, "-m", "myzing.cli", "prompt", "study"],
        capture_output=True,
        text=False,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    assert b"Judging a Zing breakdown" in proc.stdout


# -- the pack states a MEASURED fact, so the fact has to stay true -------------

# Lane A's own classifier for "this warning reports a problem"
# (tests/test_warning_registry.py). Reused deliberately: if the two lanes
# disagree about what counts as a problem, that disagreement should show
# up as a test failure somewhere rather than as two prose descriptions
# drifting apart.
_PROBLEM = re.compile(
    r"(skipped|failed|could not|unavailable|mismatch|ignored|inconclusive|empty:)",
    re.I,
)


def _measured_warning_split():
    """(not_a_problem, total) across the frozen real-video breakdowns."""
    import json as _json
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[1] / "tools" / "eval" / "real_videos"
    warnings = [
        w
        for path in sorted(root.glob("*/breakdown.json"))
        for w in _json.loads(path.read_text(encoding="utf-8")).get("warnings", [])
    ]
    assert warnings, "no frozen breakdowns found — this gate would pass vacuously"
    return sum(1 for w in warnings if not _PROBLEM.search(w)), len(warnings)


@pytest.mark.parametrize("prompt_name", ["study"])
def test_the_warning_ratio_the_pack_cites_is_still_true(prompt_name):
    """study.md tells judging AIs that most `warnings[]` entries are not
    gaps in the evidence, and cites "11 of 12" from the frozen set.

    Scoped to study.md deliberately. direct.md 1.3.0 states the same idea
    QUALITATIVELY ("on raw footage most entries are findings to act on")
    and carries no live number, so pinning one there would have matched
    its changelog — pinning history rather than guidance, which is the
    appearance of a gate rather than a gate.

    A number written into a prompt is a freshness claim nobody renews. So
    the claim is read back OUT of the prompt and checked against the
    breakdowns: change the corpus and this fails until the prompt is
    updated. That is the intended coupling, not brittleness — the
    alternative is guidance that quietly becomes false.
    """
    body = (
        pathlib.Path(__file__).resolve().parents[1]
        / "prompts"
        / f"{prompt_name}.md"
    ).read_text(encoding="utf-8")

    claimed = re.search(r"(\d+) of (\d+) warnings|(\d+) of (\d+) are", body)
    assert claimed, f"{prompt_name}.md no longer states the ratio it is pinned on"
    groups = [g for g in claimed.groups() if g is not None]
    claimed_other, claimed_total = int(groups[0]), int(groups[1])

    measured_other, measured_total = _measured_warning_split()
    assert (claimed_other, claimed_total) == (measured_other, measured_total), (
        f"{prompt_name}.md claims {claimed_other} of {claimed_total} warnings are "
        f"not skips/degradations; the frozen set now measures "
        f"{measured_other} of {measured_total}. Update the prompt (and its "
        f"changelog) — a judging AI is being told a number that is no longer true."
    )


def test_most_warnings_are_not_problems_which_is_why_the_guidance_exists():
    """The load-bearing claim behind the 0.5.0 rewrite, stated
    independently of the exact count: if problems ever became the
    MAJORITY, 'do not read a long warnings[] as a broken study' would be
    the wrong advice and the guidance would need rethinking, not just a
    new number."""
    other, total = _measured_warning_split()
    assert other > total / 2, (
        "most warnings are now problem-reports; study.md's advice to treat a "
        "long warnings[] as normal no longer follows from the data"
    )


# -- direct.md's caption-contamination figures -------------------------------


def _labelled_ocr_cells():
    """{slug: (duration_s, incidental_share)} from the hand-labelled set."""
    import json as _json

    root = pathlib.Path(__file__).resolve().parents[1] / "handoff" / "research"
    labels_dir, frozen_dir = root / "ocr-calibration" / "labels", root / "ocr-calibration" / "frozen"
    cells = {}
    for lab in sorted(labels_dir.glob("*.jsonl")):
        rows = [
            _json.loads(line)
            for line in lab.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        labelled = [r for r in rows if "label" in r]
        if not labelled:
            continue
        frozen = frozen_dir / f"{lab.stem}.jsonl"
        if not frozen.exists():
            continue
        head = _json.loads(
            frozen.read_text(encoding="utf-8").splitlines()[0])
        duration = head.get("provenance", {}).get("duration")
        if not duration:
            continue
        incidental = sum(1 for r in labelled if r["label"] == "incidental_text")
        cells[lab.stem] = (duration, incidental / len(labelled) * 100)
    assert cells, "no labelled OCR cells found — this gate would pass vacuously"
    return cells


def test_caption_contamination_still_does_not_track_runtime():
    """direct.md 1.4.0 tells a directing AI that a SHORT runtime is not
    evidence the caption basis is clean, and cites the labelled cells.

    Pinned to the load-bearing CLAIM rather than to the exact
    percentages: if the worst sub-60s cell ever fell below every longer
    cell, "does not track runtime" would stop following from the data and
    the guidance would need rethinking, not a new number.
    """
    cells = _labelled_ocr_cells()
    short = {s: v for s, v in cells.items() if v[0] < 60}
    long_ = {s: v for s, v in cells.items() if v[0] >= 60}
    assert short and long_, "need cells on both sides of 60s to compare"

    worst_short = max(share for _, share in short.values())
    beaten = [s for s, (_, share) in long_.items() if share < worst_short]
    assert beaten, (
        f"the worst sub-60s cell ({worst_short:.0f}% incidental) no longer "
        "exceeds ANY longer cell — direct.md 1.4.0 claims contamination does "
        "not track runtime, which would no longer follow from the data"
    )


def test_direct_md_cites_the_measured_contamination_figures():
    """Every "<N>s ... <P>%" pair in rule 4 must match the labelled data.

    Same reasoning as the warnings ratio gate: a figure written into
    guidance is a freshness claim nobody renews.

    The pairs are parsed OUT of the prompt rather than restated here.
    The first version of this test hardcoded them, so editing the prompt
    could not fail it — it asserted only that the data still measures
    what I had typed into the test, which is the vacuous-test shape
    caught in #358. Verified by editing 76% -> 61% and watching this
    fail.
    """
    body = (
        pathlib.Path(__file__).resolve().parents[1] / "prompts" / "direct.md"
    ).read_text(encoding="utf-8")
    rule4 = body.split("**Captions specifically:**", 1)[1].split("\n5.", 1)[0]

    cited = re.findall(r"(\d+)s\D{0,30}?(\d+(?:\.\d+)?)%", rule4)
    assert len(cited) >= 4, (
        f"expected the four cited cells in rule 4, parsed {cited!r} — if the "
        "wording changed, update this parser rather than deleting the gate"
    )

    cells = _labelled_ocr_cells()
    for duration_text, claimed_text in cited:
        duration, claimed = float(duration_text), float(claimed_text)
        near = [v for v in cells.values() if abs(v[0] - duration) < 1.5]
        assert near, (
            f"direct.md cites a {duration:.0f}s cell; no labelled cell is "
            "near that duration any more"
        )
        measured = near[0][1]
        assert abs(measured - claimed) < 1.0, (
            f"direct.md cites {claimed}% incidental for the {duration:.0f}s "
            f"cell; the labelled data now measures {measured:.1f}%. Update "
            "the prompt and its changelog."
        )
