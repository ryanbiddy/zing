from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from myzing.schemas import Breakdown, Shot, VideoMeta
from tools.eval.freeze_real_videos import (
    DEFAULT_MANIFEST,
    RegressionFreezeError,
    freeze_real_videos,
)


CHECKED_IN = ROOT / "tools" / "eval" / "real_videos"


def _sha256(path: Path) -> str:
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


def test_checked_in_real_video_snapshots_are_self_consistent() -> None:
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
        assert all(not shot.keyframe for shot in breakdown.shots)
        assert not any(
            path.suffix.lower() in {".mp4", ".mov", ".webm", ".jpg", ".png"}
            for path in case_directory.rglob("*")
        )
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
            assert _sha256(artifact) == expected_hash
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
