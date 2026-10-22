"""Frozen pre-P4 field order, plus byte snapshots of every persisted v1 fixture.

The suite-wide guard also checks EDLs constructed by the existing render goldens
and fixture factories. It does not replace or weaken their render assertions.
"""

import hashlib
import json
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from myzing.schemas import Breakdown, EDL, StyleProfile

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests/fixtures/composition-v2/v1-fixture-bytes.json"

# Deliberately frozen here, independent of dataclass field discovery/serializers.
V1_FIELDS = {
    "EDL": "clips captions audio width height fps schema_version",
    "Clip": "src src_in src_out timeline_start",
    "CaptionSpec": "text start end position all_caps word_timed words",
    "AudioTrack": "src kind timeline_start gain_db duck_under_speech",
    "Word": "text start end confidence timing",
    "Shot": "index start end keyframe",
    "CaptionEvent": "text start end position all_caps words_visible confidence",
    "AudioLayout": "has_music music_confidence has_voiceover speech_ratio loudness_curve",
    "TransitionObservation": "kind start end frame_pair_count audio_aligned audio_onset_delta",
    "VideoMeta": "source_url platform author title duration width height fps media_path",
    "Breakdown": "meta shots words captions audio avg_shot_duration cuts_per_10s transitions warnings provenance judgment schema_version",
    "StatSummary": "median p25 p75 n",
    "StyleProfile": "name source_slugs genre platform duration shot_duration cuts_per_10s_curve time_to_first_cut time_to_first_word time_to_first_caption caption_all_caps_rate caption_words_visible_mode speech_ratio music_present_rate transition_kind_counts judged unjudged_source_slugs warnings provenance schema_version",
}


def frozen_value(value):
    if is_dataclass(value):
        names = V1_FIELDS[type(value).__name__].split()
        assert [f.name for f in fields(value)] == names, "v1 field shape/order changed"
        value = {name: getattr(value, name) for name in names}
    if isinstance(value, dict):
        return {k: frozen_value(v) for k, v in value.items() if not (k == "timing" and v is None)}
    if isinstance(value, list):
        return [frozen_value(v) for v in value]
    return value


def assert_v1_bytes(value, actual):
    expected = json.dumps(frozen_value(value), ensure_ascii=False, indent=2).encode("utf-8")
    assert json.dumps(actual, ensure_ascii=False, indent=2).encode("utf-8") == expected


def fixture_documents():
    """Discover actual contracts, including contracts nested in golden envelopes."""
    roots = (ROOT / "tools/eval", ROOT / "presets", ROOT / "src/myzing/_data/presets")

    def visit(value, pointer):
        if isinstance(value, dict):
            kind = None
            if isinstance(value.get("meta"), dict) and "source_url" in value["meta"]:
                kind = "Breakdown"
            elif "clips" in value and isinstance(value["clips"], list) and "fps" in value:
                kind = "EDL"
            elif "source_slugs" in value and "shot_duration" in value:
                kind = "StyleProfile"
            if kind and value.get("schema_version", 1) == 1:
                yield pointer, kind, value
            else:
                for key, item in value.items():
                    yield from visit(item, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                yield from visit(item, pointer + f"/{i}")

    for root in roots:
        for path in sorted(root.rglob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for pointer, kind, value in visit(data, ""):
                yield path.relative_to(ROOT).as_posix() + "#" + pointer, kind, value


def test_all_persisted_v1_fixtures_match_pre_p4_byte_snapshots():
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["documents"]
    seen = set()
    for name, kind, value in fixture_documents():
        cls = {"EDL": EDL, "Breakdown": Breakdown, "StyleProfile": StyleProfile}[kind]
        obj = cls.from_dict(value)
        assert_v1_bytes(obj, obj.to_dict())
        payload = obj.to_json(indent=2).encode("utf-8")
        # Generated optional goldens also use the frozen oracle; checked-in
        # documents additionally have a hash recorded with the base serializer.
        if name in expected:
            assert hashlib.sha256(payload).hexdigest() == expected[name]["sha256"], name
            seen.add(name)
        assert cls.from_json(payload.decode("utf-8")).to_json(indent=2).encode("utf-8") == payload
    assert seen == set(expected), "a frozen v1 fixture was omitted or removed"


def test_frozen_oracle_detects_new_fields_or_changed_order():
    edl = EDL()
    payload = edl.to_dict()
    payload["new_optional_field"] = None
    with pytest.raises(AssertionError):
        assert_v1_bytes(edl, payload)
    with pytest.raises(AssertionError):
        assert_v1_bytes(edl, dict(reversed(list(edl.to_dict().items()))))
