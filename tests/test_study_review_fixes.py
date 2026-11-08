"""Reference study regressions with fake tools and no downloads."""
import hashlib
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import storage
from myzing.match import process as owned
from myzing.study import api, audio, captions, ingest, proc, report, source_map
from tests.test_study_api import wire_stages
from tests.test_study_ingest import FakeTools, use
from tests.test_study_report import sample


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(proc, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.mark.parametrize("handoff", [False, True])
def test_kept_media_replaces_same_size_content(tmp_path, monkeypatch, handoff):
    fake = FakeTools()
    use(monkeypatch, fake)
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"new-bytes")
    url = "https://www.tiktok.com/@cleo/video/777"
    target = storage.media_target(storage.slug_for(url), ".mp4")
    target.write_bytes(b"old-bytes")
    sha = hashlib.sha256(kept.read_bytes()).hexdigest()
    contract = {"source_ref": "uoink://item/777", "sha256": sha, "byte_length": kept.stat().st_size}

    result = ingest.ingest(url, kept_media=kept, handoff=contract if handoff else None)

    assert result.media_path == target
    assert result.media_path.read_bytes() == kept.read_bytes()
    assert fake.commands("yt-dlp") == []
    recorded = result.provenance["source_handoff"]["sha256"] if handoff else result.provenance["kept_media_sha256"]
    assert recorded == hashlib.sha256(result.media_path.read_bytes()).hexdigest()


@pytest.mark.parametrize("kept", [False, True])
def test_staging_reuses_identical_content(tmp_path, monkeypatch, kept):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"same-bytes")
    target = storage.media_target("reference", ".mp4")
    target.write_bytes(source.read_bytes())
    monkeypatch.setattr(ingest.shutil, "copy2", lambda *args: pytest.fail("identical media was copied"))

    result = ingest._stage_kept(source, "reference", [], {})[0] if kept else ingest._stage_local(str(source), "reference")

    assert result == target and target.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("kept", [False, True])
@pytest.mark.parametrize("previous", [None, b"old-bytes"])
@pytest.mark.parametrize("failure", ["copy", "replace"])
def test_staging_failure_never_publishes_partial_media(tmp_path, monkeypatch, kept, previous, failure):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"new-bytes")
    target = storage.media_target("reference", ".mp4")
    if previous is not None:
        target.write_bytes(previous)
    copied = []

    def copy(src, dest):
        copied.append(Path(dest))
        Path(dest).write_bytes(b"partial" if failure == "copy" else src.read_bytes())
        if failure == "copy":
            raise OSError("copy interrupted")

    def replace(src, dest):
        raise OSError("replace interrupted")

    monkeypatch.setattr(ingest.shutil, "copy2", copy)
    if failure == "replace":
        monkeypatch.setattr(os, "replace", replace)
    if kept:
        warnings, provenance = [], {}
        assert ingest._stage_kept(source, "reference", warnings, provenance) == (None, "missing")
        assert warnings and not provenance
    else:
        with pytest.raises(OSError, match="interrupted"):
            ingest._stage_local(str(source), "reference")

    assert len(copied) == 1 and copied[0] != target and copied[0].parent == target.parent
    assert (target.read_bytes() if target.exists() else None) == previous
    assert list(target.parent.iterdir()) == ([target] if previous is not None else [])
    assert storage.find_media("reference") == (target if previous is not None else None)


@pytest.mark.parametrize("platform", ["nt", "posix"])
@pytest.mark.parametrize("ending", ["timeout", "callback", "error", "success"])
def test_download_progress_owns_process_tree(monkeypatch, platform, ending):
    ended, tree_stopped = threading.Event(), threading.Event()
    events, options = [], []

    class Pipe:
        closed = False

        def __iter__(self):
            if ending == "timeout":
                assert ended.wait(2), "download read blocked after its deadline"
                return iter(())
            return iter(["[zing-progress] 42.5%\n", "last output\n"])

        def close(self):
            self.closed = True

    class Process:
        pid = 1234
        stdout, stderr = Pipe(), None
        returncode = None
        waited = False

        def kill(self):
            self.returncode = -9
            ended.set()

        def poll(self):
            return self.returncode

        def wait(self):
            self.waited = True
            if self.returncode is None:
                self.returncode = 3 if ending == "error" else 0
            return self.returncode

    process = Process()

    class Job:
        def attach(self, child):
            assert child is process
            events.append("attach")

        def close(self):
            tree_stopped.set()

    def stop_tree(pid):
        assert pid == process.pid
        tree_stopped.set()

    def start(cmd, **kwargs):
        events.append("start")
        options.append(kwargs)
        return process

    def progress(percent):
        assert percent == 42.5
        if ending == "callback":
            raise RuntimeError("callback failed")

    monkeypatch.setattr(proc, "os", SimpleNamespace(name=platform))
    monkeypatch.setattr(owned, "WindowsJob", Job)
    monkeypatch.setattr(owned, "_stop_posix_tree", stop_tree)
    monkeypatch.setattr(proc, "_resume", lambda child: events.append("resume"))
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(subprocess, "Popen", start)
    if ending == "timeout":
        with pytest.raises(proc.Timeout) as caught:
            ingest._download_progress(["fake-downloader"], .02, progress)
        assert caught.value.timeout == .02
    elif ending == "callback":
        with pytest.raises(RuntimeError, match="callback failed"):
            ingest._download_progress(["fake-downloader"], 2, progress)
    else:
        result = ingest._download_progress(["fake-downloader"], 2, progress)
        assert result.returncode == (3 if ending == "error" else 0)
        assert result.stderr == "last output"

    # A POSIX tool that already exited is not walked; Windows always closes its job.
    assert tree_stopped.is_set() == (platform == "nt" or ending in ("timeout", "callback"))
    assert process.waited and process.stdout.closed
    if platform == "nt":
        assert events == ["start", "attach", "resume"]
        assert options[0]["creationflags"] == 0x08000204
    else:
        assert events == ["start"]
        assert options[0]["start_new_session"] is True


def test_scattered_speech_leaves_music_inconclusive():
    warnings = []
    assert audio._music_heuristic([-20.0] * 4, [(.2, .6)], .1, warnings) == (False, 0.0)
    assert len(warnings) == 1 and "inconclusive" in warnings[0]


@pytest.mark.parametrize("fps", [2, 3, 30])
def test_caption_frame_times_follow_source(monkeypatch, fps):
    class Capture:
        index = 0
        released = False

        def isOpened(self):
            return True

        def get(self, prop):
            return fps

        def read(self):
            frame = self.index
            self.index += 1
            return frame < fps * 10, frame

        def release(self):
            self.released = True

    capture = Capture()
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(VideoCapture=lambda path: capture, CAP_PROP_FPS=1))
    frames = list(captions._iter_frames(Path("reference.mp4"), 10))
    schedule = captions.sample_schedule(10)

    assert capture.released
    assert len({frame for _, _, frame in frames}) == len(frames)
    for t, step, frame in frames:
        assert t <= frame / fps + 1e-9 < t + step + 1e-9
        assert (t, step) == max(slot for slot in schedule if slot[0] <= frame / fps + 1e-9)
    if fps == 30:
        assert [(t, step) for t, step, _ in frames] == schedule
    else:
        assert len(frames) == fps * 10
        assert frames[-1][0] >= 9.5


@pytest.mark.parametrize("has_shots", [False, True])
def test_failed_transition_report_says_not_measured(has_shots):
    breakdown = sample()
    if not has_shots:
        breakdown.shots = []
    breakdown.provenance.update(transition_detector="test", transition_status="failed")
    text = report.render_markdown(breakdown)

    assert not report._transition_ran(breakdown)
    assert "not measured" in text and "detection failed" in text
    assert "none observed" not in text and "detector ran" not in text


def test_transition_failure_status_is_saved(monkeypatch):
    wire_stages(monkeypatch)
    monkeypatch.setattr(source_map, "build_source_map", lambda p, d, f, shots: source_map.SourceMap(f, d, []))

    def fail(path):
        raise api.transitions_mod.TransitionProbeError("decode failed")

    monkeypatch.setattr(api.transitions_mod, "detect_transitions", fail)
    breakdown = api.study("reference.mp4", detect_transitions=True)
    saved = storage.load_breakdown("tiktok-777")
    text = (storage.breakdown_dir("tiktok-777") / "breakdown.md").read_text(encoding="utf-8")

    assert breakdown.provenance["transition_status"] == saved.provenance["transition_status"] == "failed"
    assert "transition_detector" in saved.provenance
    assert "not measured" in text and "none observed" not in text
