"""Story CLI integration with generated audio and no voice model or browser."""
from __future__ import annotations

import json
import re
import struct
import tomllib
import wave
import zlib
from pathlib import Path

import pytest

from myzing import cli
from myzing.story import StoryError, command, contract, receipt


def story_file(tmp_path: Path) -> dict:
    story = {
        "topic": "a paper moon", "handle": "", "cast": {},
        "sources": [{"title": "Invented test story", "url": "https://example.org/story"}],
        "beats": [{"id": name, "lines": [{"text": text}]} for name, text in (
            ("hook", "A paper moon would not fit."), ("problem", "The door was too narrow."),
            ("fix", "A hinge let it fold."), ("end", "The moon made its entrance."))],
        "panels": [{"from": "hook", "set": {"wall": "#FFD21F", "floor": "#17161C"}}],
    }
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    return story


def line_files(tmp_path: Path, story: dict) -> Path:
    directory = tmp_path / "lines"
    directory.mkdir()
    for beat in story["beats"]:
        for index, _line in enumerate(beat["lines"]):
            with wave.open(str(directory / f"{beat['id']}-{index}.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(1000)
                audio.writeframes(b"\x00\x04" * 250)
    return directory


def test_cli_routes_story_and_checks_a_good_file(tmp_path, capsys):
    story_file(tmp_path)
    assert cli.main(["story", "check", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert "story" in cli._usage()


def test_check_prints_every_problem(tmp_path, capsys):
    story = story_file(tmp_path)
    story["topic"] = ""
    story["sources"] = []
    story["beats"][0]["lines"][0]["text"] = "word " * 23
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    assert command.run(["check", str(tmp_path)]) == 1
    errors = capsys.readouterr().err
    assert "topic" in errors and "sources" in errors and "22" in errors


@pytest.mark.parametrize("contents", [None, "{bad json"])
def test_check_reports_missing_or_malformed_json(tmp_path, contents, capsys):
    if contents is not None:
        (tmp_path / "story.json").write_text(contents, encoding="utf-8")
    assert command.run(["check", str(tmp_path)]) == 1
    assert "cannot read story.json" in capsys.readouterr().err


def test_voice_lines_cli_writes_real_audio_and_metadata(tmp_path, capsys):
    story = story_file(tmp_path)
    lines = line_files(tmp_path, story)
    assert command.run(["voice", str(tmp_path), "--lines-dir", str(lines)]) == 0
    timing = json.loads(capsys.readouterr().out)
    assert timing["provider"] == "lines" and timing["voice"] is None
    assert timing["beats"][0]["lines"][0] == {"text": "A paper moon would not fit.", "start": 0.35, "end": 0.6}
    assert timing["outro_start"] == 3.19
    assert timing["duration"] == 6.39
    assert json.loads((tmp_path / "timings.json").read_text(encoding="utf-8")) == timing
    with wave.open(str(tmp_path / "narration.wav"), "rb") as audio:
        assert audio.getnframes() == 6390


def test_heads_without_photos_needs_no_image_package(tmp_path, capsys):
    story_file(tmp_path)
    assert command.run(["heads", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"heads": []}


def test_render_cli_passes_still_times_and_output(tmp_path, monkeypatch, capsys):
    from myzing.story import render

    observed = {}

    def capture(directory, *, out, stills):
        observed.update(directory=directory, out=out, stills=stills)
        return [tmp_path / "stills" / "first.jpg"]

    monkeypatch.setattr(render, "render", capture)
    assert command.run(["render", str(tmp_path), "--stills", "0,1.25,3", "--out", "review.mp4"]) == 0
    assert observed == {"directory": tmp_path, "out": Path("review.mp4"), "stills": [0, 1.25, 3]}
    assert json.loads(capsys.readouterr().out)["stills"] == [str(tmp_path / "stills" / "first.jpg")]


@pytest.mark.parametrize("times", ["", "1,", "-1", "nan", "inf", "one"])
def test_bad_still_times_fail_at_cli_parse(tmp_path, times):
    with pytest.raises(SystemExit) as exc:
        command.run(["render", str(tmp_path), f"--stills={times}"])
    assert exc.value.code == 2


def test_build_uses_generated_audio_then_writes_receipt(tmp_path, monkeypatch, capsys):
    from myzing.story import render

    story = story_file(tmp_path)
    lines = line_files(tmp_path, story)
    output = tmp_path / "final.mp4"

    def capture(directory, *, out):
        assert (directory / "narration.wav").is_file()
        assert json.loads((directory / "timings.json").read_text(encoding="utf-8"))["provider"] == "lines"
        assert out == output
        output.write_bytes(b"test render output")
        return output

    monkeypatch.setattr(render, "render", capture)
    assert command.run(["build", str(tmp_path), "--lines-dir", str(lines), "--out", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
    assert saved == {"look": "cutout", "voice": {"provider": "lines", "name": None, "synthetic": False}, "photos": [],
                     "sources": story["sources"], "output": "final.mp4", "duration": 6.39}


def test_failed_build_does_not_write_a_receipt(tmp_path, monkeypatch, capsys):
    from myzing.story import render

    story = story_file(tmp_path)
    lines = line_files(tmp_path, story)

    def refuse(*args, **kwargs):
        raise StoryError("render did not finish")

    monkeypatch.setattr(render, "render", refuse)
    assert command.run(["build", str(tmp_path), "--lines-dir", str(lines)]) == 2
    assert "render did not finish" in capsys.readouterr().err
    assert not (tmp_path / "story-receipt.json").exists()


def test_receipt_requires_a_finished_output(tmp_path):
    story_file(tmp_path)
    (tmp_path / "timings.json").write_text(json.dumps({"provider": "kokoro", "voice": "af_heart", "duration": 3}), encoding="utf-8")
    with pytest.raises(StoryError, match="output file is missing"):
        receipt.write(tmp_path, tmp_path / "absent.mp4")


def test_receipt_preserves_photo_rights(tmp_path):
    story = story_file(tmp_path)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    # Draw one flat green pixel using only stdlib, with no image dependency.
    (tmp_path / "drawn.png").write_bytes(b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x20\x80\x40")) + chunk(b"IEND", b""))
    story["cast"] = {"mira": {"name": "Mira Vale", "photos": [{"path": "drawn.png", "credit": "Test artist",
                           "license": "CC BY 4.0", "source_url": "https://example.org/drawing"}]}}
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    (tmp_path / "timings.json").write_text(json.dumps({"provider": "kokoro", "voice": "af_heart", "duration": 3}), encoding="utf-8")
    output = tmp_path / "story.mp4"
    output.write_bytes(b"test render output")
    saved = json.loads(receipt.write(tmp_path, output).read_text(encoding="utf-8"))
    assert saved["voice"] == {"provider": "kokoro", "name": "af_heart", "synthetic": True}
    assert saved["photos"] == [{"cast": "mira", "name": "Mira Vale", **story["cast"]["mira"]["photos"][0]}]


def test_documented_example_passes_the_real_contract():
    root = Path(__file__).resolve().parents[1]
    docs = (root / "docs" / "STORY.md").read_text(encoding="utf-8")
    example = json.loads(re.search(r"```json\n(.*?)\n```", docs, re.S).group(1))
    assert contract.check(example) == []


def test_story_voice_is_optional_and_data_ships_in_the_package():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]
    assert not any("kokoro" in item for group in extras.values() for item in group)
    assert not any("kokoro" in item for item in project["project"]["dependencies"])
    data = project["tool"]["setuptools"]["package-data"]["myzing"]
    assert {"_data/story/*.html", "_data/story/*.cjs", "_data/story/*.json", "_data/story/prompts/*.md"} <= set(data)


def test_new_has_only_the_source_placeholder_problem_and_build_refuses_it(tmp_path, capsys):
    folder = tmp_path / "draft"
    assert command.run(["new", str(folder), "--topic", "a paper moon"]) == 0
    capsys.readouterr()
    starter = json.loads((folder / "story.json").read_text(encoding="utf-8"))
    assert all(not cast.get("photos") for cast in starter["cast"].values())
    problems = contract.check(starter, folder)
    assert len(problems) == 1 and "replace this source" in problems[0]
    assert command.run(["build", str(folder)]) == 2
    assert "replace this source" in capsys.readouterr().err
    assert not (folder / "narration.wav").exists()
    assert "zing story prompt" in (folder / "README-STORY.txt").read_text(encoding="utf-8")
    starter["sources"] = [{"title": "Checked source", "url": "https://example.org/research"}]
    assert contract.check(starter, folder) == []


def test_new_does_not_overwrite_an_existing_story(tmp_path):
    original = story_file(tmp_path)
    with pytest.raises(StoryError, match="already exists"):
        command.new(tmp_path, topic="changed")
    assert json.loads((tmp_path / "story.json").read_text(encoding="utf-8")) == original


def test_prompt_prints_the_bundled_prompt(capsys):
    from myzing.story import data_path

    assert command.run(["prompt"]) == 0
    assert capsys.readouterr().out == data_path("prompts", "story.md").read_text(encoding="utf-8")


def test_json_check_emits_only_structured_problems(tmp_path, capsys):
    story = story_file(tmp_path)
    story["topic"] = ""
    story["sources"] = []
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    assert command.run(["check", str(tmp_path), "--json"]) == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == [
        {"path": "topic", "message": "must be non-empty text"},
        {"path": "sources", "message": "needs 1 or more entries"},
    ]
    story_file(tmp_path)
    assert command.run(["check", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_json_check_unreadable_story_is_a_problem(tmp_path, capsys):
    assert command.run(["check", str(tmp_path), "--json"]) == 1
    problems = json.loads(capsys.readouterr().out)
    assert problems[0]["path"] == "story.json"
    assert "cannot read story.json" in problems[0]["message"]


@pytest.mark.parametrize("action", ["render", "build"])
def test_no_sfx_flag_reaches_renderer(tmp_path, monkeypatch, capsys, action):
    from myzing.story import render

    value = story_file(tmp_path)
    lines = line_files(tmp_path, value)
    seen = {}

    def capture(directory, **kwargs):
        seen.update(kwargs)
        output = directory / "story.mp4"
        output.write_bytes(b"fake rendered clip")
        return output

    monkeypatch.setattr(render, "render", capture)
    args = [action, str(tmp_path), "--no-sfx"]
    if action == "build":
        args += ["--lines-dir", str(lines)]
    assert command.run(args) == 0
    capsys.readouterr()
    assert seen["no_sfx"] is True


def test_heads_sheet_cli(tmp_path, monkeypatch, capsys):
    from myzing.story import heads

    story_file(tmp_path)
    calls = []
    monkeypatch.setattr(heads, "generate", lambda directory, story, **kw: calls.append(kw) or [])
    assert command.run(["heads", str(tmp_path), "--sheet"]) == 0
    assert calls == [{"sheet": True}]
    assert json.loads(capsys.readouterr().out)["sheet"].endswith("sheet.png")


@pytest.mark.parametrize("provider", ["kokoro", "elevenlabs"])
def test_voice_provider_flag_reaches_generate(tmp_path, monkeypatch, capsys, provider):
    from myzing.story import voice

    story_file(tmp_path)
    seen = {}
    monkeypatch.setattr(voice, "generate", lambda directory, story, **kwargs: seen.update(kwargs) or {})
    assert command.run(["voice", str(tmp_path), "--provider", provider, "--voice", "test-voice"]) == 0
    capsys.readouterr()
    assert seen["provider"] == provider and seen["voice"] == "test-voice"


@pytest.mark.parametrize("action", ["voice", "build"])
@pytest.mark.parametrize("explicit", [True, False])
def test_elevenlabs_reaches_voice_provider(tmp_path, monkeypatch, capsys, action, explicit):
    from myzing import tts_providers
    from myzing.render.tts import SynthesisResult
    from myzing.story import render
    from myzing.story.outro import credit_lines
    from test_story_voice import write_wav

    story = story_file(tmp_path)
    calls = []

    class FakeProvider:
        name = "elevenlabs"

        def synthesize(self, request, output_path):
            calls.append(request.text)
            write_wav(output_path, 250)
            return SynthesisResult(output_path, self.name, "test-voice", 1000, .25)

    def capture(directory, **kwargs):
        output = directory / "story.mp4"
        output.write_bytes(b"test render")
        return output

    monkeypatch.setattr(tts_providers, "_REGISTRY", {"elevenlabs": FakeProvider})
    monkeypatch.setenv("ZING_TTS_PROVIDER", "kokoro" if explicit else "elevenlabs")
    monkeypatch.setattr(render, "render", capture)
    args = [action, str(tmp_path)] + (["--provider", "elevenlabs"] if explicit else [])
    assert command.run(args) == 0
    capsys.readouterr()
    assert calls == [line["text"] for beat in story["beats"] for line in beat["lines"]]
    timings = json.loads((tmp_path / "timings.json").read_text(encoding="utf-8"))
    assert timings["provider"] == "elevenlabs" and timings["synthetic"] is True
    assert "narration is an AI voice" in credit_lines(story, timings)


def test_images_cli_and_build_prepare_declared_images(tmp_path, monkeypatch, capsys):
    from myzing.story import images, render

    value = story_file(tmp_path)
    lines = line_files(tmp_path, value)
    calls = []
    monkeypatch.setattr(images, "generate", lambda directory, story, **kw: calls.append(kw) or [])
    assert command.run(["images", str(tmp_path), "--sheet"]) == 0
    assert json.loads(capsys.readouterr().out)["sheet"].endswith("sheet.png")

    def capture(directory, **kwargs):
        output = directory / "story.mp4"
        output.write_bytes(b"test render")
        return output

    monkeypatch.setattr(render, "render", capture)
    assert command.run(["build", str(tmp_path), "--lines-dir", str(lines)]) == 0
    assert calls == [{"sheet": True}, {}]


@pytest.mark.parametrize("as_json", [True, False])
def test_find_cli_lists_candidates_and_refusals(monkeypatch, capsys, as_json):
    from myzing.story import commons

    result = [{"title": "File:Drawing.png", "license": "CC BY-NC 4.0", "credit": "Test artist",
               "width": 900, "height": 600, "bytes": 12000, "accepted": False,
               "reason": "NC licenses are refused", "source_url": "https://commons.wikimedia.org/wiki/File:Drawing.png"}]
    monkeypatch.setattr(commons, "find", lambda query, limit: result if query == "drawing" and limit == 2 else [])
    assert command.run(["find", "drawing", "--limit", "2"] + (["--json"] if as_json else [])) == 0
    output = capsys.readouterr().out
    if as_json:
        assert json.loads(output) == result
    else:
        assert "refused: NC licenses are refused" in output and "900x600" in output
        assert "Test artist" in output and result[0]["source_url"] in output


def test_fetch_cli_passes_exact_title_and_target(tmp_path, monkeypatch, capsys):
    from myzing.story import commons

    seen = []
    monkeypatch.setattr(commons, "fetch", lambda *args: seen.append(args) or {"target": args[2]})
    assert command.run(["fetch", str(tmp_path), "File:Drawing.png", "--as", "image:drawing"]) == 0
    assert seen == [(tmp_path, "File:Drawing.png", "image:drawing")]
    assert json.loads(capsys.readouterr().out) == {"target": "image:drawing"}


def test_music_credit_is_in_generated_end_card_and_receipt(tmp_path):
    from myzing.story.outro import prepare
    from test_story_audio import tone

    value = story_file(tmp_path)
    tone(tmp_path / "tone.wav", duration=.1)
    music = {"path": "tone.wav", "credit": "Test tone", "license": "CC0",
             "source_url": "https://example.org/test-tone"}
    value["music"] = music
    (tmp_path / "story.json").write_text(json.dumps(value), encoding="utf-8")
    timings = {"provider": "elevenlabs", "voice": "test", "duration": 3}
    (tmp_path / "timings.json").write_text(json.dumps(timings), encoding="utf-8")
    card = prepare(value, timings)["panels"][-1]["cards"][-1]
    assert "music: Test tone · CC0" in card["lines"]
    assert "narration is an AI voice" in card["lines"]
    output = tmp_path / "story.mp4"
    output.write_bytes(b"test output")
    saved = json.loads(receipt.write(tmp_path, output).read_text(encoding="utf-8"))
    assert saved["music"] == music
    assert saved["voice"]["synthetic"] is True
