"""Whole-word fitting and the text actually emitted to the preset renderer."""

from pathlib import Path
import re

import pytest

from myzing.brief.models import Brief
from myzing.captions.grouping import STOPWORDS, group_words, join, token
from myzing.captions.metrics import metrics
from myzing.captions.presets import apply_preset, fit_long_words, line_widths, phone_floor, rail_width
from myzing.captions.render import compile_caption
from myzing.composition import Composition
from myzing.layout.framing import place_captions
from myzing.render.font_files import private_font
from myzing.schemas import Word
from test_caption2 import plan, words


@pytest.mark.parametrize("preset", ["punch", "box"])
@pytest.mark.parametrize("text", [
    "of our everyday lives.",
    "from the International Space Station.",
    "how we use it in microgravity.",
    "using the corresponding classroom connection.",
])
def test_whole_words_survive_protected_prefix(text, preset):
    p = plan(text, 1080, 1920)
    apply_preset(p, preset, vad=False)
    assert [w.text for c in p.captions for w in c.words] == text.split()
    assert not any("split into" in warning for warning in p.warnings)
    for c in p.captions:
        assert max(line_widths(c, metrics(c.font.path, c.font.sha256), c.style)) <= rail_width(p.width, p.height)


def test_prefix_break_is_only_a_grouping_fallback():
    timed = words("of our everyday lives.")
    kept, shown, solo, notes = fit_long_words(timed, str, lambda ts: len(join(ts)), 10)
    assert kept == timed and shown == [w.text for w in timed]
    assert not solo and not notes
    groups, *_ = group_words(kept, lambda ts: len(join(ts)), 10, preset="punch")
    assert [join(w.text for w in g) for g in groups] == ["of our", "everyday", "lives."]
    # When a legal partition exists, never choose a dangling stopword instead.
    timed = words("we go a way with big hopes and new goals")
    groups, *_ = group_words(timed, lambda ts: len(join(ts)), 14, preset="punch")
    assert all(token(g[-1]) not in STOPWORDS for g in groups[:-1])


@pytest.mark.parametrize("preset,text,size", [
    ("punch", "corresponding", 97),
    ("box", "WWWWWWWWW", 100),
])
def test_oversize_word_uses_readable_solo_scale(preset, text, size):
    p = plan(f"look here {text} then go", 1080, 1920)
    p.brief = Brief(caption_options={"size": size})
    apply_preset(p, preset, vad=False)
    c = next(c for c in p.captions if any(w.text == text for w in c.words))
    assert [w.text for w in c.words] == [text]
    assert phone_floor(p, c.start, c.end, preset) <= c.style.size < size
    assert any("shown alone at" in note for note in p.warnings)
    place_captions(p, {}, {})
    assert c.style.size*c.layout.scale >= phone_floor(p, c.start, c.end, preset)-1e-6


def test_floor_split_preserves_span_and_marks_all_nonfinal_pieces():
    text = "https://example.com/" + "x"*40
    assert len(text) == 60
    word = Word(text, 1., 7.)
    kept, shown, solo, notes = fit_long_words(
        [Word("of", .1, .5), word], str, lambda ts: len(join(ts)), 12, scales=(1., .9, .8))
    pieces = kept[1:]
    assert len(pieces) > 1
    assert "".join(w.text for w in pieces) == text
    assert all(s.endswith("-") for s in shown[1:-1])
    assert pieces[0].start == word.start and pieces[-1].end == word.end
    assert all(a.start < a.end == b.start < b.end for a, b in zip(pieces, pieces[1:]))
    assert all(w.end-w.start == pytest.approx((word.end-word.start)*len(w.text)/len(text)) for w in pieces)
    assert all(solo[i] == .8 for i in range(1, len(kept)))
    assert any("split into" in note and "proportional timing" in note for note in notes)


@pytest.mark.parametrize("preset", ["punch", "box"])
def test_split_hyphens_reach_drawn_text_after_reapplication(preset):
    text = "https://example.com/" + "x"*40
    p = plan(text, 1080, 1920)
    # Give each split piece enough time that cue scheduling need not trim it.
    p.captions[0].words = [Word(text, .2, 6.2)]
    p.captions[0].end = 6.2
    p.clips[0].src_out = p.assets[0].duration = 7.
    for _ in range(2):
        apply_preset(p, preset, vad=False)
        place_captions(p, {}, {})
        pieces = [(c, w) for c in p.captions for w in c.words]
        assert len(pieces) > 1
        assert "".join(w.text for _, w in pieces) == text
        assert pieces[0][1].start == .2 and pieces[-1][1].end == 6.2
        assert all(a.end == b.start for (_, a), (_, b) in zip(pieces, pieces[1:]))
        for c, word in pieces[:-1]:
            data = Path(c.font.path).read_bytes()
            events, _ = compile_caption(c, p, private_font(data)[0], data, 210)
            drawn = [re.sub(r"\{[^}]*\}", "", event.split(",", 9)[9]).rstrip("\n")
                     for event in events if event.startswith("Dialogue: 1,")]
            assert word.text.upper()+"-" in drawn
        # Delivery adaptation and option changes can rebuild from serialized words.
        p = Composition.from_dict(p.to_dict())


def test_clean_keeps_prefix_aware_fitting():
    timed = [Word("the", 0, .5), Word("everyday", .5, 1.5)]
    kept, shown, solo, notes = fit_long_words(
        timed, str, lambda ts: len(join(ts)), 10, keep_whole=False)
    assert [w.text for w in kept] == ["the", "every", "day"]
    assert shown == ["the", "every-", "day"]
    assert not solo and len(notes) == 1
