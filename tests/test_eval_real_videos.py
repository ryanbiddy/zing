from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing.schemas import Breakdown, Shot, VideoMeta
from tools.eval import backfill_frames
from tools.eval.freeze_real_videos import (
    DEFAULT_MANIFEST,
    RegressionFreezeError,
    _portable_breakdown,
    freeze_real_videos,
)


CHECKED_IN = ROOT / "tools" / "eval" / "real_videos"
CQ13_MANIFEST = CHECKED_IN / "manifest-cq13.json"


def _sha256(path: Path) -> str:
    """Normalized text hash, matching ``freeze_real_videos._text_sha256``.

    ``read_text`` decodes with universal newlines, so CRLF worktrees
    (Windows checkouts with ``core.autocrlf``) and LF checkouts (CI) hash
    identically: every text pin is the sha256 of the LF-normalized UTF-8
    text. Do not "simplify" this to ``read_bytes`` — that would make the
    pins line-ending dependent and break on one side or the other. Binary
    artifacts (keyframe JPEGs) are hashed raw where they are checked.
    """
    content = path.read_text(encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class FakeBenchmarkAdapter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.artifacts: dict[str, Path] = {}

    def __call__(self, media_path: Path) -> Breakdown:
        artifact_directory = self.root / media_path.stem
        frames = artifact_directory / "frames"
        frames.mkdir(parents=True)
        (artifact_directory / "media.mp4").write_bytes(media_path.read_bytes())
        (frames / "shot_000.jpg").write_bytes(b"jpeg fixture")
        self.artifacts[str(media_path.resolve())] = artifact_directory
        return Breakdown(
            meta=VideoMeta(
                source_url=str(media_path.resolve()),
                platform="file",
                title=media_path.stem,
                duration=45.0,
                width=1080,
                height=1920,
                fps=30.0,
                media_path="media.mp4",
            ),
            shots=[
                Shot(
                    index=0,
                    start=0.0,
                    end=45.0,
                    keyframe="frames/shot_000.jpg",
                )
            ],
            provenance={"measured_at": "2026-07-18T00:00:00+00:00"},
        )

    def artifact_directory_for(self, media_path: Path) -> Path | None:
        return self.artifacts.get(str(media_path.resolve()))

    def performance_for(self, media_path: Path) -> dict:
        return {
            "available": True,
            "stages": {"ingest": 1.0, "render": 2.0},
        }


def test_portable_breakdown_derives_platform_from_canonical_source() -> None:
    measured = Breakdown(
        meta=VideoMeta(
            source_url="C:/staged/media.mp4",
            platform="file",
        )
    )
    case = {
        "source_url": "https://x.com/creator/status/1234567890",
        "creator": "Creator",
        "title": "Long-form post",
        "fixture_id": "x-long-form",
        "video_id": "1234567890",
        "role": "reference",
        "truth_section": "X VIDEO",
    }

    frozen = _portable_breakdown(measured, case)

    assert frozen.meta.platform == "x"


def test_freeze_real_videos_writes_portable_outputs_and_provenance(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        (media_root / case["media_filename"]).write_bytes(
            case["video_id"].encode("ascii")
        )
    output = tmp_path / "frozen"
    adapter = FakeBenchmarkAdapter(tmp_path / "study")

    directories = freeze_real_videos(
        media_root,
        output,
        DEFAULT_MANIFEST,
        adapter=adapter,
        ffmpeg="not-installed-ffmpeg",
    )

    assert [path.name for path in directories] == [
        "reference-cleo-antarctica",
        "raw-editing-practice",
    ]
    reference = json.loads(
        (directories[0] / "breakdown.json").read_text(encoding="utf-8")
    )
    assert reference["meta"]["source_url"].endswith("/shorts/nlGYV0bmddI")
    assert reference["meta"]["platform"] == "youtube"
    assert reference["meta"]["media_path"] == ""
    assert reference["shots"][0]["keyframe"] == ""
    assert not (directories[0] / "frames").exists()
    provenance = json.loads(
        (directories[0] / "provenance.json").read_text(encoding="utf-8")
    )
    assert len(provenance["source_media"]["sha256"]) == 64
    assert len(provenance["measured_media"]["sha256"]) == 64
    assert provenance["performance"]["stages"]["render"] == 2.0
    assert provenance["artifacts"].keys() == {"breakdown.json"}

    with pytest.raises(RegressionFreezeError, match="refusing to replace"):
        freeze_real_videos(
            media_root,
            output,
            DEFAULT_MANIFEST,
            adapter=adapter,
            ffmpeg="not-installed-ffmpeg",
        )


def test_freeze_supports_measurement_only_cases_with_rights_provenance(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    (media_root / "measurement-only.mp4").write_bytes(b"measurement-only")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "media_policy": {
                    "committed": False,
                    "derived_frames_committed": False,
                },
                "source_acquisition": {
                    "tool": "yt-dlp",
                    "version": "2026.7.4",
                    "merge_output_format": "mp4",
                    "no_playlist": True,
                },
                "cases": [
                    {
                        "fixture_id": "measurement-only",
                        "role": "landscape-long-form",
                        "video_id": "measurement-only",
                        "selected_format_ids": ["480p"],
                        "media_filename": "measurement-only.mp4",
                        "source_url": "https://video.example/measurement-only",
                        "title": "Measurement only",
                        "creator": "Example creator",
                        "human_truth": {
                            "available": False,
                            "reason": (
                                "C-Q13 adds measured coverage; no independent "
                                "human annotation was commissioned."
                            ),
                        },
                        "rights": {
                            "label": "Creative Commons Attribution 3.0",
                            "spdx": "CC-BY-3.0",
                            "evidence_url": "https://video.example/license",
                            "attribution": "Example creator",
                            "limitations": "License evidence checked at freeze time.",
                        },
                        "acquisition": {
                            "format_selector": "480p",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "frozen"
    adapter = FakeBenchmarkAdapter(tmp_path / "study")

    directories = freeze_real_videos(
        media_root,
        output,
        manifest_path,
        adapter=adapter,
        ffmpeg="not-installed-ffmpeg",
    )

    breakdown = json.loads(
        (directories[0] / "breakdown.json").read_text(encoding="utf-8")
    )
    provenance = json.loads(
        (directories[0] / "provenance.json").read_text(encoding="utf-8")
    )
    fixture = breakdown["provenance"]["regression_fixture"]
    assert fixture["human_truth"]["available"] is False
    assert "truth_section" not in fixture
    assert provenance["human_truth"]["available"] is False
    assert provenance["rights"]["spdx"] == "CC-BY-3.0"
    assert provenance["source_media"]["acquisition"]["format_selector"] == "480p"
    assert provenance["source_media"]["acquisition"]["selected_format_ids"] == [
        "480p"
    ]


def test_backfill_supports_measurement_only_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_directory = tmp_path / "measurement-only"
    case_directory.mkdir()
    media = tmp_path / "measurement-only.mp4"
    media.write_bytes(b"source media")
    breakdown_path = case_directory / "breakdown.json"
    breakdown_path.write_text(
        Breakdown(
            meta=VideoMeta(
                source_url="measurement-only.mp4",
                platform="file",
                duration=1.0,
            ),
            shots=[Shot(index=0, start=0.0, end=1.0)],
        ).to_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    provenance_path = case_directory / "provenance.json"
    provenance_path.write_text(
        json.dumps(
            {
                "source_media": {
                    "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
                },
                "human_truth": {
                    "available": False,
                    "reason": "No independent annotation was commissioned.",
                },
                "normalizations": [],
                "manifest": {},
                "artifacts": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_grab(
        ffmpeg: str,
        source: Path,
        at: float,
        target: Path,
    ) -> None:
        target.write_bytes(f"{source.name}:{at}".encode("utf-8"))

    monkeypatch.setattr(backfill_frames, "grab", fake_grab)

    result = backfill_frames.backfill_case(
        case_directory,
        media,
        "ffmpeg",
        "a" * 64,
        None,
        None,
        None,
    )

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert result["frames"] == 2
    assert provenance["human_truth"]["available"] is False
    assert provenance["derived_frames"]["committed"] is True
    assert set(provenance["artifacts"]) == {
        "breakdown.json",
        "frames/hook_0s.jpg",
        "frames/shot_000.jpg",
    }


def test_checked_in_real_video_snapshots_are_self_consistent() -> None:
    """Frozen fixtures stay pinned to the documents they were frozen against.

    Pin chain (dependency order): each ``provenance.json`` pins the truth
    doc and the manifest by normalized-text sha256 (see ``_sha256`` —
    line-ending independent by construction), and its own artifacts —
    text artifacts normalized, binary keyframe JPEGs by raw bytes.
    Nothing pins the provenance files themselves, so a sanctioned
    truth-document correction (e.g. fixlist item F-16, PR #52) is
    recorded by re-pinning the ``human_truth``/``manifest`` hashes and
    keeping a ``human_truth.supersession`` record (date, superseded
    hash) — without touching the frozen measurements.
    """
    manifest_path = CHECKED_IN / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    truth_path = ROOT / manifest["human_truth"]
    required_stages = {
        "ingest",
        "shots",
        "transcribe",
        "ocr",
        "audio",
        "render",
    }

    for case in manifest["cases"]:
        case_directory = CHECKED_IN / case["fixture_id"]
        breakdown_path = case_directory / "breakdown.json"
        provenance_path = case_directory / "provenance.json"
        breakdown = Breakdown.from_json(
            breakdown_path.read_text(encoding="utf-8")
        )
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

        assert breakdown.meta.source_url == case["source_url"]
        assert breakdown.meta.media_path == ""
        # A-Q6: analysis keyframes ARE committed (small JPEGs) so visual
        # judgment criteria are scoreable; source media still is not.
        assert manifest["media_policy"]["derived_frames_committed"] is True
        assert all(
            shot.keyframe == f"frames/shot_{shot.index:03d}.jpg"
            for shot in breakdown.shots
        )
        for shot in breakdown.shots:
            assert (case_directory / shot.keyframe).is_file()
        assert provenance["derived_frames"]["committed"] is True
        assert not any(
            path.suffix.lower() in {".mp4", ".mov", ".webm"}
            for path in case_directory.rglob("*")
        )
        # every committed frame is hash-tracked in provenance artifacts
        frame_files = {
            f"frames/{p.name}"
            for p in (case_directory / "frames").iterdir()
        }
        assert frame_files == {
            rel for rel in provenance["artifacts"] if rel.startswith("frames/")
        }
        assert provenance["source_media"]["committed"] is False
        assert provenance["source_media"]["acquisition"][
            "selected_format_ids"
        ] == case["selected_format_ids"]
        assert provenance["measured_media"]["committed"] is False
        assert provenance["manifest"]["sha256"] == _sha256(manifest_path)
        assert provenance["human_truth"]["sha256"] == _sha256(truth_path)
        assert required_stages <= provenance["performance"]["stages"].keys()
        for relative, expected_hash in provenance["artifacts"].items():
            artifact = case_directory / relative
            assert artifact.is_file()
            if artifact.suffix.lower() in {".json", ".md", ".txt"}:
                assert _sha256(artifact) == expected_hash
            else:  # binary artifacts (keyframe JPEGs)
                assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_hash
        serialized = breakdown_path.read_text(encoding="utf-8")
        assert "AppData" not in serialized
        assert "zing-cq4-media" not in serialized

    raw = Breakdown.from_json(
        (
            CHECKED_IN
            / "raw-editing-practice"
            / "breakdown.json"
        ).read_text(encoding="utf-8")
    )
    raw_provenance = json.loads(
        (
            CHECKED_IN
            / "raw-editing-practice"
            / "provenance.json"
        ).read_text(encoding="utf-8")
    )
    assert raw.cuts_per_10s[2] == 15.0
    assert "not zero-cut raw footage" in raw_provenance["human_truth"]["caveat"]


def test_checked_in_cq13_snapshots_are_self_consistent() -> None:
    manifest = json.loads(CQ13_MANIFEST.read_text(encoding="utf-8"))
    required_stages = {
        "ingest",
        "shots",
        "transcribe",
        "ocr",
        "audio",
        "render",
    }

    for case in manifest["cases"]:
        case_directory = CHECKED_IN / case["fixture_id"]
        breakdown_path = case_directory / "breakdown.json"
        provenance_path = case_directory / "provenance.json"
        breakdown = Breakdown.from_json(
            breakdown_path.read_text(encoding="utf-8")
        )
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

        expected = case["expected_media"]
        assert breakdown.meta.source_url == case["source_url"]
        assert breakdown.meta.media_path == ""
        assert breakdown.meta.width == expected["width"]
        assert breakdown.meta.height == expected["height"]
        assert breakdown.meta.duration == pytest.approx(
            expected["duration_seconds"],
            abs=0.02,
        )
        assert all(
            shot.keyframe == f"frames/shot_{shot.index:03d}.jpg"
            for shot in breakdown.shots
        )
        assert provenance["human_truth"] == case["human_truth"]
        assert provenance["rights"] == case["rights"]
        assert provenance["schema_version"] == 2
        assert provenance["source_media"]["committed"] is False
        assert len(provenance["source_media"]["sha256"]) == 64
        assert provenance["source_media"]["acquisition"][
            "format_selector"
        ] == case["acquisition"]["format_selector"]
        assert provenance["source_media"]["acquisition"][
            "selected_format_ids"
        ] == case["selected_format_ids"]
        assert provenance["manifest"]["sha256"] == _sha256(CQ13_MANIFEST)
        source_document = ROOT / manifest["source_document"]
        assert provenance["source_document"] == {
            "path": manifest["source_document"],
            "sha256": _sha256(source_document),
        }
        assert provenance["derived_frames"]["committed"] is True
        assert required_stages <= provenance["performance"]["stages"].keys()
        assert not any(
            path.suffix.lower() in {".mp4", ".mov", ".webm"}
            for path in case_directory.rglob("*")
        )
        frame_files = {
            f"frames/{path.name}"
            for path in (case_directory / "frames").iterdir()
        }
        assert frame_files == {
            relative
            for relative in provenance["artifacts"]
            if relative.startswith("frames/")
        }
        for relative, expected_hash in provenance["artifacts"].items():
            artifact = case_directory / relative
            assert artifact.is_file()
            if artifact.suffix.lower() in {".json", ".md", ".txt"}:
                assert _sha256(artifact) == expected_hash
            else:
                assert (
                    hashlib.sha256(artifact.read_bytes()).hexdigest()
                    == expected_hash
                )
