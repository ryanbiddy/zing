"""POLISH1 item 3: non-face subjects and explicit protect boxes stay clear of text."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from myzing import cli, mcp_server  # noqa: E402
from myzing.memes import MemeError  # noqa: E402
from myzing.memes.render import Rect, fit_rect, render_meme  # noqa: E402
from myzing.memes.subject import MIN_CONFIDENCE, estimate_subject, user_boxes  # noqa: E402
from myzing.still.api import create_stills, pick_still  # noqa: E402

BLOB = (30, 25, 20)
GROUND = (205, 205, 200)


def blob_photo(path, box, size=(1200, 1200)):
    """A dark, compact, two-lobed blob (pet-like silhouette) on a flat background."""
    image = Image.new("RGB", size, GROUND)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = (round(v * s) for v, s in zip(box, size * 2))
    draw.ellipse((x0, y0, x1, y0 + round((y1 - y0) * .7)), fill=BLOB)
    draw.ellipse((x0 + (x1 - x0) // 6, y0 + (y1 - y0) // 2, x1 - (x1 - x0) // 6, y1), fill=BLOB)
    image.save(path)
    return path


def ink_inside(result, box, source_size, viewport):
    """Rendered text ink boxes (renderer-measured) that intersect the blob's output rectangle."""
    rect = fit_rect(source_size, viewport, result["fit"], result["focus"])
    x0, y0, x1, y1 = box
    left, top = rect.x + x0 * rect.width, rect.y + y0 * rect.height
    right, bottom = rect.x + x1 * rect.width, rect.y + y1 * rect.height
    return [b["text_bbox"] for b in result["boxes"] if b["text_bbox"]
            and min(right, b["text_bbox"][2]) > max(left, b["text_bbox"][0])
            and min(bottom, b["text_bbox"][3]) > max(top, b["text_bbox"][1])]


@pytest.mark.parametrize("where", [(.35, .05, .65, .43), (.3, .6, .7, .96)])
@pytest.mark.parametrize("aspect", ["1:1", "9:16", "16:9"])
def test_blob_on_flat_background_never_gets_text(tmp_path, where, aspect):
    source = blob_photo(tmp_path / "blob.png", where)
    with Image.open(source) as image:
        estimate = estimate_subject(image)
    assert estimate is not None and estimate["confidence"] >= MIN_CONFIDENCE
    x, y, w, h = estimate["box"]
    assert x <= where[0] and y <= where[1] and x + w >= where[2] and y + h >= where[3]
    result = render_meme(["when the build passes", "first try"], image=str(source), aspect=aspect,
                         out=str(tmp_path / "meme.png"))
    assert result["protection"]["text_clear"] is True
    if where[1] < .5 and aspect != "9:16":
        # Classic top text would cross the blob: the default moves to a caption bar.
        # (At 9:16 the blur-fit photo sits between the text bands.)
        assert result["layout"] == "caption" and any("estimated subject" in w for w in result["warnings"])
    with Image.open(result["path"]) as rendered:
        bar = _bar_height(rendered) if result["layout"] == "caption" else 0
        viewport = Rect(0, bar, rendered.width, rendered.height - bar)
    assert ink_inside(result, where, (1200, 1200), viewport) == []


def _bar_height(rendered):
    """Rows of the white caption bar at the top of a rendered meme."""
    image = rendered.convert("RGB")
    row = 0
    while row < image.height and image.getpixel((2, row)) == (255, 255, 255):
        row += 1
    return row


def test_explicit_layout_is_kept_and_the_overlap_is_stated(tmp_path):
    source = blob_photo(tmp_path / "blob.png", (.35, .05, .65, .43))
    result = render_meme(["when the build passes", "first try"], image=str(source), layout="classic",
                         out=str(tmp_path / "meme.png"))
    assert result["layout"] == "classic" and result["protection"]["text_clear"] is False
    assert any("Text box 1 overlaps the estimated subject; the requested classic layout was kept" in w
               for w in result["warnings"])
    assert "Text overlaps it because the requested layout was kept" in result["protection"]["summary"]


def test_estimate_is_honest_and_never_names_a_category(tmp_path):
    source = blob_photo(tmp_path / "blob.png", (.3, .6, .7, .96))
    result = render_meme(["one quick fix"], image=str(source), out=str(tmp_path / "meme.png"))
    summary = result["protection"]["summary"].casefold()
    for word in ("dog", "cat", "pet", "animal", "person"):
        assert word not in summary.split()
    assert "uncalibrated" in summary and "not what it is" in summary
    estimate = result["protection"]["subject_estimate"]
    assert "not recognition" in estimate["method"]
    assert estimate["evidence"]["position"] == "bottom-center"
    assert [r["kind"] for r in result["protection"]["regions"]] == ["subject_estimate"]


def test_flat_noise_and_gradient_photos_are_not_called_subjects(tmp_path):
    import random

    assert estimate_subject(Image.new("RGB", (800, 600), (120, 130, 140))) is None
    rnd = random.Random(7)
    noise = Image.new("RGB", (200, 150))
    noise.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(200 * 150)])
    assert estimate_subject(noise) is None
    sky = Image.linear_gradient("L").resize((800, 600)).convert("RGB")
    gradient = estimate_subject(sky)
    assert gradient is None or gradient["confidence"] < MIN_CONFIDENCE
    path = tmp_path / "sky.png"
    sky.save(path)
    result = render_meme(["top", "bottom"], image=str(path), out=str(tmp_path / "m.png"))
    assert result["layout"] == "classic" and result["protection"]["text_clear"]
    if gradient is not None:
        assert "reported but not protected" in result["protection"]["summary"]


def test_user_protect_box_moves_default_text_and_is_validated(tmp_path):
    path = tmp_path / "flat.png"
    Image.new("RGB", (1000, 1000), (90, 140, 200)).save(path)
    plain = render_meme(["top", "bottom"], image=str(path), out=str(tmp_path / "plain.png"))
    assert plain["layout"] == "classic" and plain["protection"]["regions"] == []
    protected = render_meme(["top", "bottom"], image=str(path), out=str(tmp_path / "p.png"),
                            protect=[[0.1, 0.0, 0.8, 0.2]])
    assert protected["layout"] == "caption" and protected["protection"]["text_clear"]
    assert protected["protection"]["regions"] == [{"kind": "user", "box": [0.1, 0.0, 0.8, 0.2], "confidence": None}]
    assert any("protect box" in w for w in protected["warnings"])
    assert user_boxes(["0.1,0.2,0.3,0.4"]) == [[0.1, 0.2, 0.3, 0.4]]
    for bad in (["0.9,0.9,0.3,0.3"], ["a,b,c,d"], [[0, 0, 0, 1]], [[0.1] * 4] * 7):
        with pytest.raises(MemeError):
            user_boxes(bad)
    # CLI and MCP take the same boxes.
    out = tmp_path / "cli.png"
    assert cli.main(["meme", "render", "--image", str(path), "--text", "top", "--text", "bottom",
                     "--protect", "0.1,0.75,0.8,0.25", "--out", str(out), "--json"]) == 0
    reply = mcp_server.h_meme_render(["top", "bottom"], image=str(path), out=str(tmp_path / "mcp.png"),
                                     protect=[[0.1, 0.75, 0.8, 0.25]])
    assert reply["ok"] and reply["layout"] == "caption" and reply["protection"]["text_clear"]


def test_template_renders_check_only_explicit_protect_boxes(tmp_path, monkeypatch):
    from myzing.memes import render as render_module

    blank = blob_photo(tmp_path / "blank.png", (.35, .05, .65, .43))
    monkeypatch.setattr(render_module, "fetch_blank", lambda template, allow_download=True: blank)
    result = render_meme(["one", "two"], template="drake", out=str(tmp_path / "t.png"))
    assert result["protection"]["subject_estimate"] is None and result["protection"]["regions"] == []
    assert "Templates are designed panels" in result["protection"]["summary"]


def test_stills_keep_text_off_the_subject_and_pick_rechecks_protect_boxes(tmp_path, zing_workspace):
    photos = tmp_path / "photos"
    photos.mkdir()
    blob_photo(photos / "blob.png", (.35, .05, .65, .43))
    result = create_stills(photos, "when the build passes", tmp_path / "stills", n=3, aspect="1:1")
    index = json.loads((tmp_path / "stills" / "index.json").read_text(encoding="utf-8"))
    estimate = index["photos"][0]["subject_estimate"]
    assert estimate["confidence"] >= MIN_CONFIDENCE
    assert any("Subject estimate (top-center" in w for w in result["warnings"])
    for concept in index["concepts"]:
        assert concept["layout"] == "caption", concept
        with Image.open(tmp_path / "stills" / concept["path"]) as rendered:
            bar = _bar_height(rendered)
            viewport = Rect(0, bar, rendered.width, rendered.height - bar)
        assert ink_inside(concept["render"], (.35, .05, .65, .43), (1200, 1200), viewport) == []
    # A user box on a flat photo: the index keeps it and pick re-checks it.
    flat = tmp_path / "flat"
    flat.mkdir()
    Image.new("RGB", (1000, 1000), (90, 140, 200)).save(flat / "flat.png")
    out = tmp_path / "flat-stills"
    assert cli.main(["still", "--photos", str(flat), "--topic", "monday standup", "--out", str(out), "--n", "2",
                     "--layout", "classic", "--protect", "0,0,1,0.3", "--json"]) == 0
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["protect"] == [[0.0, 0.0, 1.0, 0.3]]
    assert all(c["layout"] == "caption" for c in index["concepts"])
    assert any("your protect boxes" in w for c in index["concepts"] for w in c["warnings"])
    picked = pick_still(out, index["concepts"][0]["id"])
    assert picked["protection"]["text_clear"]
