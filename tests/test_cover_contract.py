"""Hand-authored covers, source checks and bad JSON without an imaging extra."""
import json
import struct
import zlib

import pytest

from myzing.cover import CoverError
from myzing.cover.contract import CAPS, SPELLED, Cover, inspect, load


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(w=160, h=90):
    rows = (b"\0" + b"\x20\x40\x60" * w) * h
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))


def spec_at(path):
    path.mkdir(exist_ok=True)
    (path / "frame.png").write_bytes(png())
    data = {"version": 1, "frame": {"src": "frame.png", "w": 160, "h": 90,
                                    "face": {"cx": .5, "cy": .4, "fh": .3}},
            "source": {"name": "The City Desk", "rights": "own", "timestamp": 2},
            "said": "It’s time. We waited four minutes.",
            "clipping": {"masthead": "City Desk", "kicker": "It’s time", "dateline": "Today",
                         "body": "We waited four minutes.", "headline": "We waited"},
            "plate": {"top": "We waited", "bottom": "four minutes"},
            "number": {"figure": "4 MIN", "label": "We waited"},
            "quote": {"text": "It's time.", "highlight": "time", "by": ["City Desk"]}}
    (path / "cover.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def test_contract_round_trip_and_warning_scale(tmp_path):
    data = spec_at(tmp_path)
    cover = Cover.from_dict(data, tmp_path)
    assert cover.to_dict() == dict(data, seed=11)
    report = load(tmp_path, styles=["quote"], sizes=["square"], scale=2)[1]
    assert report["valid"] and [w["path"] for w in report["warnings"]] == ["quote.square"]
    assert report["checks"]["quote_in_transcript"] == "passed"
    # Warnings only above 2.5x, computed for the selected export scale.
    (tmp_path / "frame.png").write_bytes(png(1280, 720))
    data["frame"].update(w=1280, h=720)
    assert not inspect(data, tmp_path, styles=["plate"], sizes=["wide"])[1]["warnings"]
    assert inspect(data, tmp_path, styles=["plate"], sizes=["wide"], scale=2)[1]["warnings"]


@pytest.mark.parametrize("path,value", [
    ("version", True), ("seed", -1), ("source.name", ""), ("source.rights", "  "),
    ("source.timestamp", -1), ("source.timestamp", float("inf")), ("frame.w", 91), ("frame.h", 91),
    ("frame.src", "absent.jpg"), ("frame.src", "https://example.invalid/f.png"),
    ("frame.face.cy", .05), ("frame.face.cx", .99), ("frame.face.fh", False), ("frame.face.fh", 0),
    ("quote.highlight", "wrong case"), ("quote.by", "one<br>two"), ("quote.by", ["", "b", "c"]),
    ("quote.html", "<b>text</b>"), ("clipping.logo", "logo.png"), ("clipping.accent", "url(x)"),
    ("clipping.masthead", "Deskette"), ("clipping.body", "We never waited"),
    ("quote.text", "It’s timing."), ("number.figure", "14 MIN"), ("number.figure", "N/A"),
])
def test_field_problems(tmp_path, path, value):
    data = spec_at(tmp_path)
    block = data
    keys = path.split(".")
    for key in keys[:-1]:
        block = block[key]
    block[keys[-1]] = value
    with pytest.raises(CoverError):
        Cover.from_dict(data, tmp_path)
    assert not inspect(data, tmp_path)[1]["valid"]


@pytest.mark.parametrize("style,key,cap", [(s, k, cap) for s in CAPS for k, cap in CAPS[s].items()])
def test_every_text_cap_names_the_field(tmp_path, style, key, cap):
    data = spec_at(tmp_path)
    value = "x" * (cap + 1)
    data[style][key] = [value] if key == "by" else value
    errors = inspect(data, tmp_path)[1]["problems"]
    assert any(p["path"].startswith(style + "." + key) and str(cap) in p["message"] for p in errors)


@pytest.mark.parametrize("n", range(21))
def test_spelled_numbers_and_numeric_boundaries(tmp_path, n):
    data = spec_at(tmp_path)
    data["number"]["figure"] = f"{n} MIN"
    for word in (SPELLED[n], str(n)):
        data["said"] = "We waited " + word + " minutes."
        assert not any(p["path"] == "number.figure" for p in inspect(data, tmp_path)[1]["problems"])
    data["said"] = f"We waited 9{n} minutes."
    assert any(p["path"] == "number.figure" for p in inspect(data, tmp_path)[1]["problems"])


def test_all_problems_and_attribution_boundaries(tmp_path):
    data = spec_at(tmp_path)
    data["source"] = {"name": "City Desks", "rights": ""}
    data["quote"]["highlight"] = "walk"
    report = inspect(data, tmp_path)[1]
    assert {p["path"] for p in report["problems"]} == {"source.rights", "clipping.masthead", "quote.highlight"}
    data["said"] = 'CITY   DESK said “IT’S TIME.”  We waited four minutes.'
    data["source"]["rights"] = "licensed: press"
    data["source"]["url"] = "https://example.test/interview"
    data["quote"].update(text='"it\'s time."', highlight="time")
    assert inspect(data, tmp_path)[1]["valid"]
    del data["said"]
    data["clipping"]["masthead"] = "Desks"
    report = inspect(data, tmp_path)[1]
    assert report["valid"] and report["checks"]["quote_in_transcript"].startswith("skipped")


def test_external_rights_need_the_source_url(tmp_path):
    data = spec_at(tmp_path)
    data["source"]["rights"] = "public-domain"
    for url in (None, "an episode", "https://["):
        if url is not None:
            data["source"]["url"] = url
        assert any(p["path"] == "source.url" for p in inspect(data, tmp_path)[1]["problems"])
    data["source"]["url"] = "https://example.test/episode"
    assert inspect(data, tmp_path)[1]["valid"]


def test_frame_cannot_escape_and_corrupt_input_is_reported(tmp_path):
    data = spec_at(tmp_path / "cover")
    (tmp_path / "outside.png").write_bytes(png())
    for path in ("../outside.png", str(tmp_path / "outside.png")):
        data["frame"]["src"] = path
        assert "inside" in inspect(data, tmp_path / "cover")[1]["problems"][0]["message"]
    (tmp_path / "cover/frame.png").write_bytes(b"not an image")
    data["frame"]["src"] = "frame.png"
    assert not inspect(data, tmp_path / "cover")[1]["valid"]


@pytest.mark.parametrize("document, message", [
    ("null", "Supply a JSON object"), ("[]", "Supply a JSON object"), ("{", "Supply a readable JSON"),
])
def test_malformed_cover_names_document(tmp_path, document, message):
    spec_at(tmp_path)
    assert load(tmp_path)[1]["valid"]
    (tmp_path / "cover.json").write_text(document)
    cover, report = load(tmp_path)
    assert cover is None
    assert any(p["path"] == "cover.json" and message in p["message"] for p in report["problems"])


def test_frame_metadata_uses_display_orientation_and_a_single_still(tmp_path):
    from myzing.cover.frame import dimensions

    # TIFF orientation 6 (rotate 90 degrees clockwise), one SHORT in IFD0.
    tiff = b"II" + struct.pack("<HIHHHIH", 42, 8, 1, 274, 3, 1, 6) + bytes(6)
    exif = b"Exif\0\0" + tiff

    def jpeg_segment(marker, data):
        return marker + struct.pack(">H", len(data) + 2) + data

    def webp_chunk(kind, data):
        return kind + struct.pack("<I", len(data)) + data + bytes(len(data) % 2)

    def webp(flags):
        header = bytes([flags, 0, 0, 0, 159, 0, 0, 89, 0, 0])
        body = b"WEBP" + webp_chunk(b"VP8X", header) + webp_chunk(b"EXIF", tiff)
        return b"RIFF" + struct.pack("<I", len(body)) + body

    image = png()
    stills = {
        "jpeg": b"\xff\xd8" + jpeg_segment(b"\xff\xe1", exif) +
                jpeg_segment(b"\xff\xc0", struct.pack(">BHH", 8, 90, 160)) + b"\xff\xd9",
        "png": image[:33] + png_chunk(b"eXIf", tiff) + image[33:],
        "webp": webp(8),
    }
    for suffix, data in stills.items():
        path = tmp_path / ("frame." + suffix)
        path.write_bytes(data)
        assert dimensions(path) == (90, 160)
    animations = {"png": image[:33] + png_chunk(b"acTL", struct.pack(">II", 2, 0)) + image[33:],
                  "webp": webp(2)}
    for suffix, data in animations.items():
        path = tmp_path / ("anim." + suffix)
        path.write_bytes(data)
        with pytest.raises(CoverError, match="still frame"):
            dimensions(path)


@pytest.mark.parametrize("field,phrase,said,valid", [
    ("number.figure", "1.1M", "We reached 1.1M views.", True),
    ("number.figure", "1.1M", "We reached 1.1 million views.", True),
    ("number.figure", "1.1M", "We reached 1.1 views.", False),
    ("number.figure", "8.5%", "Inflation was 8.5%.", True),
    ("number.figure", "8.5%", "It was eight point five percent.", True),
    ("number.figure", "8.5%", "Growth was 8.5 %.", True),
    ("number.figure", "8.5", "Growth was 8.5%.", True),
    ("number.figure", "1.1M", "1.1 billion views", False),
    ("number.figure", "4 Q9", "four", False),
    ("number.figure", "4-minute", "A 4-minute break.", True),
    ("number.figure", "4", "four hundred", False),
    ("number.figure", "4", "one hundred and four", False),
    ("number.figure", "4", "four point five", False),
    ("number.figure", "4", "8.5", False),
    ("number.figure", "5%", "8.5%", False),
    ("number.figure", "5%", "eight point five percent", False),
    ("number.figure", "4", "-4 degrees", False),
    ("number.figure", "-4", "4 degrees", False),
    ("number.figure", "-4", "−4 degrees", True),
    ("number.figure", "1,000", "1000 users", True),
    ("number.figure", "1000", "1,000 users", True),
    ("number.figure", "24", "twenty-four", True),
    ("number.figure", "24", "twenty‑four", True),
    ("number.figure", "4", "twenty–four", False),
    ("number.figure", "15K", "15,000 subscribers", True),
    ("number.figure", "15,000", "fifteen thousand subscribers", True),
    ("number.figure", "1.1M", "1,100,000 views", True),
    ("number.figure", "400", "four hundred people", True),
    ("number.figure", "104", "one hundred and four", True),
    ("number.figure", "104", "one hundred four", True),
    ("number.figure", "100", "one hundred and four", False),
    ("number.figure", "15K", "15 subscribers", False),
    ("number.figure", "15", "15,000 subscribers", False),
    ("number.figure", "15K", "15 million subscribers", False),
    ("number.figure", "405", "four hundred, 5 of them", False),
    ("number.figure", "104", "one hundred and four thousand", False),
    ("number.figure", "100", "one hundred and four thousand dollars", False),
    ("number.figure", "104K", "one hundred and four thousand dollars", True),
    ("number.figure", "100K", "one hundred thousand dollars", True),
    ("number.figure", "100", "a hundred people", True),
    ("number.figure", "1,500", "fifteen hundred and four", False),
    ("number.figure", "1,504", "fifteen hundred and four", True),
    ("number.figure", "100", "one hundred and four point five", False),
    ("number.figure", "104.5", "one hundred and four point five", True),
    ("number.figure", "1.504", "1.5 hundred and 4", False),
    ("number.figure", "2K", "in two thousand and four", False),
    ("number.figure", "2004", "in two thousand and four", True),
    ("number.figure", "2,500", "two thousand five hundred", True),
    ("number.figure", "2.5K", "two thousand five hundred", True),
    ("number.figure", "2,000", "two thousand five hundred", False),
    ("number.figure", "200", "between one hundred and two hundred", True),
    ("number.figure", "100", "between one hundred and two hundred", True),
    ("number.figure", "102", "between one hundred and two hundred", False),
    ("number.figure", "2.5M", "two million five hundred thousand", True),
    ("number.figure", "2026", "in twenty twenty-six", False),
    ("number.figure", "46", "in twenty twenty-six", False),
    ("number.figure", "15 M", "There were 15.", False),
    ("number.figure", "15 M", "There were 15 million.", True),
    ("number.figure", "15", "It was 15 m long.", True),
    ("number.figure", "10-20", "It fell from 10 to minus 20.", False),
    ("number.figure", "10-20", "ten to twenty", True),
    ("number.figure", "10–20", "10–20 people", True),
    ("number.figure", "3", "three point fourteen", False),
    ("number.figure", "3.14", "three point one four", True),
    ("number.figure", "5%", "up point five percent", False),
    ("number.figure", "0.5%", "up point five percent", True),
    ("number.figure", "1", "one-third of respondents", False),
    ("number.figure", "20", "in the twenty-first century", False),
    ("number.figure", "4", "a four-minute break", True),
    ("number.figure", "100%", "I am one hundred percent sure.", True),
    ("number.figure", "15K", "negative $15,000", False),
    ("number.figure", "-$15K", "$15,000", False),
    ("number.figure", "-$15K", "minus $15,000", True),
    ("number.figure", "$15K", "$15,000", True),
    ("number.figure", "5", "a five-billion-dollar deal", False),
    ("number.figure", "5B", "a five-billion-dollar deal", True),
    ("number.figure", "50%", "a 50-percent cut", True),
    ("number.figure", "1M", "We have half a million users", False),
    ("number.figure", "501K", "between five hundred and a thousand", False),
    ("number.figure", "2", "Two thirds of voters agreed", False),
    ("number.figure", "3", "three quarters of them", False),
    ("number.figure", "2", "two seconds late", True),
    ("number.figure", "-10%", "inflation of 5%–10%", False),
    ("number.figure", "10%", "inflation of 5%–10%", True),
    ("number.figure", "10%", "inflation of 5%-10%", True),
    ("number.figure", "-50", "Wait--50 people", False),
    ("number.figure", "50", "Wait--50 people", True),
    ("number.figure", "5 – 10", "from 5 to 10", True),
    ("number.figure", "2B", "between 1.5 billion and 500 million", False),
    ("number.figure", "1.5B", "between 1.5 billion and 500 million", True),
    ("number.figure", "500M", "between 1.5 billion and 500 million", True),
    ("number.figure", "2.5B", "between 2 billion and 500 million", False),
    ("number.figure", ".5%", "It grew 5 percent", False),
    ("number.figure", ".5%", "It grew 0.5 percent", True),
    ("number.figure", "5", "At this point five people left", True),
    ("number.figure", "0.5", "At this point five people left", False),
    ("quote.text", "$5 million", "They made -$5 million", False),
    ("quote.text", "5 degrees", "It was –5 degrees", False),
    ("quote.text", "He ran 3.", "He ran 3:30 in the marathon", False),
    ("number.figure", "5M", "We raised 5 million and 20 percent went to fees", True),
    ("number.figure", "20%", "We raised 5 million and 20 percent went to fees", True),
    ("number.figure", "5,000,020", "We raised 5 million and 20 percent went to fees", False),
    ("number.figure", "5M", "We hit five million two years ago", True),
    ("number.figure", "5,000,002", "We hit five million two years ago", False),
    ("number.figure", "100,018", "There are 100 thousand 18-year-olds", False),
    ("number.figure", "2024", "in two thousand twenty-four", True),
    ("number.figure", "2", "We raised two and a half million", False),
    ("number.figure", "3", "Rates rose 3 and a half percent", False),
    ("number.figure", "19", "During COVID-19, travel stopped", False),
    ("number.figure", "1", "No-one was there", False),
    ("number.figure", "20", "10-20 people", True),
    ("number.figure", "200", "A two-hundred-thousand-dollar house", False),
    ("number.figure", "200K", "A two-hundred-thousand-dollar house", True),
    ("quote.text", "5% growth.", "We saw -5% growth.", False),
    ("quote.text", "profit organization.", "This is a non-profit organization.", False),
    ("quote.text", "This is risk.", "This is risk-free.", False),
    ("quote.text", "We shipped it.", "We shipped it—finally.", True),
    ("quote.text", "non-profit organization.", "This is a non-profit organization.", True),
    *(("number.figure", n, n, True) for n in ("100K", "10x", "4K", "1st", "4min", "500GB")),
    ("quote.text", "It's time.", "It’s time, we can go.", True),
    ("quote.text", '"On time"', "She said “On time” yesterday.", True),
    ("quote.text", "A 4-minute break.", "A 4‑minute break.", True),
    ("quote.text", "Yes—today", "Yes–today", True),
    ("quote.text", "5%", "Inflation was 8.5%.", False),
    ("quote.text", '"', "She said “yes.”", False),
    ("quote.text", "...", None, False),
    ("clipping.masthead", "s", "It's time", False),
    ("clipping.masthead", '"', "She said “yes.”", False),
    ("clipping.masthead", "   ", None, False),
    ("clipping.masthead", "", None, False),
])
def test_honesty(tmp_path, field, phrase, said, valid):
    data = spec_at(tmp_path)
    style, key = field.split(".")
    for other in {"number", "quote", "clipping", "plate"} - {style}:
        del data[other]
    if said is None:
        del data["said"]
    else:
        data["said"] = said
    data[style][key] = phrase
    if style == "quote":
        data["quote"]["highlight"] = phrase
    if style == "clipping":
        data["clipping"]["body"] = said or "Body"
    report = inspect(data, tmp_path)[1]
    assert report["valid"] == valid, report
    if not valid:
        assert field in {p["path"] for p in report["problems"]}
        if style == "clipping":
            assert report["checks"]["masthead_attribution"] == "failed"


def test_crop_coordinates_must_fit_even_with_finite_zoom(tmp_path):
    data = spec_at(tmp_path)
    data["frame"]["face"]["fh"] = 1e-307
    cover, report = inspect(data, tmp_path, styles=["clipping"], sizes=["wide"])
    assert cover is None and "frame.face" in {p["path"] for p in report["problems"]}
