"""Headless meme contracts: stdlib paths, stable ideas, budgets, and cache."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from email.message import Message
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

from myzing import cli, doctor, mcp_server, prompt_pack, storage
from myzing.memes import MemeError
from myzing.memes.ideas import generate_ideas
from myzing.memes.render import Rect, fit_rect, layout_boxes, normalized_regions, output_size
from myzing.memes.score import viral_score
from myzing.memes.templates import _MemegenRedirect, fetch_blank, get_template, list_templates
from myzing.memes.validate import check_texts


def test_ideas_are_stable_in_fresh_processes():
    code = "import json; from myzing.memes.ideas import generate_ideas; print(json.dumps(generate_ideas('release day')))"
    outputs = []
    for seed in ("1", "87"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        outputs.append(subprocess.check_output([sys.executable, "-c", code], env=env))
    assert outputs[0] == outputs[1]
    assert generate_ideas("release day") != generate_ideas("laundry day")


def test_eight_formulas_are_distinct_and_budgeted():
    ideas = generate_ideas("trying to fix a bug in a very long project name", n=8)
    assert len({i["formula"] for i in ideas}) == 8
    assert len({tuple(i["texts"]) for i in ideas}) == 8
    assert all(i["validation"]["valid"] for i in ideas)
    assert "Wildcard" in {i["title"] for i in ideas}


@pytest.mark.parametrize("template", list_templates(), ids=lambda t: t["id"])
def test_every_template_has_complete_budgeted_ideas(template):
    for idea in generate_ideas("fixing the build with a really long topic", template["id"], n=8):
        assert len(idea["texts"]) == template["box_count"]
        assert idea["validation"]["valid"], idea


def test_template_grammar():
    assert generate_ideas("builds", "drake", 1)[0]["texts"] == ["a 47-slide plan for builds", "one meme"]
    assert generate_ideas("builds", "db", 1)[0]["texts"] == ["builds", "me", "my actual priorities"]
    assert generate_ideas("builds", "gb", 1)[0]["texts"][-1] == "calling the chaos iterative"
    assert generate_ideas("builds", "astronaut", 1)[0]["texts"][:2] == ["", ""]


@pytest.mark.parametrize("kwargs", [{"topic": ""}, {"topic": "x", "n": 0}, {"topic": "x", "n": 9},
                                    {"topic": "x", "n": True}, {"topic": "x", "template": "../../bad"}])
def test_invalid_idea_requests(kwargs):
    with pytest.raises(MemeError):
        generate_ideas(**kwargs)


@pytest.mark.parametrize("texts,valid,codes", [
    (["a" * 70, "b" * 40], True, set()),
    (["a" * 71], False, {"line_too_long"}),
    (["a" * 70, "b" * 41], False, {"total_too_long"}),
    ([], False, {"beat_count"}),
    (["", " "], False, {"beat_count"}),
    (["1", "2", "3", "4"], False, {"beat_count"}),
    (["Nobody:", "That moment when", "Also me:"], False, {"banned_filler"}),
    (["nobody move", "my actual priorities"], True, set()),
    (["é" * 70, "🙂" * 40], True, set()),
])
def test_text_budgets(texts, valid, codes):
    result = check_texts(texts)
    assert result["valid"] is valid
    assert {p["code"] for p in result["problems"]} == codes


def test_normalization_preserves_linebreaks_and_empty_slots():
    result = check_texts(["  one   quick\n fix  ", "", "  me "])
    assert result["texts"] == ["one quick\nfix", "", "me"]
    assert result["characters"] == 15
    assert result["beats"] == 2
    assert check_texts(["a"] * 6, box_count=6)["valid"]
    assert not check_texts(["a"] * 7, box_count=6)["valid"]
    with pytest.raises(MemeError):
        check_texts("not an array")


def test_catalog_is_metadata_only_and_has_valid_regions(monkeypatch):
    monkeypatch.setattr("myzing.memes.templates.build_opener", lambda *a: pytest.fail("network"))
    catalog = list_templates()
    assert len(catalog) == 101
    assert len({t["id"] for t in catalog}) == len(catalog)
    for template in catalog:
        assert len(normalized_regions(template["box_layout"])) == template["box_count"]
        assert template["memegen_id"] == template["id"]
    assert list_templates("DRAKE")[0]["id"] == "drake"
    assert get_template("memegen-drake") == get_template("drake")


def test_geometry_presets_cover_contain_and_label_mapping():
    assert [output_size(a, (400, 300)) for a in ("16:9", "1:1", "4:5", "9:16")] == [
        (1200, 675), (1080, 1080), (1080, 1350), (1080, 1920)]
    assert output_size("original", (400, 200)) == (1200, 600)
    square = Rect(0, 0, 100, 100)
    assert fit_rect((200, 100), square, "cover") == Rect(-50, 0, 200, 100)
    contain = fit_rect((200, 100), square, "contain")
    assert contain == Rect(0, 25, 100, 50)
    assert layout_boxes("labels", 1, (100, 100), regions=[[0, 0, 1, 1]], image_rect=contain) == [contain]
    top, bottom = layout_boxes("classic", 2, (1080, 1080))
    assert top.y + top.height < bottom.y


@pytest.mark.parametrize("regions", [[], [[0, 0, -1, .5]], [[.9, 0, .2, .2]], [[0, 0, float("nan"), 1]],
                                     [[0, 0, True, 1]], [[0, 1]], "bad"])
def test_invalid_regions(regions):
    with pytest.raises(MemeError):
        normalized_regions(regions)


def test_crop_does_not_silently_drop_label():
    with pytest.raises(MemeError, match="cropped"):
        layout_boxes("labels", 1, (100, 100), regions=[[0, 0, .1, .1]], image_rect=Rect(-100, 0, 300, 100))


def test_viral_lens_is_an_honest_still_heuristic():
    result = viral_score(["setup", "payoff"], aspect="1:1", contrast=[True, True])
    assert result["score"] == 92
    assert result["predicts_reach"] is False
    assert viral_score(["x" * 160], aspect="9:16")["score"] == 52
    assert viral_score([""], contrast=[True])["score"] < result["score"]


class Response(io.BytesIO):
    def __init__(self, data, content_type="image/jpeg"):
        super().__init__(data)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


def test_template_fetch_is_opt_in_and_cached(zing_workspace, monkeypatch):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout))
            return Response(b"\xff\xd8\xffmock-jpeg")
    monkeypatch.setattr("myzing.memes.templates.build_opener", lambda *args: Opener())
    with pytest.raises(MemeError, match="not cached"):
        fetch_blank("drake")
    assert calls == []
    target = fetch_blank("drake", allow_download=True)
    assert target == storage.workspace_root().resolve() / "memes/templates/drake.jpg"
    assert fetch_blank("drake") == target
    assert calls == [("https://api.memegen.link/images/drake.jpg", 15)]
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize("data,content_type", [(b"html", "text/html"), (b"bad", "image/jpeg"), (b"", "image/jpeg")])
def test_invalid_download_does_not_poison_cache(zing_workspace, monkeypatch, data, content_type):
    class Opener:
        def open(self, *args, **kwargs):
            return Response(data, content_type)
    monkeypatch.setattr("myzing.memes.templates.build_opener", lambda *args: Opener())
    with pytest.raises(MemeError):
        fetch_blank("drake", allow_download=True)
    assert not (storage.workspace_root() / "memes/templates/drake.jpg").exists()


def test_download_size_limit_and_network_error(zing_workspace, monkeypatch):
    from myzing.memes import templates
    monkeypatch.setattr(templates, "MAX_IMAGE_BYTES", 8)
    class Opener:
        def open(self, *args, **kwargs):
            return Response(b"\xff\xd8\xff1234567890")
    monkeypatch.setattr(templates, "build_opener", lambda *args: Opener())
    with pytest.raises(MemeError, match="limit"):
        fetch_blank("drake", allow_download=True)
    def refuse(*args):
        raise URLError("offline")
    monkeypatch.setattr(templates, "build_opener", refuse)
    with pytest.raises(MemeError, match="local photo"):
        fetch_blank("drake", allow_download=True)


def test_redirects_cannot_escape_memegen():
    with pytest.raises(MemeError, match="outside"):
        _MemegenRedirect().redirect_request(Request("https://api.memegen.link"), None, 302, "", {}, "https://example.com/photo")


def test_optional_pillow_doctor(monkeypatch):
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    check = doctor.check_pillow()
    assert not check.ok and check.tier == doctor.OPTIONAL and "myzing[memes]" in check.fix
    monkeypatch.setattr(doctor, "_has_module", lambda name: name == "PIL")
    assert doctor.check_pillow().ok


def test_core_without_site_packages_or_network(tmp_path):
    # -S excludes Pillow, MCP, and every other installed dependency.
    code = """
import json, socket
socket.create_connection = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('network'))
from myzing.mcp_server import h_meme_ideas, h_meme_templates, h_meme_check, h_meme_render
assert h_meme_ideas('builds')['ok']
assert h_meme_templates()['ok']
assert h_meme_check(['setup', 'payoff'])['valid']
result = h_meme_render(['hello'], image='anything.png')
assert result['ok'] is False and 'myzing[memes]' in result['error'], result
print('core works without Pillow')
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "ZING_HOME": str(tmp_path)}
    proc = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr


def test_cli_json_and_mcp_checks(capsys):
    assert cli.main(["meme", "templates", "--search", "drake", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["templates"][0]["id"] == "drake"
    assert cli.main(["meme", "--json", "check", "--text", "a" * 71]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and not result["valid"]
    assert cli.main(["meme", "ideas", "--topic", "builds", "--n", "0", "--json"]) == 1
    assert not json.loads(capsys.readouterr().out)["ok"]
    assert mcp_server.h_meme_check(["1", "2", "3", "4"], template="gb")["valid"]
    assert not mcp_server.h_meme_ideas("x", template="not-a-template")["ok"]
    assert not mcp_server.h_meme_render(["hello"])["ok"]


def test_prompt_and_fonts_ship_with_provenance(monkeypatch):
    monkeypatch.delenv(prompt_pack.PROMPTS_DIR_ENV, raising=False)
    meta, prompt = prompt_pack.load_prompt("meme-writer")
    assert meta["required_keys"] == ["ideas"]
    assert all(s in prompt for s in ("70", "110", "meme_check", "meme_render", "wildcard"))
    data = Path(__file__).resolve().parents[1] / "src/myzing/_data"
    assert (data / "prompts/meme-writer.md").read_bytes() == (data.parents[2] / "prompts/meme-writer.md").read_bytes()
    for record in json.loads((data / "fonts/sources.json").read_text()):
        assert hashlib.sha256((data / "fonts" / record["file"]).read_bytes()).hexdigest() == record["sha256"]
    assert "SIL OPEN FONT LICENSE" in (data / "fonts/Anton-OFL.txt").read_text()
    assert "SIL OPEN FONT LICENSE" in (data / "fonts/IBMPlexSans-OFL.txt").read_text(encoding="utf-8")
