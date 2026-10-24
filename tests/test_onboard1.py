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
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: pytest.fail("unconsented network"))


@pytest.fixture
def pins(monkeypatch):
    payload = b"model fixture"
    files = {name: {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
             for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")}
    monkeypatch.setattr(speech, "MODELS", {name: {"revision": "a" * 40, "files": files}
                                         for name in ("small.en", "large-v2")})
    return payload


def interview(inputs):
    return f"1\n{inputs['source']}\nall\n{inputs['clips']}\ngeneral\na local story\n\n12\nphone\n\n"


@pytest.mark.parametrize("choice,model", [("", "small.en"), ("1", "small.en"), ("2", "large-v2"), ("3", "skip")])
def test_model_stdin_choices_and_finish_receipt(inputs, monkeypatch, capsys, pins, choice, model):
    calls = []
    def download(url, **kwargs):
        calls.append(url)
        assert load_session(inputs["project"]).answers["speech_download"] is True
        return io.BytesIO(pins)
    monkeypatch.setattr(model_fetch, "open_url", download)
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
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(b"bad"))
    with pytest.raises(RuntimeError, match="SHA-256"):
        speech.fetch_model("small.en", consent=True)
    root = speech.cache_dir("small.en")
    assert not (root / "model.bin").exists() and not list(root.glob("*.part"))
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(pins))
    receipt = speech.fetch_model("small.en", consent=True)
    assert receipt["verified"] and receipt["downloaded_bytes"] == len(pins) * 4
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: pytest.fail("cache downloaded"))
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
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(pins))
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
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(pins))
    assert run(["--speech-model", "small.en", "--yes"]) == 0
    assert speech.inventory()[0]["verified"]


def test_skip_never_loads_or_fakes_words(monkeypatch):
    from myzing.study import transcribe
    monkeypatch.setattr(transcribe, "_load_model", lambda *a, **k: pytest.fail("skip loaded a model"))
    result = transcribe.transcribe(Path("not-read.mp4"), model_name="skip")
    assert result.words == [] and result.provenance["continuity"] == "unavailable"


# -- Review repairs (Claude review of 5e5b15e) ----------------------------------


def _local_server(handler):
    import http.server
    import threading
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_https_policy_refuses_downgrade_on_every_hop():
    import http.server
    import urllib.request
    hits = []

    class Target(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"plain http bytes")

    target = _local_server(Target)

    class Redirect(http.server.BaseHTTPRequestHandler):
        location = ""

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", Redirect.location)
            self.end_headers()

    redirect = _local_server(Redirect)
    try:
        with pytest.raises(ValueError, match="HTTPS only"):
            model_fetch.https_open(f"http://127.0.0.1:{target.server_address[1]}/model.bin")
        for location in (f"http://127.0.0.1:{target.server_address[1]}/model.bin", "ftp://127.0.0.1:1/model.bin"):
            Redirect.location = location
            with pytest.raises(RuntimeError, match="non-HTTPS") as error:
                model_fetch.opener().open(f"http://127.0.0.1:{redirect.server_address[1]}/hop", timeout=5)
            assert "127.0.0.1" not in str(error.value)  # signed CDN targets are never echoed
        assert hits == []  # refused before the downgraded hop was contacted
        handler = next(h for h in model_fetch.opener().handlers if isinstance(h, model_fetch._HTTPSOnlyRedirects))
        request = urllib.request.Request("https://huggingface.co/x")
        follow = handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "https://cdn.example/y")
        assert follow.full_url == "https://cdn.example/y"  # cross-host HTTPS is allowed; the hash decides
    finally:
        target.shutdown()
        redirect.shutdown()


def test_abandoned_part_from_a_killed_download_is_removed_next_time(zing_workspace, monkeypatch, pins):
    root = speech.cache_dir("small.en")
    root.mkdir(parents=True)
    stale = root / ".model.bin.k1ll3d.part"
    stale.write_bytes(b"x" * 1000)  # what a job-object kill or a closed terminal leaves behind
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(pins))
    assert speech.fetch_model("small.en", consent=True)["verified"]
    assert not stale.exists() and not list(root.glob("*.part"))


def test_concurrent_setup_downloads_each_file_once(zing_workspace, monkeypatch, pins):
    import threading
    import time
    calls, gate = [], threading.Event()

    def slow(url, *args, **kwargs):
        calls.append(url)
        gate.wait(5)  # hold the first download open while the second setup arrives
        return io.BytesIO(pins)

    monkeypatch.setattr(model_fetch, "open_url", slow)
    results, errors, waits = [], [], []

    def setup():
        try:
            results.append(speech.fetch_model("small.en", consent=True, progress=waits.append))
        except Exception as exc:  # noqa: BLE001 - the assertion reports it
            errors.append(exc)

    threads = [threading.Thread(target=setup) for _ in range(2)]
    for thread in threads:
        thread.start()
        time.sleep(.3)
    gate.set()
    for thread in threads:
        thread.join(10)
    assert errors == [] and len(results) == 2
    assert len(calls) == 4  # one download per pinned file, not two
    assert sum(r["downloaded_bytes"] for r in results) == len(pins) * 4  # each file fetched by one setup
    assert any("Waiting for another Zing download" in line for line in waits)


@pytest.mark.parametrize("name", ["../escape.bin", "sub/model.bin", "sub\\model.bin", "..", "C:model.bin",
                                  "model.bin:stream", ""])
def test_pin_file_names_must_stay_inside_the_cache(zing_workspace, monkeypatch, pins, name):
    spec = speech.MODELS["small.en"]
    monkeypatch.setitem(speech.MODELS, "small.en", {**spec, "files": {name: spec["files"]["model.bin"]}})
    with pytest.raises(ValueError, match="unsafe file names"):
        speech.fetch_model("small.en", consent=True)
    with pytest.raises(ValueError, match="unsafe file names"):
        speech.managed_path("small.en")
    monkeypatch.setitem(speech.MODELS, "small.en", {**spec, "revision": "../" + "a" * 37})
    with pytest.raises(ValueError, match="invalid name or revision"):
        speech.cache_dir("small.en")


def test_setup_checks_room_on_the_zing_drive_before_downloading(zing_workspace, monkeypatch, pins):
    from collections import namedtuple
    seen = []
    usage = namedtuple("usage", "total used free")

    def disk(path):
        seen.append(Path(path))
        return usage(10**9, 10**9, len(pins))  # less than the four pinned files

    monkeypatch.setattr(speech.shutil, "disk_usage", disk)
    with pytest.raises(RuntimeError, match="needs .* GB free") as error:
        speech.fetch_model("small.en", consent=True)
    assert "move ZING_HOME" in str(error.value)
    target = speech.cache_dir("small.en")
    assert seen and all(p == target or p in target.parents for p in seen)


def test_full_disk_mid_stream_names_the_folder_and_cleans_up(zing_workspace, monkeypatch, pins):
    import errno
    real = model_fetch.tempfile.NamedTemporaryFile

    def full(**kwargs):
        stream = real(**kwargs)

        def write(data):
            raise OSError(errno.ENOSPC, "No space left on device")
        stream.write = write
        return stream

    monkeypatch.setattr(model_fetch.tempfile, "NamedTemporaryFile", full)
    monkeypatch.setattr(model_fetch, "open_url", lambda *a, **k: io.BytesIO(pins))
    with pytest.raises(OSError, match="Could not save model.bin") as error:
        speech.fetch_model("small.en", consent=True)
    assert error.value.errno == errno.ENOSPC and "move ZING_HOME" in str(error.value)
    assert not list(speech.cache_dir("small.en").glob("*.part"))


@pytest.mark.parametrize("repo,name", [("models--guillaumekln--faster-whisper-large-v2", "large-v2"),
                                       ("models--deepdml--faster-whisper-large-v3-turbo-ct2", "large-v3-turbo-ct2")])
def test_study_loads_the_snapshot_inventory_reported(zing_workspace, monkeypatch, repo, name):
    import sys
    from types import SimpleNamespace
    from myzing.study import transcribe
    snapshot = speech.hub_cache() / repo / "snapshots" / ("c" * 40)
    snapshot.mkdir(parents=True)
    for file in ("model.bin", "config.json", "tokenizer.json"):
        (snapshot / file).write_bytes(b"user-provisioned")
    assert name in speech.choices()  # inventory offers it as cached
    calls = []
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=lambda path, **kw: calls.append((path, kw)) or object()))
    transcribe._load_model(name)
    assert Path(calls[0][0]) == snapshot and calls[0][1]["local_files_only"] is True
    assert sorted(p.name for p in snapshot.iterdir()) == ["config.json", "model.bin", "tokenizer.json"]


def test_plain_study_never_downloads_an_uncached_model(zing_workspace, monkeypatch):
    import sys
    from types import SimpleNamespace
    from myzing.study import transcribe
    resolved = []

    def download_model(name, local_files_only=False):
        resolved.append(local_files_only)
        raise FileNotFoundError("not in the local hub cache")

    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=lambda *a, **k: pytest.fail("constructed without weights")))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=download_model))
    result = transcribe.transcribe(Path("clip.mp4"))  # ordinary zing study: no local_files_only flag
    assert resolved == [True] and result.words == []
    assert any("never downloads" in w and "--speech-model" in w for w in result.warnings)


def test_supplied_model_for_silent_clips_needs_consent_before_the_plan(inputs, monkeypatch):
    from types import SimpleNamespace
    probe = {"duration": 18.0, "width": 640, "height": 360, "orientation": "landscape",
             "has_audio": False, "flags": [], "streams": [{"codec_type": "video"}], "notes": []}
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: SimpleNamespace(to_dict=lambda: probe))
    answers, _ = complete("b", inputs)
    answers["speech_model"] = "small.en"
    step = flow.next_step(answers)
    assert step["status"] == "question" and step["question"]["id"] == "speech_download"
    assert flow.next_step({**answers, "speech_download": False})["status"] == "blocked"
    plan = flow.next_step({**answers, "speech_download": True})["plan"]
    assert "Speech model: small.en" in plan["downloads"]


def test_back_after_a_declined_download_returns_to_the_model_choice(inputs, monkeypatch):
    # Enter picks small.en, Enter declines its download, b, then 3 = skip, q.
    monkeypatch.setattr("sys.stdin", io.StringIO(interview(inputs) + "\n\nb\n3\nq\n"))
    assert command.run([]) == 0
    state = load_session(inputs["project"])
    assert state.answers["speech_model"] == "skip" and "speech_download" not in state.answers


def test_supervised_cancel_removes_the_killed_downloads_part(inputs, monkeypatch, pins):
    from myzing.match.process import Cancelled
    root = speech.cache_dir("small.en")
    root.mkdir(parents=True)
    part = root / ".model.bin.k1ll3d.part"

    def killed(*args, **kwargs):
        (root / model_fetch.LOCK_NAME).touch()
        part.write_bytes(b"partial")  # the worker died mid-stream; its finally never ran
        raise Cancelled("Match cancelled")

    monkeypatch.setattr(jobs, "run_owned", killed)
    with pytest.raises(Cancelled, match="Studio run cancelled"):
        jobs.execute({"project": inputs["project"], "speech_model": "small.en"})
    assert not part.exists()


def test_discard_leaves_a_live_download_alone(tmp_path):
    part = tmp_path / ".model.bin.live.part"
    part.write_bytes(b"x")
    with model_fetch.download_lock(tmp_path):
        model_fetch.discard_abandoned(tmp_path)  # another handle: the folder is busy
        assert part.exists()
    model_fetch.discard_abandoned(tmp_path)
    assert not part.exists()


@pytest.mark.parametrize("surface", ["doctor", "setup"])
def test_doctor_and_setup_accept_the_equals_form(zing_workspace, monkeypatch, capsys, surface):
    from myzing import doctor, setup_flow
    monkeypatch.setattr(doctor, "run_checks", lambda: [])
    run = doctor.run if surface == "doctor" else setup_flow.run
    assert run(["--speech-model=skip"]) == 0
    assert "Speech skipped" in capsys.readouterr().out
