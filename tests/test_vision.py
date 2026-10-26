"""VIS1: model-free CI seams, coordinate decoding, offline provisioning and evidence."""

import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import model_fetch
from myzing.layout import vision, vision_models
from myzing.layout.detector import LayoutError
from myzing.layout.types import Box, Detection, FaceTrack, FrameDetections
from myzing.layout.tracking import build_tracks


def test_missing_models_are_offline_and_actionable(tmp_path):
    rows = vision_models.inventory(tmp_path)
    assert len(rows) == 2 and not any(r["verified"] for r in rows)
    assert all(r["license"] == "Apache-2.0" and vision_models.REVISION in r["url"] for r in rows)
    with pytest.raises(LayoutError, match="fetch-model --vision"):
        vision_models.require_model("person", tmp_path)


@pytest.mark.parametrize("name", ["person", "objects"])
def test_explicit_fetch_is_bounded_verified_atomic_and_cached(tmp_path, monkeypatch, name):
    data = b"a small mocked model"
    spec = {**vision_models.MODELS[name], "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    monkeypatch.setitem(vision_models.MODELS, name, spec)
    monkeypatch.setattr(model_fetch, "open_url", lambda url: io.BytesIO(data))
    rows = vision_models.fetch_models([name], tmp_path)
    assert rows[0]["verified"] and rows[0]["network_used"] and rows[0]["downloaded"]
    path = vision_models.model_path(name, tmp_path)
    monkeypatch.setattr(model_fetch, "open_url", lambda url: pytest.fail("cached model downloaded again"))
    cached = vision_models.fetch_models([name], tmp_path)[0]
    assert cached["verified"] and not cached["network_used"] and not cached["downloaded"]
    path.write_bytes(b"broken")
    for bad, message in ((b"x" * (len(data) + 1), "pinned size"), (b"bad", "SHA-256")):
        monkeypatch.setattr(model_fetch, "open_url", lambda url: io.BytesIO(bad))
        with pytest.raises(LayoutError, match=message):
            vision_models.fetch_models([name], tmp_path)
        assert path.read_bytes() == b"broken"
        assert not list(path.parent.glob("*.part"))


def test_cli_explicit_vision_selection(tmp_path, monkeypatch, capsys):
    from myzing.layout import command
    calls = []
    monkeypatch.setattr(command, "fetch_model", lambda *a: pytest.fail("vision-only fetch downloaded YuNet"))
    monkeypatch.setattr(vision_models, "fetch_models", lambda **kw: calls.append(kw) or [{"verified": True}])
    assert command.run(["fetch-model", "--vision", "--workspace", str(tmp_path)]) == 0
    assert calls == [{"workspace": tmp_path}]
    assert json.loads(capsys.readouterr().out)["vision_models"][0]["verified"]


def test_missing_runtime_falls_back_without_numpy_or_network(monkeypatch):
    monkeypatch.setattr(vision, "load_cv2", lambda: (_ for _ in ()).throw(LayoutError("Install myzing[layout]")))
    detections, notes = vision.photo_detections(object())
    assert detections == [] and any("model-free saliency" in n for n in notes)


def test_raw_class_and_confidence_survive_tracks_and_roundtrip():
    frames = [FrameDetections(t, [Detection(Box(.2 + .01*t, .3, .2, .3), score,
                                          class_name="dog", detector="yolox-s-int8")])
              for t, score in ((0, .81), (1, .94))]
    tracks = build_tracks(frames, duration=2)
    copy = FaceTrack.from_dict(tracks[0].to_dict())
    assert [(o.time, o.class_name, o.confidence, o.detector) for o in copy.observations] == [
        (0, "dog", .81, "yolox-s-int8"), (1, "dog", .94, "yolox-s-int8")]


def test_yolox_decoding_undoes_letterbox_and_uses_xywh_for_classwise_nms():
    np = pytest.importorskip("numpy")
    detector = object.__new__(vision.ObjectDetector)
    seen = {}
    def nms(boxes, scores, labels, *args):
        seen.update(boxes=boxes, scores=scores, labels=labels)
        return [0, 1]
    detector.cv2 = SimpleNamespace(dnn=SimpleNamespace(NMSBoxesBatched=nms))
    raw = np.zeros((1, 8400, 85), np.float32)
    # Center (320,160), width 160, height 80 in 640 canvas => source (800,400).
    raw[0, :2, :4] = [40, 20, np.log(20), np.log(10)]
    raw[0, 1, 0] -= 1  # second anchor is x=1
    raw[0, :2, 4] = .9
    raw[0, 0, 5 + 16] = .9
    raw[0, 1, 5 + 15] = .8
    items = detector.decode([raw], 800, 400, .8)
    assert [d.class_name for d in items] == ["dog", "cat"]
    assert items[0].confidence == pytest.approx(.81)
    assert items[0].box.x == pytest.approx(.375)
    assert items[0].box.height == pytest.approx(.25)
    assert seen["boxes"][0] == pytest.approx([240, 120, 160, 80])
    assert seen["labels"] == [16, 15]


def test_person_decoding_sigmoid_center_padding_and_multiple_people():
    np = pytest.importorskip("numpy")
    detector = object.__new__(vision.PersonDetector)
    seen = []
    def nms(boxes, scores, *args):
        seen.extend(boxes)
        return [0, 1]
    detector.cv2 = SimpleNamespace(dnn=SimpleNamespace(NMSBoxes=nms))
    raw = np.zeros((1, 2254, 12), np.float32)
    logits = np.full((1, 2254, 1), -100., np.float32)
    logits[0, :2, 0] = [2, 3]
    raw[0, :2, :4] = [108, 108, 56, 56]  # first anchor is at pixel (4,4)
    items = detector.decode([raw, logits], 448, 224, (.5, 0, 56))
    assert len(items) == 2  # upstream topK=1 would lose the second person
    assert items[0].box.x == pytest.approx(.375)
    assert items[0].box.y == pytest.approx(.25)
    assert items[0].box.height == pytest.approx(.5)
    assert items[0].confidence == pytest.approx(1 / (1 + np.exp(-2)))
    assert seen[0] == pytest.approx([84, 84, 56, 56])


def test_person_last_anchor_uses_the_seven_by_seven_grid():
    np = pytest.importorskip("numpy")
    detector = object.__new__(vision.PersonDetector)
    detector.cv2 = SimpleNamespace(dnn=SimpleNamespace(NMSBoxes=lambda *args: [0]))
    raw = np.zeros((1, 2254, 12), np.float32)
    logits = np.full((1, 2254, 1), -100., np.float32)
    logits[0, 2253, 0] = 3
    raw[0, 2253, 2:4] = [16, 16]
    item, = detector.decode([raw, logits], 224, 224, (1, 0, 0))
    assert item.box.center == pytest.approx((208/224, 208/224))


@pytest.mark.parametrize("label", ["cat", "dog", "bird", "horse", "person", "chair"])
def test_semantic_regions_protect_alongside_faces_and_suppress_saliency(label):
    from myzing.memes.subject import protected_regions
    d = Detection(Box(.2, .1, .5, .7), .83, class_name=label, detector="yolox-s-int8").to_dict()
    regions = protected_regions([[.8, .1, .1, .2]], "yunet",
                                {"box": [.1, .1, .2, .2], "confidence": .9}, detections=[d])
    assert [r["kind"] for r in regions] == ["face", "detected_subject"]
    assert regions[1]["class_name"] == label and regions[1]["confidence"] == .83
    assert regions[1]["box"][0] < .2


def test_mocked_pet_meme_avoids_actual_text_ink(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    from myzing.memes import render
    source = tmp_path / "shape.png"
    Image.new("RGB", (600, 600), "#aaaabb").save(source)
    d = Detection(Box(.05, .02, .9, .85), .88, class_name="dog", detector="mock").to_dict()
    monkeypatch.setattr(render, "photo_faces", lambda image: ([], "yunet"))
    monkeypatch.setattr(render, "photo_detections", lambda image: ([d], []))
    result = render.render_meme(["The meeting ran long", "Still waiting for the walk"], image=str(source),
                                out=str(tmp_path / "render.png"))
    assert result["layout"] == "caption" and result["protection"]["text_clear"]
    assert result["protection"]["detections"] == [d]
    assert any("detected dog" in note for note in result["warnings"])


def test_mocked_pet_still_inventory_and_protection(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    from myzing.still import inventory, placement
    from myzing.still.models import Photo
    source = tmp_path / "shape.png"
    Image.new("RGB", (600, 600), "#aaaabb").save(source)
    d = Detection(Box(.1, .1, .8, .8), .92, class_name="cat", detector="mock").to_dict()
    monkeypatch.setattr(inventory, "photo_detections", lambda image: ([d], []))
    monkeypatch.setattr(inventory, "read_text", lambda image: None)
    photo = Photo.from_dict(inventory.describe_photo(source).to_dict())
    assert photo.detections == [d] and "cat (0.92" in photo.description
    assert any(b.x < .1 and b.right > .9 for b in placement.protected_boxes(photo))


def test_framing_models_sample_cuts_record_all_classes_and_keep_faces(tmp_path, monkeypatch):
    from myzing.layout import framing, debug
    frames = [(t, tmp_path / f"{t}.png") for t in (0., .5, 1., 1.5, 2.)]
    monkeypatch.setattr(framing, "_sample_window", lambda *a: frames)
    monkeypatch.setattr(debug, "read_image", lambda path: object())
    monkeypatch.setattr(framing, "load_cv2", lambda: object())
    monkeypatch.setattr(framing, "appearance", lambda *a: [])
    monkeypatch.setattr(framing, "YuNetDetector", lambda **kw: SimpleNamespace(
        detect=lambda im: [Detection(Box(.1, .1, .1, .2), .91)]))
    calls = {"person": 0, "objects": 0}
    def detect(name):
        calls[name] += 1
        return [Detection(Box(.65, .1, .2, .6), .82, class_name="person" if name == "person" else "dog", detector=name)]
    monkeypatch.setattr(framing, "optional_detectors", lambda: (
        {n: SimpleNamespace(detect=lambda im, n=n: detect(n)) for n in calls}, []))
    tracks, notes = framing.analyze_subjects(tmp_path / "video.mp4", 2.5, tmp_path, cut_times=[1.5])
    assert calls == {"person": 5, "objects": 3}  # 0,1,1.5; .5 and 2 skipped
    raw = [o for t in tracks for o in t.observations]
    assert len(raw) == 13
    assert {o.class_name for o in raw} == {"person", "dog", "face"}
    assert all(o.confidence is not None for o in raw)
    assert all(not (t.keyframes[0].time < 1.5 <= t.keyframes[-1].time) for t in tracks)


def test_full_person_body_does_not_push_captions_out_of_sharp_picture():
    from myzing.composition import Composition, AssetRef, CompositionClip, CompositionCaption, CaptionStyle
    from myzing.layout.framing import place_captions, centered_framing, visible_content
    plan = Composition(assets=[AssetRef("s", "source.mp4", None)],
                       clips=[CompositionClip("source.mp4", 0, 2, 0, id="c", asset_id="s")],
                       captions=[CompositionCaption(id="cap", text="We already", start=.2, end=1,
                                                     word_timed=False, style=CaptionStyle(50))],
                       width=1920, height=1080)
    tracks = build_tracks([FrameDetections(0, [Detection(Box(0, 0, 1, 1), .9, class_name="person", detector="yolox-s-int8")])],
                          duration=2, max_gap=2)
    place_captions(plan, {"s": tracks}, {"s": (862, 360)})
    layout = plan.captions[0].layout
    assert layout.overlap.safe and "sharp picture" in layout.overlap.scope
    assert not layout.overlap.face_ids and not plan.accepted_unsafe_layouts
    content = visible_content(centered_framing("fit", 862, 360, 1920, 1080), 1920, 1080)
    assert content.y <= layout.box.y < layout.box.bottom <= content.bottom


@pytest.mark.skipif(os.environ.get("ZING_REQUIRE_VISION") != "1", reason="set ZING_REQUIRE_VISION=1 with cached models and licensed fixtures; shapes cannot test recognition")
@pytest.mark.real_model(env="ZING_REQUIRE_VISION")
def test_real_models_on_licensed_images_and_blank():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    root = Path(os.environ.get("ZING_VISION_FIXTURES", str(Path(__file__).parent / "fixtures/vision")))
    assert (root / "manifest.json").is_file(), "Prepare licensed VIS1 fixture manifest; tests never download"
    models = {"person": vision.PersonDetector(), "objects": vision.ObjectDetector()}
    for row in json.loads((root / "manifest.json").read_text()):
        path = root / row["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        assert image is not None
        for model, label in row["expect"].items():
            assert any(d.class_name == label for d in models[model].detect(image)), row["file"]
    for detector in models.values():
        assert detector.detect(np.zeros((360, 640, 3), np.uint8)) == []


def test_person_head_region_blocks_captions_but_body_does_not():
    # Grok R2: mediapipe-person-head tracks carry person ids/class names but are heads.
    from myzing.composition import Composition, AssetRef, CompositionClip, CompositionCaption, CaptionStyle
    from myzing.layout.caption_safety import is_face
    from myzing.layout.framing import place_captions
    head = build_tracks([FrameDetections(0, [Detection(Box(0, 0, 1, 1), .9, class_name="person", detector="mediapipe-person-head")])],
                        duration=2, max_gap=2)
    body = build_tracks([FrameDetections(0, [Detection(Box(0, 0, 1, 1), .9, class_name="person", detector="yolox-s-int8")])],
                        duration=2, max_gap=2)
    assert all(is_face(t) for t in head) and not any(is_face(t) for t in body)
    plan = Composition(assets=[AssetRef("s", "source.mp4", None)],
                       clips=[CompositionClip("source.mp4", 0, 2, 0, id="c", asset_id="s")],
                       captions=[CompositionCaption(id="cap", text="We already", start=.2, end=1,
                                                     word_timed=False, style=CaptionStyle(50))],
                       width=1920, height=1080)
    try:
        place_captions(plan, {"s": head}, {"s": (1920, 1080)})
    except Exception as exc:  # A refusal must name the head track.
        assert head[0].id in str(exc)
        return
    layout = plan.captions[0].layout
    assert not layout.overlap.safe and any(f.endswith(head[0].id) for f in layout.overlap.face_ids)
    assert any("overlaps face tracks" in w and "measured" in w for w in layout.warnings)
