"""Factory reads leave the project intact; writes retain their existing effects."""
import json

import pytest

from myzing import mcp_server
from myzing.factory import judge, pipeline, postcopy


@pytest.fixture
def project(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unexpected judge call")
    monkeypatch.setattr(judge.Judge, "_claude", refuse)
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"local fixture")
    root = tmp_path / "project"
    pipeline.init(root, media, moments=0, offline=True)
    pipeline._write(root / "status.json", {"state": "running"})
    with pytest.raises(judge.NeedsAnswer):
        judge.Judge(root).ask("clip01-copy", "Write the post copy.")
    return root


def test_factory_reads_leave_files_unchanged(project):
    def snapshot():
        return {p.relative_to(project): (p.read_bytes(), p.stat().st_mtime_ns)
                if p.is_file() else None for p in project.rglob("*")}
    before = snapshot()
    for _ in range(2):
        status = mcp_server.h_factory_status(str(project))
        assert status["ok"] and status["state"] == "interrupted"
        assert status["pending"][0]["task"] == "clip01-copy"
        prompt = mcp_server.h_factory_prompt(str(project), "clip01-copy")
        assert prompt["ok"] and prompt["prompt"] == "Write the post copy."
    assert snapshot() == before


def test_factory_answer_replaces_existing_work(project):
    first = {field: "First draft" for field in postcopy.FIELDS}
    second = {field: "Revised draft" for field in postcopy.FIELDS}
    pipeline._write(project / "answers" / "clip01-copy.json", first)
    assert mcp_server.h_factory_answer(str(project), "clip01-copy", second)["ok"]
    assert json.loads((project / "answers" / "clip01-copy.json").read_text()) == second
    assert not (project / "pending" / "clip01-copy.md").exists()


def test_factory_run_uses_host_judge(project, monkeypatch):
    calls = []

    def run(root, ask, **kwargs):
        calls.append((root, ask.backend))
    monkeypatch.setattr(pipeline, "run", run)
    mcp_server._run_factory(project)
    assert calls == [(project, "host")]
