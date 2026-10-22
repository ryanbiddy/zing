"""Provisioning is offline by default; actual YuNet inference is explicit."""

import builtins
import hashlib
import io
import os
from pathlib import Path

import pytest

from myzing.layout import detector


def test_missing_model_never_uses_network(tmp_path, monkeypatch):
    monkeypatch.setattr(detector.urllib.request, "urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    with pytest.raises(detector.LayoutError, match="fetch-model"):
        detector.require_model(tmp_path)


def test_explicit_fetch_verifies_cache_and_hash_before_replacement(tmp_path, monkeypatch):
    payload = b"a stand-in model for provisioning tests"
    monkeypatch.setattr(detector, "MODEL_SIZE", len(payload))
    monkeypatch.setattr(detector, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(detector.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    path = detector.fetch_model(tmp_path)
    assert path.read_bytes() == payload
    monkeypatch.setattr(detector.urllib.request, "urlopen", lambda *a, **k: pytest.fail("cache refetched"))
    assert detector.fetch_model(tmp_path) == path
    path.write_bytes(b"bad cache")
    monkeypatch.setattr(detector.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"bad download"))
    with pytest.raises(detector.LayoutError, match="verification"):
        detector.fetch_model(tmp_path)
    assert path.read_bytes() == b"bad cache"
    assert not list(path.parent.glob("*.part"))


def test_missing_runtime_names_optional_extra(monkeypatch):
    real_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(detector.LayoutError, match=r"myzing\[layout\]"):
        detector.load_cv2()


def test_doctor_layout_is_offline_and_actionable(tmp_path, monkeypatch):
    from myzing import doctor

    monkeypatch.setenv("ZING_HOME", str(tmp_path))
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    check = doctor.check_layout()
    assert check.tier == doctor.OPTIONAL and not check.ok
    assert "myzing[layout]" in check.fix
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    def version(name):
        if name == "opencv-python-headless":
            return "4.13.0.92"
        raise doctor.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(doctor.metadata, "version", version)
    monkeypatch.setattr(detector, "load_cv2", lambda: pytest.fail("doctor imported native runtime"))
    check = doctor.check_layout()
    assert not check.ok and check.fix == "zing layout fetch-model"
    assert not check.data["network_used"]


@pytest.mark.skipif(os.environ.get("ZING_REQUIRE_YUNET") != "1", reason="set ZING_REQUIRE_YUNET=1 for cached model tests")
def test_real_yunet_detects_public_domain_face_at_two_sizes_and_blank(monkeypatch):
    # NASA Eileen Collins image; provenance/hash and explicit fetch instructions
    # in docs/FACE-LAYOUT.md. No model/image download from a test.
    import numpy as np
    from myzing.layout.debug import read_image

    image_path = Path(os.environ.get("ZING_YUNET_TEST_IMAGE", "zing-workspace/layout-fixtures/astronaut.png"))
    if not image_path.is_file():
        pytest.fail("Prepare the public-domain fixture: uv run python tools/layout_fixture.py --fetch-image")
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == "88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5"
    monkeypatch.setattr(detector.urllib.request, "urlopen", lambda *a, **k: pytest.fail("inference attempted network"))
    runtime = detector.YuNetDetector()
    source = read_image(image_path)
    for size in (320, 512):
        image = runtime.cv2.resize(source, (size, size))
        detections = runtime.detect(image)
        assert any(.35 < d.box.center[0] < .55 and .12 < d.box.center[1] < .35
                   and d.confidence > .8 for d in detections)
        for detection in detections:
            assert set(detection.to_dict()) == {"version", "box", "confidence"}
    assert runtime.detect(np.zeros((320, 320, 3), dtype=np.uint8)) == []
