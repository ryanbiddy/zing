"""Explicitly provision a public-domain YuNet fixture; never imported by tests.

NASA Eileen Collins portrait, public domain per scikit-image's data docs.
The hash comes from that repository's data registry at the pinned commit.
"""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

URL = ("https://raw.githubusercontent.com/scikit-image/scikit-image/"
       "c1af2bf80d2c8845bbbf06222f87e8b58a8e5c1e/skimage/data/astronaut.png")
SHA256 = "88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5"
LICENSE_URL = "https://scikit-image.org/docs/0.25.x/api/skimage.data.html#skimage.data.astronaut"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-image", action="store_true", required=True,
                        help="explicitly download the pinned public-domain NASA portrait")
    parser.add_argument("--out", type=Path, default=Path("zing-workspace/layout-fixtures/astronaut.png"))
    args = parser.parse_args()
    with urllib.request.urlopen(URL, timeout=30) as response:
        payload = response.read(2 * 1024 * 1024)
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise SystemExit("Fixture SHA-256 mismatch; nothing written")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    metadata = {"source": URL, "sha256": SHA256, "license": "public domain (NASA)",
                "license_evidence": LICENSE_URL, "attribution": "NASA: Eileen Collins portrait"}
    args.out.with_suffix(".license.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(args.out.resolve())


if __name__ == "__main__":
    main()
