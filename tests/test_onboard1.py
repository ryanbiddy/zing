"""First-run consent, offline inventory, verified bytes and recovery contracts."""

import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from myzing import model_fetch
from myzing.study import speech_models as speech
from myzing.studio import command, flow, jobs
from myzing.studio.models import Session, load_session, save_session, write_json
from test_studio import inputs, complete


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf/hub"))
    monkeypatch.delenv("ZING_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(model_fetch.urllib.request, "urlopen", lambda *a, **k: pytest.fail("unconsented network"))


@pytest.fixture
def pins(monkeypatch):
    payload = b"model fixture"
    files = {name: {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
             for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")}
    monkeypatch.setattr(speech, "MODELS", {name: {"revision": "a" * 40, "files": files}
                                         for name in ("small.en", "large-v2")})
    return payload


def interview(inputs):
    return f"1\n{inputs['source']}\n{inputs['clips']}\na local story\n\n12\nphone\n\n"


@pytest.mark.parametrize("choice,model", [("", "small.en"), ("1", "small.en"), ("2", "large-v2"), ("3", "skip")])
def test_model_stdin_choices_and_finish_receipt(inputs, monkeypatch, capsys, pins, choice, model):
    calls = []
    def download(url, **kwargs):
        calls.append(url)
        assert load_session(inputs["project"]).answers["speech_download"] is True
        return io.BytesIO(pins)
    monkeypatch.setattr(model_fetch.urllib.request, "urlopen", download)
    def execute(a, **kwargs):
        receipt = speech.prepare(a, progress=kwargs["progress"])
        return {"ok": True, "status": "ready", "speech_setup": receipt, "outputs": [], "warnings": []}
    monkeypatch.setattr("myzing.studio.execute.run_confirmed", execute)
    transcript = interview(inputs) + choice + "\n" + ("yes\n" if model != "skip" else "") + "yes\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(transcript))
    assert command.run([]) == 0
    output = capsys.readouterr().out
    assert "to keep spoken lines whole and place captions" in output
    assert "486 MB" in output and "3.09 GB" in output and "0 MB" in output
    state = load_session(inputs["project"])
    assert state.answers["speech_model"] == model
    assert len(calls) == (0 if model == "skip" else 4)
    if model != "skip":
        assert "Verified SHA-256" in output and "SHA-256 verified" in output
        assert all("/resolve/" + "a" * 40 in u for u in calls)
    else:
        assert state.result["speech_setup"]["continuity"] == "unavailable"


@pytest.mark.parametrize("tail", ["q\n", "\nq\n", "\n\nb\nb\n3\nq\n", "\nb\n3\nq\n"])
def test_model_back_quit_and_enter_never_authorize_fetch(inputs, monkeypatch, tail):
    monkeypatch.setattr("sys.stdin", io.StringIO(interview(inputs) + tail))
    assert command.run([]) == 0
    state = load_session(inputs["project"])
    assert state.status == "paused"
    assert not state.answers.get("speech_download")


@pytest.mark.parametrize("flags", [[], ["--json"], ["--yes"], ["--json", "--yes"]])
def test_noninteractive_requires_model_then_explicit_consent(inputs, flags, capsys):
    answers, _ = complete("a", inputs)
    answers.pop("speech_model")
    file = Path(inputs["project"]).with_suffix(".json")
    file.write_text(json.dumps(answers))
    assert command.run(["--answers", str(file), *flags]) == 2
    assert "speech" in capsys.readouterr().out.lower()
    answers["speech_model"] = "small.en"
    file.write_text(json.dumps(answers))
    assert command.run(["--answers", str(file), *flags]) == 2
    assert "download" in capsys.readouterr().out.lower()


def test_resume_model_change_does_not_reuse_previous_download_consent(inputs, capsys):
    answers, _ = complete("a", inputs)
    answers.update(speech_model="small.en", speech_download=True)
    save_session(inputs["project"], Session(answers=answers, history=["speech_model", "speech_download"]))
    file = Path(inputs["project"]).with_suffix(".json")
    file.write_text(json.dumps({"speech_model": "large-v2"}))
    assert command.run(["--resume", inputs["project"], "--answers", str(file), "--json", "--yes"]) == 2
    event = json.loads(capsys.readouterr().out)
    assert event["question"]["id"] == "speech_download"
    assert "speech_download" not in load_session(inputs["project"]).answers


def test_fetch_hash_failure_never_publishes_and_cache_is_rechecked(zing_workspace, monkeypatch, pins):
    with pytest.raises(ValueError, match="explicit yes"):
        speech.fetch_model("small.en")
    monkeypatch.setattr(model_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"bad"))
    with pytest.raises(RuntimeError, match="SHA-256"):
        speech.fetch_model("small.en", consent=True)
    root = speech.cache_dir("small.en")
    assert not (root / "model.bin").exists() and not list(root.glob("*.part"))
    monkeypatch.setattr(model_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(pins))
    receipt = speech.fetch_model("small.en", consent=True)
    assert receipt["verified"] and receipt["downloaded_bytes"] == len(pins) * 4
    monkeypatch.setattr(model_fetch.urllib.request, "urlopen", lambda *a, **k: pytest.fail("cache downloaded"))
    assert speech.prepare({"speech_model": "small.en"})["downloaded_bytes"] == 0
    (root / "model.bin").write_bytes(b"x" * len(pins))
    assert speech.local_path("small.en") is None


@pytest.mark.parametrize("value", ["true", 1, None, [], {}])
def test_mcp_confirmation_requires_real_boolean(value):
    from myzing.mcp_server import h_zing_studio_run
    result = h_zing_studio_run(confirmed=value)
    assert result["ok"] is False and "real booleans" in result["error"]


@pytest.mark.parametrize("value", ["true", 1])
def test_mcp_sdk_does_not_coerce_confirmation(value):
    import asyncio
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError
    from myzing.mcp_server import build_server
    server = build_server()
    async def call():
        return await server.call_tool("zing_studio_run", {"confirmed": value})
    with pytest.raises(ToolError, match="valid boolean"):
        asyncio.run(call())


def test_cache_directory_name_alone_does_not_prove_model_cached(zing_workspace):
    (speech.hub_cache() / "models--Systran--faster-whisper-large-v2").mkdir(parents=True)
    assert speech.local_path("large-v2") is None


def test_inventory_offers_other_complete_cached_models(zing_workspace):
    snapshot = speech.hub_cache() / "models--Systran--faster-whisper-tiny.en/snapshots/fixture"
    snapshot.mkdir(parents=True)
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (snapshot / name).write_bytes(b"existing cache")
    assert any(r["model"] == "tiny.en" and r["cached"] and not r["verified"] for r in speech.inventory())
    assert "tiny.en" in speech.choices()
    assert speech.recommendation()[0] == "tiny.en"


def test_study_loads_verified_managed_model_offline(zing_workspace, monkeypatch, pins):
    import sys
    from types import SimpleNamespace
    from myzing.study import transcribe
    monkeypatch.setattr(model_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(pins))
    speech.fetch_model("small.en", consent=True)
    calls = []
    def model(path, **kwargs):
        calls.append((path, kwargs))
        return object()
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    transcribe._load_model("small.en", local_files_only=True)
    assert Path(calls[0][0]) == speech.cache_dir("small.en")
    assert calls[0][1]["local_files_only"] is True


@pytest.mark.parametrize("url", ["https://ryan:secret@example.org/a", "https://ryan@example.org/a", "https://:secret@example.org/a"])
def test_reference_credentials_message_redacts_credentials(url):
    with pytest.raises(ValueError, match="Credentials in URLs are refused for safety") as error:
        flow.normalize("reference", url)
    assert "secret" not in str(error.value) and "ryan" not in str(error.value)
    assert "download it yourself or remove the credentials" in str(error.value)


@pytest.mark.parametrize("action", ["status", "cancel", "resume"])
def test_orphan_updates_job_and_session_with_resume_hint(inputs, monkeypatch, action):
    root = Path(inputs["project"])
    save_session(root, Session(answers={"path": "a", "project": str(root)}, status="running"))
    write_json(root / "studio-job.json", {"status": "running", "pid": os.getpid() + 100000})
    monkeypatch.setattr("myzing.project.locking._pid_alive", lambda _: False)
    result = jobs.reconcile(root) if action == "resume" else jobs.job(project=root, cancel=action == "cancel")
    assert result["status"] == "interrupted" and "--resume" in result["hint"]
    assert load_session(root).status == "interrupted"
    assert "--resume" in load_session(root).result["hint"]


def test_studio_cancel_names_studio(inputs, monkeypatch):
    from myzing.match.process import Cancelled
    def cancel(*args, **kwargs):
        raise Cancelled("Match cancelled")
    monkeypatch.setattr(jobs, "run_owned", cancel)
    with pytest.raises(Cancelled, match="Studio run cancelled"):
        jobs.execute({"project": inputs["project"]})


@pytest.mark.skipif(os.name != "nt", reason="Windows status-reader sharing")
def test_status_write_waits_out_windows_reader(tmp_path, monkeypatch):
    from myzing.studio import models
    replace = models.os.replace
    calls = []
    def busy(source, target):
        calls.append(target)
        if len(calls) < 3:
            raise PermissionError(5, "status reader has the destination open")
        return replace(source, target)
    monkeypatch.setattr(models.os, "replace", busy)
    target = tmp_path / "studio-job.json"
    write_json(target, {"status": "ready"})
    assert json.loads(target.read_text())["status"] == "ready" and len(calls) == 3


def test_reference_worker_uses_supervisors_existing_lease(inputs, monkeypatch):
    from myzing.studio import worker, execute
    answers, _ = complete("a", inputs)
    monkeypatch.setattr(jobs, "busy_lock", lambda *a: pytest.fail("nested production lock"))
    monkeypatch.setattr("myzing.match.jobs.execute", lambda *a, **k: {"status": "shortage"})
    assert execute.run_confirmed(answers, locked=True)["status"] == "shortage"
    seen = []
    def run(a, **kwargs):
        seen.append(kwargs["locked"])
        return {"ok": True}
    monkeypatch.setattr(worker, "run_confirmed", run)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"answers": answers,
                        "result_path": str(Path(inputs["project"]) / "worker-result.json")})))
    assert worker.main() == 0 and seen == [True]


@pytest.mark.parametrize("surface", ["doctor", "setup"])
def test_doctor_setup_share_consent_and_verified_receipt(zing_workspace, monkeypatch, pins, capsys, surface):
    from myzing import doctor, setup_flow
    monkeypatch.setattr(doctor, "run_checks", lambda: [])
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))  # pipe is non-interactive
    run = doctor.run if surface == "doctor" else setup_flow.run
    assert run(["--speech-model", "small.en"]) == 2
    captured = capsys.readouterr()
    assert "explicit consent" in captured.out + captured.err
    monkeypatch.setattr(model_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(pins))
    assert run(["--speech-model", "small.en", "--yes"]) == 0
    assert speech.inventory()[0]["verified"]


def test_skip_never_loads_or_fakes_words(monkeypatch):
    from myzing.study import transcribe
    monkeypatch.setattr(transcribe, "_load_model", lambda *a, **k: pytest.fail("skip loaded a model"))
    result = transcribe.transcribe(Path("not-read.mp4"), model_name="skip")
    assert result.words == [] and result.provenance["continuity"] == "unavailable"
