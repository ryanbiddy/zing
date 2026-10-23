"""Opt-in, pinned OpenCV Zoo models. Inspection and inference stay offline."""

from pathlib import Path

from myzing import model_fetch
from myzing.storage import workspace_root
from .detector import LayoutError

REVISION = "f12e12798e8314f7c074a6656816c048dcc95b7a"
MODELS = {
    "person": {
        "directory": "person_detection_mediapipe",
        "filename": "person_detection_mediapipe_2023mar.onnx",
        "sha256": "47fd5599d6fa17608f03e0eb0ae230baa6e597d7e8a2c8199fe00abea55a701f",
        "bytes": 11990159,
    },
    "objects": {
        "directory": "object_detection_yolox",
        "filename": "object_detection_yolox_2022nov_int8.onnx",
        "sha256": "01a3b0f400b30bc1e45230e991b2e499ab42622485a330021947333fbaf03935",
        "bytes": 9079452,
    },
}


def model_path(name, workspace=None):
    return (Path(workspace) if workspace else workspace_root()).expanduser().resolve() / "models" / "vision" / MODELS[name]["filename"]


def inventory(workspace=None):
    rows = []
    for name, spec in MODELS.items():
        path = model_path(name, workspace)
        valid = (path.is_file() and path.stat().st_size == spec["bytes"]
                 and model_fetch.verified(path, spec["sha256"]))
        base = f"https://raw.githubusercontent.com/opencv/opencv_zoo/{REVISION}/models/{spec['directory']}"
        rows.append({"version": 1, "name": name, **spec, "path": str(path),
                     "revision": REVISION, "license": "Apache-2.0", "license_url": base + "/LICENSE",
                     "url": f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{REVISION}/models/{spec['directory']}/{spec['filename']}",
                     "verified": valid, "network_used": False})
    return rows


def fetch_models(names=("person", "objects"), workspace=None):
    """Call only for an explicit fetch command, never from an analysis path."""
    selected = [row for row in inventory(workspace) if row["name"] in names]
    downloaded = {}
    try:
        for row in selected:
            downloaded[row["name"]] = model_fetch.fetch_verified(row["url"], row["path"], row["sha256"], row["bytes"])
    except (OSError, RuntimeError, ValueError) as exc:
        raise LayoutError(f"Vision model download failed: {exc}. Retry zing layout fetch-model --vision.") from exc
    return [{**row, "downloaded": downloaded[row["name"]], "network_used": downloaded[row["name"]]}
            for row in inventory(workspace) if row["name"] in names]


def require_model(name, workspace=None):
    row = next(r for r in inventory(workspace) if r["name"] == name)
    if not row["verified"]:
        raise LayoutError(f"{name} model missing or corrupt at {row['path']}; explicitly run zing layout fetch-model --vision")
    return Path(row["path"])
