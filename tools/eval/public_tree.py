"""Check tracked public content without printing possible credential values.

Run with ``python -m tools.eval.public_tree`` from a source checkout.
This is a regression guard, not a complete secret or copyright detector.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
MEDIA = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".wav", ".mp3",
         ".mp4", ".webm", ".mov", ".mkv", ".ttf", ".woff", ".woff2", ".onnx"}
SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|pypi-[A-Za-z0-9_-]{30,})"
)
HOME = re.compile(r"(?:[A-Za-z]:[\\/]+Users[\\/]+|/(?:Users|home)/)([\w.-]+)[\\/]", re.I)
EXAMPLE_USERS = {"x", "example", "exampleuser", "user", "test"}


def text_issues(text: str) -> list[tuple[int, str]]:
    issues = []
    for number, line in enumerate(text.splitlines(), 1):
        if SECRET.search(line):
            issues.append((number, "credential-shaped value"))
        if any(m.group(1).lower() not in EXAMPLE_USERS for m in HOME.finditer(line)):
            issues.append((number, "personal home path"))
    return issues


def allowed_assets(root: Path) -> set[str]:
    allowed = set()
    for slug in ("landscape-big-buck-bunny", "short-daily-dweebs",
                 "raw-talking-head-korky-paul", "x-nasa-artemis-backseat-drivers"):
        folder = root / "tools/eval/real_videos" / slug
        provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
        rights = provenance["rights"]
        if not all(rights.get(k) for k in ("label", "attribution", "evidence_url")):
            raise ValueError(f"{slug}: missing rights record")
        allowed.update((folder / p).relative_to(root).as_posix()
                       for p in provenance["artifacts"])
    allowed.update({
        "tools/eval/fixtures/speech/ripe-figs-spoken.wav",
        "tools/eval/fixtures/speech/ripe-figs-like.wav",
        "src/myzing/_data/fonts/Anton-Regular.ttf",
        "src/myzing/_data/fonts/IBMPlexSans.ttf",
        # CC0, with original/derived hashes and attribution in the manifest.
        "tests/fixtures/vision/Cat-on-couch.jpg",
        "tests/fixtures/vision/Dog_IMG_1057.jpg",
        "tests/fixtures/vision/korky-1s.jpg",
    })
    return allowed


def scan(root: Path = ROOT) -> dict:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode("utf-8").split("\0")
    allowed = allowed_assets(root)
    issues = []
    scanned = 0
    for name in sorted(set(paths) - {""}):
        if name.startswith("handoff/"):
            issues.append({"path": name, "reason": "internal coordination must not be tracked"})
        path = root / name
        if not path.is_file():  # an intentional current-tree deletion
            continue
        scanned += 1
        if path.suffix.lower() in MEDIA and name not in allowed:
            issues.append({"path": name, "reason": "unreviewed media/model/font"})
        if ((path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example")
                or path.name in {".pypirc", ".netrc"}
                or path.suffix in {".token", ".pem", ".key"}):
            issues.append({"path": name, "reason": "credential file"})
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        issues.extend({"path": name, "line": line, "reason": reason}
                      for line, reason in text_issues(text))
    return {"scanned_files": scanned, "issues": issues}


if __name__ == "__main__":
    report = scan()
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["issues"]))
