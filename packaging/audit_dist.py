"""Fail if the built wheel omits runtime data or ships private/dev trees."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def audit(wheel: Path, sdist: Path | None = None) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        expected = {p.relative_to(ROOT / "src").as_posix(): p
                    for p in (ROOT / "src/myzing/_data").rglob("*") if p.is_file()}
        # Also catch runtime assets added outside the established data directory.
        expected.update({p.relative_to(ROOT / "src").as_posix(): p
                         for p in (ROOT / "src/myzing").rglob("*")
                         if p.is_file() and p.suffix not in {".py", ".pyc"}
                         and "__pycache__" not in p.parts})
        for name, path in expected.items():
            assert name in names, f"Missing runtime file: {name}"
            assert archive.read(name) == path.read_bytes(), f"Changed runtime file: {name}"
        for name in ("LICENSE", "NOTICE.md", "docs/THIRD-PARTY-NOTICES.md"):
            matches = [n for n in names if n.endswith(".dist-info/licenses/" + name)]
            assert len(matches) == 1, f"Missing license/notice: {name}"
            assert archive.read(matches[0]) == (ROOT / name).read_bytes()
        assert all(n.startswith("myzing/") or ".dist-info/" in n for n in names)
        assert not any(part in {"tests", "handoff", "zing-workspace", "__pycache__"}
                       for name in names for part in Path(name).parts)
        for font in ("Anton", "IBMPlexSans", "ZingCaption"):
            assert f"myzing/_data/fonts/{font}-OFL.txt" in names
        assert "myzing/_data/docs/OPENCV-ZOO-LICENSES.md" in names
    if sdist:
        with tarfile.open(sdist) as archive:
            members = archive.getnames()
            assert not any(part in {"zing-workspace", "handoff", ".venv", ".git"}
                           for name in members for part in Path(name).parts)
            prefix = members[0].split("/")[0] + "/"
            for name in ("LICENSE", "NOTICE.md", "docs/THIRD-PARTY-NOTICES.md"):
                assert prefix + name in members
            for name in expected:
                assert prefix + "src/" + name in members
    return {"wheel": wheel.name, "bytes": wheel.stat().st_size,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "runtime_files": len(expected), "members": len(names), "ok": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    wheels, sdists = list(args.dist.glob("*.whl")), list(args.dist.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1, "Expected exactly one wheel and sdist"
    print(json.dumps(audit(wheels[0], sdists[0]), indent=2))
