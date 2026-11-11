from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from myzing.factory import cut
from myzing.layout import detector
from myzing.study import caption_models


HAND = [918.202759, 327.123840, 250.350800, 369.976959,
        1015.092224, 461.676971, 1080.191528, 461.517487, 1048.916016, 514.528687,
        1022.485046, 588.228516, 1083.046631, 586.007202, .689781]
FACE = [428.107483, 105.487038, 131.694672, 195.339584,
        473.459229, 182.738907, 534.888733, 187.456177, 506.745148, 224.576035,
        472.878235, 248.381256, 526.424500, 251.959869, .932162]
FACES = [
    FACE,
    [406.225220, 312.824188, 255.079727, 318.982727,
     542.431763, 462.621582, 609.818298, 444.321350, 621.213074, 512.367310,
     564.044373, 556.065552, 625.344116, 542.084961, .888066],
    [1629.175537, 144.726654, 109.797272, 165.673294,
     1643.241455, 203.849640, 1673.649170, 204.945068, 1636.306030, 236.101105,
     1649.449585, 265.794312, 1676.336426, 266.051422, .927961],
    [1030.013672, 101.907379, 60.838509, 98.555916,
     1038.427856, 138.134552, 1048.690186, 139.875656, 1030.658691, 154.677094,
     1040.377563, 172.204010, 1046.893799, 173.756088, .902167],
    [217.733093, 124.065590, 52.349411, 93.361404,
     251.903229, 154.650909, 262.670380, 153.725021, 267.778229, 169.246658,
     252.967514, 191.471634, 261.221069, 189.320587, .888869],
    [449.219421, 413.814514, 251.549164, 256.297729,
     509.832550, 541.770264, 622.400757, 548.378845, 559.256226, 605.880615,
     511.755646, 625.635620, 602.619141, 630.359558, .903135],
]


@pytest.mark.parametrize("row", [
    HAND,
    [984.500854, 354.554047, 183.993927, 292.648071,
     1096.795044, 466.343933, 1126.109497, 465.471069, 1139.884888, 508.546753,
     1102.075195, 571.330566, 1118.982178, 569.694641, .779174],
    [817.206482, 264.291626, 144.039215, 214.997375,
     931.384338, 333.991547, 926.672119, 333.284912, 957.251282, 355.763733,
     926.606445, 407.678741, 919.517761, 405.328857, .625712],
], ids=["hand_61s", "hand_60_833s", "chair"])
def test_real_nonfaces_are_rejected(row):
    assert not detector.face_landmarks(row)


@pytest.mark.parametrize("row", FACES,
                         ids=["frontal", "three_quarter_right", "three_quarter_left",
                              "small_profile_left", "small_profile_right", "looking_down"])
@pytest.mark.parametrize("scale", [.25, 1, 4])
def test_real_faces_survive_at_each_scale(row, scale):
    assert detector.face_landmarks([v * scale for v in row[:14]] + row[14:])


@pytest.mark.parametrize("kind", ["rotated", "upside_down", "mirrored", "low_eyes", "nose_above_eyes",
                                  "mouth_above_nose", "outside_box", "collapsed_eyes"])
def test_bad_landmark_geometry_is_rejected(kind):
    row = FACE.copy()
    x, y, w, h = row[:4]
    if kind == "rotated":
        for i in range(4, 14, 2):
            row[i], row[i + 1] = x + w / 2 - (row[i + 1] - y - h / 2), y + h / 2 + (row[i] - x - w / 2)
    elif kind == "upside_down":
        for i in range(4, 14, 2):
            row[i], row[i + 1] = 2 * x + w - row[i], 2 * y + h - row[i + 1]
    elif kind == "mirrored":
        row[4:14:2] = [2 * x + w - v for v in row[4:14:2]]
    elif kind == "low_eyes":
        row[5] = row[7] = y + .8 * h
    elif kind == "nose_above_eyes":
        row[9] = min(row[5], row[7]) - 1
    elif kind == "mouth_above_nose":
        row[11] = row[9] - 1
    elif kind == "outside_box":
        row[4:14:2] = [v + w for v in row[4:14:2]]
    else:
        row[6] = row[4]
    assert not detector.face_landmarks(row)


@pytest.mark.parametrize("index,value", [(2, 0), (3, -1), (4, float("nan")), (9, float("inf"))])
def test_invalid_rows_are_rejected(index, value):
    row = FACE.copy()
    row[index] = value
    assert not detector.face_landmarks(row)


def test_mirrored_face_with_correct_landmark_order_survives():
    row = FACE.copy()
    row[4:14:2] = [2 * row[0] + row[2] - v for v in row[4:14:2]]
    row[4:8] = row[6:8] + row[4:6]
    row[10:14] = row[12:14] + row[10:12]
    assert detector.face_landmarks(row)


class Frame:
    shape, size = (720, 1280, 3), 0

    def __getitem__(self, key):
        return self


@pytest.fixture
def clip(tmp_path, monkeypatch, zing_workspace):
    state = SimpleNamespace(path=tmp_path, rows=[FACE, HAND], sizes=[])
    cv2 = SimpleNamespace(error=RuntimeError, imread=lambda path: Frame(),
                          dnn=SimpleNamespace(DNN_BACKEND_OPENCV=0, DNN_TARGET_CPU=0),
                          FaceDetectorYN=SimpleNamespace(create=lambda *a: SimpleNamespace(
                              setInputSize=state.sizes.append, detect=lambda img: (None, state.rows))))
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setattr(detector, "load_cv2", lambda: cv2)
    monkeypatch.setattr(detector, "require_model", lambda *a, **kw: tmp_path / "model")
    monkeypatch.setattr(cut, "_camera_cuts", lambda *a: [])
    monkeypatch.setattr(cut, "burned_caption_top", lambda d: None)
    monkeypatch.setattr(caption_models, "engine", lambda: (None, "fake"))
    (tmp_path / "frames").mkdir()
    for n in range(1, 61):
        (tmp_path / "frames" / f"{n:05d}.jpg").touch()
    return state


def test_factory_crop_follows_the_face_instead_of_the_larger_hand(clip):
    x, y, w, h = (int(v) for v in FACE[:4])
    assert cut.cams(clip.path)["cams"] == [
        {"from": 0, "to": 2, "mode": "face", "cx": (x + w / 2) / 1280,
         "cy": (y + h / 2) / 720, "fh": h / 720}]
    assert clip.sizes and set(clip.sizes) == {(1280, 720)}


def test_layout_discards_the_hand_before_building_boxes(clip):
    faces = detector.YuNetDetector().detect(Frame())
    assert len(faces) == 1
    assert faces[0].box.x == pytest.approx(FACE[0] / 1280)
    assert faces[0].confidence == FACE[-1]


def test_hand_alone_leaves_the_factory_shot_wide(clip):
    clip.rows = [HAND]
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 2, "mode": "wide", "faces": 0}]


@pytest.mark.parametrize("rows", [None, []])
def test_empty_detections_stay_empty(clip, rows):
    clip.rows = rows
    assert detector.YuNetDetector().detect(Frame()) == []
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 2, "mode": "wide", "faces": 0}]
