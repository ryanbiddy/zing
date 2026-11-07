"""Regressions for the study and local-media review."""

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("timeline", [None, "timeline.png"])
def test_match_markdown_allows_missing_inspection(timeline):
    from myzing.match.evidence import markdown

    row = {"status": "ready", "video": "a.mp4", "plan": "a.json",
           "report": "a.match.json", "timeline": timeline}
    text = markdown({"project": ".", "summary": "1 ready", "drafts": {"A": row}})
    assert "[video](<a.mp4>)" in text and "[match report](<a.match.json>)" in text
    assert ("[timeline]" in text) == bool(timeline)


@pytest.mark.parametrize("folder", [".", "director"])
@pytest.mark.parametrize("replacement_pid", [1234, 5678])
def test_match_cleanup_preserves_replaced_project_lock(tmp_path, monkeypatch, folder, replacement_pid):
    from myzing.match import jobs
    from myzing.match.state import write, read

    lock = tmp_path / folder / ".project.lock"
    lock.parent.mkdir(exist_ok=True)
    write(lock, {"pid": 1234, "token": "worker"})
    replacement = {"pid": replacement_pid, "token": "new-owner"}
    rename, unlink = Path.rename, Path.unlink

    def swap():
        unlink(lock)
        write(lock, replacement)

    def racing_rename(path, target):
        if path == lock:
            swap()
        return rename(path, target)

    def racing_unlink(path, *args, **kwargs):
        if path == lock:
            swap()
        return unlink(path, *args, **kwargs)

    def worker(command, payload, **kwargs):
        kwargs["on_started"](1234)
        write(tmp_path / "comparison.json", {"run_id": json.loads(payload)["run_id"], "status": "ready"})
        write(tmp_path / "match-state.json", {"status": "ready"})
        return 0

    monkeypatch.setattr(jobs, "run_owned", worker)
    monkeypatch.setattr(Path, "rename", racing_rename)
    monkeypatch.setattr(Path, "unlink", racing_unlink)
    assert jobs.execute({"out": str(tmp_path)}, locked=True)["status"] == "ready"
    assert read(lock) == replacement


@pytest.mark.parametrize("failure", ["wrong_frame", "seek_failed"])
def test_long_caption_samples_skip_unreliable_seeks(monkeypatch, failure):
    from myzing.study import caption_geometry as cg

    class Capture:
        index = 0
        released = False

        def isOpened(self):
            return True

        def get(self, prop):
            return 30 if prop == 1 else (91 if self.index == 300 else self.index + 1)

        def set(self, prop, index):
            self.index = index
            return failure != "seek_failed" or index != 300

        def read(self):
            return True, SimpleNamespace(shape=(48, 64, 3))

        def release(self):
            self.released = True

    cap = Capture()
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(
        VideoCapture=lambda path: cap, CAP_PROP_FPS=1, CAP_PROP_POS_FRAMES=2))
    schedule = [(0, 10), (10, 10), (20, 10)]
    monkeypatch.setattr(cg, "sample_schedule", lambda duration: schedule)
    frames = list(cg.iter_frames(Path("interview.mp4"), 600))
    assert [f[0] for f in frames] == [0, 20]
    result = cg.CaptionGeometry(600, frames=[cg.FrameSample(t, target, step, index, 64, 48)
                                           for t, target, step, index, _ in frames])
    assert cg._coverage(result, schedule)["gaps"] == [{"t": 10, "reason": "frame_unavailable"}]
    assert cap.released


def test_study_timeout_stops_descendants_and_raises_media_error(tmp_path):
    from myzing.study import proc
    from myzing.project.locking import _pid_alive

    marker, pid_file = tmp_path / "late-write", tmp_path / "child.pid"
    child = f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).touch()"
    parent = (f"import subprocess, sys, time; from pathlib import Path; "
              f"p = subprocess.Popen([sys.executable, '-c', {child!r}]); "
              f"Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(10)")
    try:
        with pytest.raises(Exception) as caught:
            proc.run([sys.executable, "-c", parent], timeout=.5)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 2
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(.02)
        assert isinstance(caught.value, proc.MediaError)
        assert "timed out" in str(caught.value)
        assert not marker.exists()
        assert not _pid_alive(pid)
    finally:
        if pid_file.exists() and _pid_alive(int(pid_file.read_text())):
            import signal
            os.kill(int(pid_file.read_text()), signal.SIGTERM)


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel32 branch")
def test_windows_tool_cannot_start_before_job_attachment(tmp_path, monkeypatch):
    from myzing.match.process import WindowsJob
    from myzing.study import proc

    marker = tmp_path / "started"
    attach = WindowsJob.attach

    def delayed(job, process):
        time.sleep(.3)
        assert not marker.exists(), "tool ran before its descendants were owned"
        attach(job, process)

    monkeypatch.setattr(WindowsJob, "attach", delayed)
    result = proc.run([sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"], timeout=3)
    assert result.returncode == 0 and marker.exists()


def test_default_caption_reader_never_constructs_downloading_ocr(monkeypatch):
    from myzing.study import caption_models, captions

    calls = []
    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(RapidOCR=lambda **kw: calls.append(kw)))

    def missing():
        raise RuntimeError("caption OCR model missing or corrupt: local.onnx")

    monkeypatch.setattr(caption_models, "model_paths", missing)
    result = captions.read_captions(Path("clip.mp4"), 1)
    assert calls == []
    assert not result.captions
    assert any("model missing or corrupt" in w for w in result.warnings)


def test_normalize_keeps_staged_source_until_replace_succeeds(tmp_path, monkeypatch):
    from myzing.study import ingest

    media = tmp_path / "media.webm"
    media.write_bytes(b"original")

    def run(command, **kwargs):
        Path(command[-1]).write_bytes(b"normalized")
        return SimpleNamespace(returncode=0)

    replace = Path.replace

    def fail(path, target):
        if path.name == "media_normalizing.mp4":
            raise PermissionError("publication interrupted")
        return replace(path, target)

    monkeypatch.setattr(ingest.proc, "run", run)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(PermissionError, match="publication interrupted"):
        ingest._normalize(media, 30)
    assert media.read_bytes() == b"original"
    monkeypatch.setattr(Path, "replace", replace)
    assert ingest._normalize(media, 30).read_bytes() == b"normalized"
    assert not media.exists()


def assert_safe_input(command, path):
    from myzing.project.probe import MEDIA_DEMUXERS

    prefix = command[:command.index(str(path))]
    assert prefix[prefix.index("-protocol_whitelist") + 1] in ("file", "file,pipe")
    assert prefix[prefix.index("-format_whitelist") + 1] == MEDIA_DEMUXERS
    assert prefix[prefix.index("-enable_drefs") + 1] == "0"
    assert prefix[prefix.index("-use_absolute_path") + 1] == "0"


def test_heif_probe_and_decode_restrict_input_formats(tmp_path, monkeypatch):
    from myzing.memes import photo

    Image = pytest.importorskip("PIL.Image")
    ppm = io.BytesIO()
    Image.new("RGB", (2, 2)).save(ppm, format="PPM")
    media = tmp_path / "shot.heic"
    media.write_text("ffconcat version 1.0\nfile 'private.txt'\n")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        data = json.dumps({"streams": [{"codec_type": "video", "width": 2, "height": 2}]})
        return SimpleNamespace(returncode=0, stdout=data if command[0] == "ffprobe" else ppm.getvalue())

    monkeypatch.setattr(photo.shutil, "which", lambda name: name)
    monkeypatch.setattr(photo.subprocess, "run", run)
    image, _ = photo.load_photo(media)
    image.close()
    assert len(commands) == 2
    for command in commands:
        assert_safe_input(command, media)


@pytest.mark.parametrize("operation", ["explain", "matte", "inspect_probe", "inspect_frame", "inspect_audio"])
def test_explain_and_inspect_restrict_input_formats(tmp_path, monkeypatch, operation):
    from myzing.explain import api, matte
    from myzing.inspect.media import Decoder

    media, commands = tmp_path / "talk.mp4", []
    data = {"streams": [{"codec_type": "video", "width": 2, "height": 2, "avg_frame_rate": "30/1"}],
            "format": {"duration": "1"}}

    def run(command, **kwargs):
        commands.append(command)
        payload = json.dumps(data) if command[0] == "ffprobe" else ""
        return SimpleNamespace(returncode=0, stdout=payload if kwargs.get("text") else payload.encode(), stderr=b"")

    monkeypatch.setattr(api.storage, "resolve_workspace", lambda: tmp_path)
    monkeypatch.setattr(subprocess, "run", run)
    if operation == "explain":
        from myzing.study import proc
        monkeypatch.setattr(proc, "run", lambda command, **kw: run(command, text=True))
        api.probe_video(media)
    elif operation == "matte":
        matte._frame(media, 0, 2, 2)
    elif operation == "inspect_probe":
        Decoder().probe(media)
    elif operation == "inspect_frame":
        commands.append(Decoder.input_args(media, 0))
    else:
        from myzing.inspect import InspectionError
        with pytest.raises(InspectionError, match="no audio"):
            Decoder().envelope(media, 0, 1, 2)
    assert_safe_input(commands[0], media)


def test_pack_uses_requested_workspace_and_persists_provenance(tmp_path, zing_workspace):
    from myzing import storage
    from myzing.profile.packs import build_pack
    from tests.test_profile_api import make_source
    from tests.test_profile_packs import write_manifest, ref

    target = tmp_path / "requested"
    url = "https://youtube.com/shorts/local-pack"
    with storage.use_workspace(target):
        make_source(storage.slug_for(url), 30, [5], 10)
    manifest = write_manifest(tmp_path / "pack.json", references=[ref(1, url)])
    result = build_pack(manifest, workspace=target, study_missing=False)
    assert result.reused == ["AITTH-01"]
    assert storage.resolve_workspace() == zing_workspace.resolve()
    assert not (zing_workspace / "profiles").exists()
    with storage.use_workspace(target):
        assert storage.load_profile(result.profile.name).provenance == result.profile.provenance


def test_draft_rounding_produces_inspectable_timeline(tmp_path):
    from myzing.assemble.draft import draft_edl
    from myzing.inspect.timing import build_time_map
    from tests.test_assemble_draft import make_breakdown

    media = tmp_path / "clip.mp4"
    media.touch()
    result = draft_edl(make_breakdown(), {"keepers": [{"start": .0004, "end": .2006},
                                                     {"start": 1, "end": 2}]}, media)
    spans = build_time_map(result.edl, tmp_path)
    assert spans[0].output_end == spans[1].output_start == .201


@pytest.mark.parametrize("bad", ["empty", "oversized", "corrupt", "animated"])
def test_photo_inventory_keeps_good_photos(tmp_path, monkeypatch, bad):
    from myzing.still import inventory as inv

    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (16, 16), "blue").save(tmp_path / "good.png")
    path = tmp_path / "bad.jpg"
    path.write_bytes(b"" if bad == "empty" else b"broken jpeg")
    if bad == "animated":
        path.unlink()
        path = tmp_path / "bad.png"
        frames = [Image.new("RGB", (16, 16), color) for color in ("red", "green")]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=100)
    if bad == "oversized":
        monkeypatch.setattr(inv, "MAX_BYTES", 100)
        path.write_bytes(b"x" * 101)
    monkeypatch.setattr(inv, "YuNetDetector", lambda **kw: None)
    monkeypatch.setattr(inv, "photo_detections", lambda image: ([], []))
    monkeypatch.setattr(inv, "read_text", lambda image: None)
    photos, notes = inv.inventory(tmp_path)
    assert [Path(p.path).name for p in photos] == ["good.png"]
    assert any(path.name in note for note in notes)


def test_four_by_five_brief_recommends_portrait(tmp_path, monkeypatch):
    from myzing.brief.models import Brief
    from myzing.brief import recommend as module

    assets = [SimpleNamespace(id=name, path=name, state="ready", probe=SimpleNamespace(
        streams=[{"codec_type": "video"}], orientation=orientation, duration=30, has_audio=True))
        for name, orientation in [("portrait.mp4", "portrait"), ("wide.mp4", "landscape")]]
    monkeypatch.setattr(module, "load_project", lambda root: SimpleNamespace(
        assets=assets, reference=SimpleNamespace(study=None)))
    monkeypatch.setattr(module, "project_status", lambda root: {"assets": [
        {"id": a.id, "path": a.path, "state": "ready", "needs_scan": False} for a in assets]})
    result = module.recommend(tmp_path, Brief.from_answers({"aspect": "4:5"}))
    warnings = str(result)
    assert "Framing review needed for 4:5: wide.mp4." in warnings
    assert "Framing review needed for 4:5: portrait.mp4" not in warnings


def test_explain_keeps_published_card_when_marker_is_locked(tmp_path, monkeypatch):
    from myzing.explain import api, presentation
    from tests.test_explain import full_card

    media = tmp_path / "clips" / "source.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    out = tmp_path / "card"
    monkeypatch.setattr(api, "probe_video", lambda path: {})
    monkeypatch.setattr(api, "_measure", lambda *a, **kw: (full_card(), media))

    def png(card, source, target):
        target.write_bytes(b"preview")
        return {}

    monkeypatch.setattr(presentation, "render_png", png)
    unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path.name == api.PARTIAL_MARKER:
            raise PermissionError("marker is locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    result = api.explain_video(media, out)
    assert result["ok"]
    assert all((out / name).is_file() for name in ("card.json", "card.md", "card.png"))


def stub_stills(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from myzing.still import api
    from myzing.still.models import Photo
    from myzing.project.api import hash_file

    source = tmp_path / "photo.png"
    source.write_bytes(b"photo")
    photo = Photo("photo-local", str(source), hash_file(source), 640, 480, 5,
                  "Landscape photo.", ["#333333"], "landscape", 0, 0, [], "supplied")
    monkeypatch.setattr(api, "inventory", lambda path: ([photo], []))
    monkeypatch.setattr(api, "_offline", lambda *args: [(photo, {"texts": ["one fix"], "provider": "offline"})])
    monkeypatch.setattr(api, "safe_geometry", lambda *a, **kw: True)
    monkeypatch.setattr(api, "open_photo", lambda path: nullcontext(SimpleNamespace(
        size=(640, 480), save=lambda target: Path(target).write_bytes(b"photo"))))
    rendered = []

    def render(concept, photo, aspect, target, protect):
        rendered.append(target)
        target.write_bytes(f"render-{os.getpid()}-{len(rendered)}".encode())
        return {"width": 640, "height": 480, "warnings": [], "viral_lens": {"score": 1}}

    def sheet(stage, *args):
        (stage / "contact-sheet.png").write_bytes(b"sheet")
        return {"path": "contact-sheet.png"}

    def video(texts, *, out, gif, **kwargs):
        path = Path(out)
        path.write_bytes(b"video-" + str(len(rendered)).encode())
        path.with_suffix(".gif").write_bytes(b"gif-" + str(len(rendered)).encode())
        return {"path": str(path), "width": 640, "height": 480,
                "gif": {"path": str(path.with_suffix('.gif')), "width": 640, "height": 480}}

    monkeypatch.setattr(api, "_render", render)
    monkeypatch.setattr(api, "_sheet", sheet)
    monkeypatch.setattr("myzing.memes.video.render_meme_video", video)
    return api


@pytest.mark.parametrize("picked", [None, False, True])
def test_still_publication_rolls_back_when_index_replace_fails(tmp_path, monkeypatch, picked):
    api = stub_stills(tmp_path, monkeypatch)
    root = tmp_path / "stills"
    if picked is not None:
        concept = api.create_stills(tmp_path, "bugs", root, n=1)["summary"][0]["id"]
        if picked:
            api.pick_still(root, concept, video=True, gif=True)
    before = {p.name: p.read_bytes() for p in root.iterdir()} if root.exists() else {}
    replace = Path.replace

    def fail(path, target):
        if Path(target) == root / "index.json":
            raise PermissionError("index is locked")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(PermissionError, match="index is locked"):
        if picked is None:
            api.create_stills(tmp_path, "bugs", root, n=1)
        else:
            api.pick_still(root, concept, video=True, gif=True)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    monkeypatch.setattr(Path, "replace", replace)
    if picked is None:
        assert api.create_stills(tmp_path, "bugs", root, n=1)["count"] == 1
    else:
        assert api.pick_still(root, concept, video=True, gif=True)["id"] == concept


@pytest.mark.parametrize("picked", [False, True])
def test_still_publication_recovers_after_process_exit(tmp_path, monkeypatch, picked):
    api = stub_stills(tmp_path, monkeypatch)
    root = tmp_path / "stills"
    if picked:
        concept = api.create_stills(tmp_path, "bugs", root, n=1)["summary"][0]["id"]
        api.pick_still(root, concept)
    script = f"""
import os
from pathlib import Path
import pytest
from tests.test_study_review_round5 import stub_stills
root = Path({str(root)!r})
api = stub_stills(root.parent, pytest.MonkeyPatch())
replace = Path.replace
def crash(path, target):
    if Path(target) == root / 'index.json':
        os._exit(71)
    return replace(path, target)
Path.replace = crash
{"api.pick_still(root, " + repr(concept) + ")" if picked else "api.create_stills(root.parent, 'bugs', root, n=1)"}
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=15)
    assert result.returncode == 71, result.stderr.decode(errors="replace")
    if picked:
        result = api.pick_still(root, concept)
        from myzing.project.api import hash_file
        index = json.loads((root / "index.json").read_text())
        assert index["concepts"][0]["outputs"][0]["sha256"] == hash_file(Path(result["path"]))
    else:
        assert api.create_stills(tmp_path, "bugs", root, n=1)["count"] == 1


@pytest.mark.parametrize("operation", ["activity", "regions"])
def test_screen_sampling_times_out_and_reaps_decoder(monkeypatch, operation):
    import threading
    from myzing.screen import analysis, regions
    from myzing.screen.models import Zoom

    killed = threading.Event()

    class Pipe:
        closed = False

        def read(self, size):
            assert killed.wait(.3), "screen read blocked without a deadline"
            return b""

        def close(self):
            self.closed = True

    class Process:
        stdout = Pipe()
        waited = False

        def kill(self):
            killed.set()

        def poll(self):
            return -9 if killed.is_set() else None

        def wait(self, **kwargs):
            self.waited = True
            return self.poll()

    process = Process()
    timer = threading.Timer
    timeouts = []

    def short_timer(seconds, callback):
        timeouts.append(seconds)
        return timer(.01, callback)

    monkeypatch.setattr(threading, "Timer", short_timer)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(RuntimeError, match="timed out"):
        if operation == "activity":
            analysis.activity(Path("stalled.mp4"), 30)
        else:
            regions.attach_regions(Path("stalled.mp4"), [Zoom(0, 2, .5, .5, [{"t": 1}], .5)], 30)
    assert timeouts == [120]
    assert killed.is_set() and process.waited and process.stdout.closed


@pytest.mark.parametrize("failure", ["plan", "render", "study"])
def test_screen_folder_continues_after_one_recording_fails(tmp_path, monkeypatch, failure):
    from myzing.screen import api, render
    from myzing.studio import evidence

    files = [tmp_path / f"{i}.mp4" for i in range(3)]
    planned, rendered = [], []
    monkeypatch.setattr(evidence, "media_files", lambda *args: files)

    def plan(path, **kwargs):
        planned.append(path)
        if failure == "plan" and path == files[1]:
            raise RuntimeError("broken recording")
        return SimpleNamespace(source=str(path), words=[], warnings=[], caption_preset="none")

    def deliver(plan, output, **kwargs):
        if failure == "render" and plan.source == str(files[1]):
            raise subprocess.TimeoutExpired("ffmpeg", 120)
        rendered.append(plan.source)
        return {"video": str(output)}

    def study(source, **kwargs):
        if source == str(files[1]):
            raise RuntimeError("broken recording")
        return SimpleNamespace(words=[])

    monkeypatch.setattr(api, "plan_screen", plan)
    monkeypatch.setattr(api, "save_plan", lambda plan, path: path)
    monkeypatch.setattr(render, "render_screen", deliver)
    monkeypatch.setattr("myzing.study.api.study", study)
    result = api.run_folder(tmp_path, tmp_path / "out", progress=lambda message: None,
                            speech_model="local" if failure == "study" else None)
    assert result["status"] == "partial"
    assert len(result["screens"]) == 2
    assert rendered == [str(files[0]), str(files[2])]
    assert result["failures"][0]["source"] == str(files[1])
    assert result["failures"][0]["error"]


@pytest.mark.parametrize("status", ["ready", "partial", "failed"])
def test_screen_cli_reports_folder_failures(tmp_path, monkeypatch, capsys, status):
    from myzing.screen import command

    monkeypatch.setattr(command, "run_folder", lambda *a, **kw: {"status": status})
    result = command.match(["--clips", str(tmp_path), "--out", str(tmp_path / "out")])
    assert result == (0 if status == "ready" else 1)
    assert json.loads(capsys.readouterr().out)["status"] == status


@pytest.mark.parametrize("failure", ["exit", "timeout", "captions"])
@pytest.mark.parametrize("explicit_work", [False, True])
def test_screen_render_cleans_only_owned_work_on_failure(tmp_path, monkeypatch, failure, explicit_work):
    from myzing.screen import render
    from myzing.screen.models import ScreenPlan
    from myzing.project.api import hash_file
    from myzing.render import pipeline, framing

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    plan = ScreenPlan(str(media), hash_file(media), 640, 360, 1, caption_preset="none")
    monkeypatch.setattr(pipeline, "probe_media", lambda *a: SimpleNamespace(duration=1, has_audio=False))
    monkeypatch.setattr(framing, "probe_dimensions", lambda *a: (640, 360))
    monkeypatch.setattr(pipeline, "filter_script_args", lambda ffmpeg, script: ["-filter_complex_script", str(script)])

    def fail(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("ffmpeg", 120)
        if failure == "captions":
            raise ValueError("caption failure")
        return SimpleNamespace(returncode=1, stderr=b"render failure")

    monkeypatch.setattr(subprocess, "run", fail)
    if failure == "captions":
        monkeypatch.setattr(render, "_captions", fail)
    work = tmp_path / "chosen-work" if explicit_work else None
    if work:
        work.mkdir()
        (work / "keep.txt").write_text("keep")
    with pytest.raises((RuntimeError, ValueError, subprocess.TimeoutExpired)):
        render.render_screen(plan, tmp_path / "out.mp4", work_dir=work)
    assert not list(tmp_path.glob("screen-work-*"))
    if work:
        assert (work / "keep.txt").read_text() == "keep"
