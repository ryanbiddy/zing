"""Independent raster masks test fill geometry on textured footage and plates."""

from pathlib import Path

import pytest

from myzing.study.caption_pixels import measure, segment


@pytest.mark.parametrize("light,plate,stroke", [(True, False, 0), (False, False, 0),
                                              (True, True, 0), (True, False, 2)])
def test_ink_excludes_textured_background_and_measures_color(light, plate, stroke):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    Image = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw, ImageFont
    font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "src/myzing/_data/fonts/Anton-Regular.ttf"), 38)
    yy, xx = np.indices((180, 450))
    background = (75 if light else 190) + ((xx//9 + yy//7) % 2)*18
    image = Image.fromarray(np.repeat(background[:, :, None], 3, axis=2).astype(np.uint8))
    drawing = ImageDraw.Draw(image)
    if plate:
        drawing.rectangle((30, 65, 370, 130), fill=(25, 25, 25))
    fill = (240, 240, 240) if light else (20, 20, 20)
    drawing.text((45, 70), "CLEAN INK", font=font, fill=fill, stroke_width=stroke,
                 stroke_fill=(15, 15, 15))
    oracle = Image.new("L", image.size)
    ImageDraw.Draw(oracle).text((45, 70), "CLEAN INK", font=font, fill=255)
    ys, xs = np.nonzero(np.asarray(oracle) > 127)
    expected = [xs.min()/450, ys.min()/180, (xs.max()+1)/450, (ys.max()+1)/180]
    polygon = [[(xs.min()-10)/450, (ys.min()-8)/180], [(xs.max()+12)/450, (ys.min()-8)/180],
               [(xs.max()+12)/450, (ys.max()+10)/180], [(xs.min()-10)/450, (ys.max()+10)/180]]
    result, mask, origin = segment(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR), polygon, "CLEAN INK")
    assert result["ink_box"] is not None and mask is not None
    assert max(abs(a-b) for a, b in zip(result["ink_box"], expected)) < .015
    assert max(abs(a-b) for a, b in zip(result["fill"]["rgb"], fill)) < 15
    assert result["cap_height"] is not None and result["x_height"] is None
    assert result["ink_evidence"]["component_count"] >= 6


def test_flat_polygon_has_no_ink_or_invented_colors():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    result = measure(np.full((100, 200, 3), 100, np.uint8), [[.1, .1], [.9, .1], [.9, .8], [.1, .8]])
    assert result["ink_box"] is result["fill"] is result["outline"] is None
    assert result["geometry_confidence"] == 0

