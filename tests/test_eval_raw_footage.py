from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from tools.eval.make_goldens import (
    FILLER_FIXTURE,
    RAW_FOOTAGE_CASES,
    generate_raw_footage_goldens,
)
from tools.eval.raw_footage import (
    measurement_from_raw_result,
    score_raw_footage,
)


@pytest.mark.ffmpeg
def test_generate_raw_footage_goldens_with_exact_truth(
    tmp_path: Path,
) -> None:
    directories = generate_raw_footage_goldens(tmp_path / "raw goldens")

    assert [directory.name for directory in directories] == [
        case["directory"] for case in RAW_FOOTAGE_CASES
    ]
    truth_by_id = {}
    for directory in directories:
        truth = json.loads(
            (directory / "raw-footage-truth.json").read_text(
                encoding="utf-8"
            )
        )
        truth_by_id[truth["fixture_id"]] = truth
        media = directory / truth["media"]
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(media),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(json.loads(probe.stdout)["format"]["duration"])
        assert duration == pytest.approx(truth["duration"], abs=0.02)

    assert truth_by_id["dead-air"]["raw_footage"] == {
        "dead_air_spans": [
            {"start": 1.0, "end": 3.0}
        ],
        "filler_words": [],
        "repeated_takes": [],
    }
    assert truth_by_id["filler-word"]["raw_footage"]["filler_words"] == [
        {"word": "like", "start": 1.4}
    ]
    assert truth_by_id["repeated-take"]["raw_footage"][
        "repeated_takes"
    ] == [
        {
            "first_start": 0.0,
            "first_end": 1.0,
            "second_start": 1.5,
            "second_end": 2.5,
            "similarity": 1.0,
        }
    ]


def test_filler_fixture_has_pinned_public_domain_provenance() -> None:
    provenance = json.loads(
        FILLER_FIXTURE.with_name("provenance.json").read_text(
            encoding="utf-8"
        )
    )

    assert provenance["license"]["spdx"] == "CC-PDDC"
    assert provenance["filler_artifact"]["sha256"] == hashlib.sha256(
        FILLER_FIXTURE.read_bytes()
    ).hexdigest()
    with wave.open(str(FILLER_FIXTURE), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16_000
        assert audio.getnframes() == 4_000


@pytest.mark.ffmpeg
def test_raw_footage_scorer_passes_exact_measurements(
    tmp_path: Path,
) -> None:
    directories = generate_raw_footage_goldens(tmp_path / "raw goldens")

    for directory in directories:
        truth = json.loads(
            (directory / "raw-footage-truth.json").read_text(
                encoding="utf-8"
            )
        )
        result = score_raw_footage(truth, truth["raw_footage"])

        assert result["passed"] is True
        assert result["dead_air"]["passed"] is True
        assert result["filler_words"]["passed"] is True
        assert result["repeated_takes"]["passed"] is True


def test_raw_result_adapter_matches_the_landed_measurement_shape() -> None:
    from myzing.study.raw import DeadAir, RawResult, RepeatedTake

    raw_result = RawResult(
        dead_air=[DeadAir(1.0, 3.0)],
        filler_locations=[("like", 3.2)],
        repeated_takes=[
            RepeatedTake(
                first_start=0.0,
                first_end=1.0,
                second_start=3.5,
                second_end=4.5,
                similarity=1.0,
                text="that the ripening figs",
            )
        ],
    )
    truth = {
        "fixture_id": "raw-result-seam",
        "raw_footage": {
            "dead_air_spans": [{"start": 1.0, "end": 3.0}],
            "filler_words": [{"word": "like", "start": 3.2}],
            "repeated_takes": [
                {
                    "first_start": 0.0,
                    "first_end": 1.0,
                    "second_start": 3.5,
                    "second_end": 4.5,
                    "similarity": 1.0,
                }
            ],
        },
    }

    measurement = measurement_from_raw_result(raw_result)

    assert score_raw_footage(truth, measurement)["passed"] is True


@pytest.mark.ffmpeg
@pytest.mark.parametrize(
    ("fixture_id", "mutation", "target"),
    [
        (
            "dead-air",
            lambda measurement: measurement["dead_air_spans"][0].update(
                start=1.4
            ),
            ("dead_air", "timing"),
        ),
        (
            "filler-word",
            lambda measurement: measurement["filler_words"][0].update(
                word="um"
            ),
            ("filler_words", "identity"),
        ),
        (
            "repeated-take",
            lambda measurement: measurement["repeated_takes"][0].update(
                similarity=0.5
            ),
            ("repeated_takes", "similarity"),
        ),
    ],
    ids=["dead-air-timing", "filler-identity", "repeat-similarity"],
)
def test_raw_footage_mutations_fail_only_the_target_dimension(
    tmp_path: Path,
    fixture_id: str,
    mutation,
    target: tuple[str, str],
) -> None:
    directories = generate_raw_footage_goldens(tmp_path / "raw goldens")
    truths = {
        truth["fixture_id"]: truth
        for directory in directories
        for truth in [
            json.loads(
                (directory / "raw-footage-truth.json").read_text(
                    encoding="utf-8"
                )
            )
        ]
    }
    truth = truths[fixture_id]
    measurement = copy.deepcopy(truth["raw_footage"])
    mutation(measurement)

    result = score_raw_footage(truth, measurement)

    assert result["passed"] is False
    assert result[target[0]][target[1]]["passed"] is False
    for family in {"dead_air", "filler_words", "repeated_takes"} - {
        target[0]
    }:
        assert result[family]["passed"] is True
