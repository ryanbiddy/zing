"""Rebuild preset faces: uv run --no-project --with fonttools==4.62.1 python tools/eval/caption2_fonts.py.

Build-time only. First explicitly fetch the pinned Inter source with zing fonts
fetch inter. Runtime uses SFNT metrics and libass, with no fontTools dependency.
"""

from hashlib import sha256
from pathlib import Path
import json

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "zing-workspace" / "home" / "fonts" / "inter"
    target = root / "src/myzing/_data/fonts"
    data = (source / "Inter[opsz,wght].ttf").read_bytes()
    assert sha256(data).hexdigest() == "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031"
    license_data = (source / "inter-OFL.txt").read_bytes()
    assert sha256(license_data).hexdigest() == "5b9321a4298cfeb6b34354164a1c3afc3db114569984c502b9b35d988fd58c57"
    manifest = {"version":1,"source_sha256":sha256(data).hexdigest(),
                "source_url":"https://raw.githubusercontent.com/google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
                "license_sha256":sha256(license_data).hexdigest(),"faces":{}}
    for weight in (700,800):
        font = TTFont(source / "Inter[opsz,wght].ttf", recalcTimestamp=False)
        instantiateVariableFont(font,{"wght":weight,"opsz":32},inplace=True)
        # Word slots use font advances. Optional Latin ligatures and kerning
        # are disabled in this derivative, while required shaping is retained.
        for table in ("GSUB","GPOS"):
            if table in font:
                for feature in font[table].table.FeatureList.FeatureRecord:
                    if feature.FeatureTag in {"liga","clig","dlig","kern"}:
                        feature.Feature.LookupListIndex = []
                        feature.Feature.LookupCount = 0
        for record in font["name"].names:
            if record.nameID in {1,2,3,4,6,16,17}:
                value = ("Bold" if weight == 700 else "ExtraBold") if record.nameID in {2,17} else f"ZingCaption{weight}"
                record.string = value.encode(record.getEncoding())
        path = target / f"ZingCaption-{weight}.ttf"
        font.save(path)
        manifest["faces"][str(weight)] = {"file":path.name,"sha256":sha256(path.read_bytes()).hexdigest(),"weight":weight}
    (target / "ZingCaption-OFL.txt").write_bytes(license_data)
    (target / "caption-presets.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
