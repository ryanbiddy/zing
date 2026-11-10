"""A blocked YuNet download leaves enough detail for a verified manual install."""
import hashlib
import io
import urllib.error

import pytest

from myzing import doctor
from myzing.factory import cut, judge, pipeline, tools
from myzing.layout import command, detector


@pytest.fixture
def model(monkeypatch, zing_workspace):
    payload = b"fixture model"
    monkeypatch.setattr(detector, "MODEL_SIZE", len(payload))
    monkeypatch.setattr(detector, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    return detector.model_path(), payload


def manual_details(text, path):
    assert detector.MODEL_NAME in text
    assert detector.MODEL_SHA256 in text
    assert str(path.parent) in text
    assert (f"https://github.com/opencv/opencv_zoo/blob/{detector.MODEL_COMMIT}"
            f"/models/face_detection_yunet/{detector.MODEL_NAME}") in text


@pytest.mark.parametrize("failure", ["transport", "hash"])
def test_fetch_failure_prints_manual_install_details(model, monkeypatch, capsys, failure):
    path, _ = model

    def download(*args, **kwargs):
        if failure == "transport":
            raise urllib.error.URLError("SSL: WRONG_VERSION_NUMBER")
        return io.BytesIO(b"bad model")

    monkeypatch.setattr(detector.urllib.request, "urlopen", download)
    assert command.run(["fetch-model"]) != 0
    text = capsys.readouterr().err
    manual_details(text, path)
    assert ("WRONG_VERSION_NUMBER" if failure == "transport" else "verification") in text
    assert not path.exists()


@pytest.mark.parametrize("valid", [True, False])
def test_manual_model_is_verified_without_network(model, monkeypatch, valid):
    path, payload = model
    path.parent.mkdir(parents=True)
    path.write_bytes(payload if valid else b"x" * len(payload))
    monkeypatch.setattr(detector.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("unexpected network"))
    monkeypatch.setattr(doctor, "_has_module", lambda _: True)

    def version(name):
        if name == "opencv-python-headless":
            return "4.13.0.92"
        raise doctor.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(doctor.metadata, "version", version)
    assert doctor.check_layout().data["model_verified"] is valid
    if valid:
        assert detector.fetch_model() == path
    else:
        with pytest.raises(detector.LayoutError) as exc:
            detector.require_model()
        manual_details(str(exc.value), path)


def test_missing_model_stops_factory_before_cutting_any_clip(model, monkeypatch, tmp_path):
    path, _ = model
    media = tmp_path / "video.mp4"
    media.write_bytes(b"fixture")
    root = tmp_path / "project"
    pipeline.init(root, media)
    moments = [{"start": 0, "end": 10, "hook": "A moment"}, {"start": 20, "end": 30, "hook": "Another"}]
    monkeypatch.setattr(pipeline, "_moments", lambda *a, **kw: moments)
    monkeypatch.setattr(cut, "run", lambda *a, **kw: pytest.fail("cut started without the face model"))
    monkeypatch.setattr(detector.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("unexpected network"))
    said = []
    with pytest.raises(tools.FactoryError) as exc:
        pipeline.run(root, judge.Judge(root), say=said.append)
    manual_details(str(exc.value), path)
    state = pipeline._read(root / "status.json")
    assert state["state"] == "failed" and detector.MODEL_NAME in state["error"]
    assert not list(root.glob("clip*"))
    assert not any("clip02" in text for text in said)

