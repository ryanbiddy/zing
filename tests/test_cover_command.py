import json
import sys
from pathlib import Path
import tomllib

import pytest

from myzing import cli, mcp_server
from myzing.cover import data_path, starter
from myzing.cover.contract import STYLES
from test_cover_contract import png, spec_at


def invoke(capsys, *args, code=0):
    assert cli.main(["cover", *map(str, args), "--json"]) == code
    return json.loads(capsys.readouterr().out)


def test_styles_prompt_and_packaged_assets(capsys):
    listing = invoke(capsys, "styles")
    assert set(listing["styles"]) == set(STYLES)
    assert listing["sizes"]["portrait"] == [1080, 1350]
    assert "highlight" in listing["styles"]["quote"]["required"]
    assert invoke(capsys, "prompt")["prompt"] == data_path("prompts", "cover.md").read_text(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    patterns = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["myzing"]
    packaged = {p for pattern in patterns for p in (root / "src/myzing").glob(pattern)}
    assert {data_path("cover.html"), data_path("render.cjs"), data_path("prompts", "cover.md")} <= packaged


def test_new_check_and_rerun(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(starter, "verified_model", lambda _: False)
    frame = tmp_path / "still.png"
    frame.write_bytes(png())
    folder = tmp_path / "cover"
    made = invoke(capsys, "new", folder, "--frame", frame, "--style", "plate")
    assert "centred default" in made["note"] and Path(made["frame"]).read_bytes() == frame.read_bytes()
    report = invoke(capsys, "check", folder, code=1)
    assert {p["path"] for p in report["problems"]} == {"source.name", "source.rights", "plate.top", "plate.bottom"}
    original = Path(made["cover"]).read_bytes()
    assert "exists" in invoke(capsys, "new", folder, "--frame", frame, code=1)["error"]
    assert original == Path(made["cover"]).read_bytes()
    assert "source.name: Replace" in invoke(capsys, "render", folder, code=1)["error"]
    data = spec_at(folder)
    del data["quote"]
    Path(made["cover"]).write_text(json.dumps(data))
    assert invoke(capsys, "check", folder)["valid"]
    assert "Add a quote block" in invoke(capsys, "render", folder, "--style", "quote", code=1)["error"]


def test_new_extracts_one_full_resolution_frame(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.touch()
    monkeypatch.setattr(starter, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(starter, "verified_model", lambda _: False)
    def extract(*args, **kwargs):
        assert args[args.index("-ss") + 1] == 2.25 and args[args.index("-frames:v") + 1] == 1
        assert "-vf" not in args and "-s" not in args
        Path(args[-1]).write_bytes(png(321, 181))
    monkeypatch.setattr(starter, "run", extract)
    made = starter.new(tmp_path / "cover", video=video, at=2.25)
    data = json.loads(Path(made["cover"]).read_text())
    assert data["source"]["timestamp"] == 2.25
    assert (data["frame"]["w"], data["frame"]["h"]) == (321, 181)
    for options in ({"video":video}, {"frame":video,"at":1}, {"video":video,"at":-1}):
        with pytest.raises(ValueError):
            starter.new(tmp_path / "bad", **options)


def test_mcp_tools_return_metadata_and_actionable_errors(tmp_path):
    folder = str(tmp_path / "cover")
    frame = tmp_path / "still.png"
    frame.write_bytes(png())
    assert mcp_server.h_cover_new(folder, frame=str(frame), style="quote")["ok"]
    assert "exists" in mcp_server.h_cover_new(folder, frame=str(frame))["error"]
    checked = mcp_server.h_cover_check(folder)
    assert checked["ok"] and not checked["valid"] and checked["problems"]
    assert "source.name: Replace" in mcp_server.h_cover_render(folder)["error"]


def test_yunet_selects_the_largest_box_without_fetching(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from myzing.layout.types import Box
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(frombuffer=lambda data, dtype: data, uint8="uint8"))
    frame = tmp_path / "still.png"
    frame.write_bytes(png())
    cv = SimpleNamespace(imdecode=lambda *_: object(), IMREAD_COLOR=1)
    boxes = [Box(.2, .1, .2, .2), Box(.35, .25, .3, .4)]
    detector = SimpleNamespace(cv2=cv, detect=lambda _: [SimpleNamespace(box=b) for b in boxes])
    def offline(*, download):
        assert download is False
        return detector
    monkeypatch.setattr(starter, "verified_model", lambda _: True)
    monkeypatch.setattr(starter, "YuNetDetector", offline)
    result = starter.new(tmp_path / "cover", frame=frame)
    assert result["face"] == {"cx": .5, "cy": .45, "fh": .4}
    assert "largest" in result["note"]


@pytest.mark.parametrize("entry", ["mcp", "cli"])
@pytest.mark.parametrize("directory", ["", "   ", None, 123, []])
@pytest.mark.parametrize("command", ["new", "check", "render"])
def test_refuse_invalid_directory(tmp_path, monkeypatch, capsys, directory, command, entry):
    monkeypatch.chdir(tmp_path)
    frame = tmp_path / "still.png"
    frame.write_bytes(png())
    kwargs = {"frame": str(frame)} if command == "new" else {}
    if entry == "mcp":
        result = getattr(mcp_server, "h_cover_" + command)(directory, **kwargs)
        assert result["ok"] is False
    else:
        args = ["--frame", str(frame)] if command == "new" else []
        assert cli.main(["cover", command, directory, *args, "--json"]) == 1
        result = json.loads(capsys.readouterr().out)
    assert "nonempty cover directory" in result["error"]
    assert list(tmp_path.iterdir()) == [frame]


@pytest.mark.parametrize("options,option", [({"style": None}, "--style"), ({"size": ["wide"]}, "--size")])
def test_invalid_mcp_selection_returns_error(tmp_path, options, option):
    result = mcp_server.h_cover_render(str(tmp_path), **options)
    assert not result["ok"] and option in result["error"]
