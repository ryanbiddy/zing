"""Contract tests: the schemas must round-trip through JSON losslessly."""

from myzing.schemas import (
    EDL,
    AudioLayout,
    AudioTrack,
    Breakdown,
    CaptionEvent,
    CaptionSpec,
    Clip,
    Shot,
    TransitionObservation,
    VideoMeta,
    Word,
)


def _sample_breakdown() -> Breakdown:
    return Breakdown(
        meta=VideoMeta(
            source_url="https://www.tiktok.com/@x/video/1",
            platform="tiktok",
            author="x",
            title="t",
            duration=31.2,
            width=1080,
            height=1920,
            fps=30.0,
            media_path="refs/1.mp4",
        ),
        shots=[Shot(0, 0.0, 1.4, keyframe="frames/shot_0000.jpg"), Shot(1, 1.4, 3.05)],
        words=[Word("stop", 0.1, 0.32, 0.98), Word("scrolling", 0.32, 0.8)],
        captions=[CaptionEvent("STOP SCROLLING", 0.0, 0.9, "center", True, 2, 0.93)],
        audio=AudioLayout(True, 0.8, True, 0.72, [-14.0, -13.2]),
        avg_shot_duration=1.52,
        cuts_per_10s=[6.0, 7.0, 5.0],
        transitions=[
            TransitionObservation("hard_cut", 1.4, 1.4, 2, True, -0.02),
            TransitionObservation("dissolve", 3.0, 3.4),
        ],
        warnings=["ocr sampled at 4fps outside hook window"],
        provenance={"zing": "0.1.0", "detector": "adaptive@3.0"},
        judgment={"study": {"hook_type": "pattern_interrupt",
                            "_meta": {"prompt_version": "0.1"}}},
    )


def test_breakdown_roundtrip():
    b = _sample_breakdown()
    b2 = Breakdown.from_json(b.to_json())
    assert b2.to_dict() == b.to_dict()
    assert b2.shots[0].duration == b.shots[0].duration
    assert b2.shots[0].keyframe == "frames/shot_0000.jpg"
    assert b2.words[0].confidence == 0.98
    assert b2.warnings and b2.provenance["zing"] == "0.1.0"
    assert b2.transitions[0].audio_aligned and b2.transitions[0].audio_onset_delta == -0.02
    assert b2.transitions[1].kind == "dissolve" and b2.transitions[1].audio_onset_delta is None
    assert b2.judgment["study"]["hook_type"] == "pattern_interrupt"


def test_breakdown_from_old_json_defaults():
    # Pre-2026-07-18 JSON (no warnings/provenance/keyframe/confidence) must
    # still load with safe defaults.
    old = {
        "meta": {"source_url": "u", "platform": "file"},
        "shots": [{"index": 0, "start": 0.0, "end": 1.0}],
        "words": [{"text": "hi", "start": 0.0, "end": 0.2}],
    }
    b = Breakdown.from_dict(old)
    assert b.shots[0].keyframe == ""
    assert b.words[0].confidence == 1.0
    assert b.warnings == [] and b.provenance == {}


def test_edl_roundtrip():
    e = EDL(
        clips=[Clip("raw/take1.mp4", 2.0, 4.5, 0.0)],
        captions=[
            CaptionSpec(
                "stop scrolling", 0.0, 0.9,
                position="center", all_caps=True, word_timed=True,
                words=[Word("stop", 0.0, 0.3), Word("scrolling", 0.3, 0.9)],
            )
        ],
        audio=[AudioTrack("vo.wav", "voiceover", 0.0, 0.0, False),
               AudioTrack("bed.mp3", "music", 0.0, -12.0, True)],
    )
    e2 = EDL.from_json(e.to_json())
    assert e2.to_dict() == e.to_dict()
    assert e2.captions[0].words[1].text == "scrolling"


def test_shot_duration():
    assert abs(Shot(0, 1.0, 2.5).duration - 1.5) < 1e-9
