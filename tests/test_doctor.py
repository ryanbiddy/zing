"""Doctor: honest tiered checks, offline. All external probes are mocked."""

from __future__ import annotations

import json
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from myzing import doctor


@pytest.fixture(autouse=True)
def _fresh_version_cache():
    doctor._version_cache.clear()
    doctor._peer_cache.clear()
    yield
    doctor._version_cache.clear()
    doctor._peer_cache.clear()


@pytest.fixture(autouse=True)
def _no_ytdlp_config(monkeypatch):
    """D-13 made doctor read REAL yt-dlp config files — tests must never
    depend on what this host's config contains (the defect itself was
    host-config-dependent behavior). Tests that want a config monkeypatch
    _ytdlp_config_paths explicitly."""
    monkeypatch.setattr(doctor, "_ytdlp_config_paths", lambda: [])


@pytest.fixture(autouse=True)
def _hermetic_modules(monkeypatch):
    """#276 (Lane A reconciliation): the ytdlp tests probed the REAL venv
    for the yt_dlp_ejs solver — green only where yt-dlp[default] was
    installed, i.e. they asserted the host's install state, not the
    code's behavior. Baseline: a fully-conformant host (every module
    present). Tests that care about absence monkeypatch _has_module
    themselves and override this."""
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)


@pytest.fixture(autouse=True)
def _hermetic_whisper_cache(monkeypatch, tmp_path):
    """Pin the Hugging Face cache the way _hermetic_modules pins imports.

    check_whisper now reads a real cache directory, so without this the
    doctor suite would assert the HOST's download state — green on a
    machine that has run `zing study`, different on CI. Same defect
    #276 fixed for the yt-dlp solver probe.

    Baseline: the configured model is already downloaded, which is also
    the branch that touches no disk-space math. Tests for the other
    states override this explicitly.
    """
    cache = tmp_path / "hf-hub"
    (cache / "models--Systran--faster-whisper-large-v2").mkdir(parents=True)
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    return cache


@pytest.fixture
def bare_machine(monkeypatch):
    """A machine with nothing installed and no network."""
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "")

    def refuse(url, timeout=0):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", refuse)
    from myzing import suite_peer
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", refuse)


@pytest.fixture
def full_machine(monkeypatch):
    """Everything installed, current yt-dlp, uoink absent."""
    monkeypatch.setattr(doctor, "_which", lambda name: f"C:/tools/{name}.exe")
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(
        doctor, "_run_version",
        lambda cmd: "2026.07.01" if "yt-dlp" in cmd[0] else "ffmpeg version 7.1",
    )

    def refuse(url, timeout=0):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", refuse)
    from myzing import suite_peer
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", refuse)


# -- bare machine ------------------------------------------------------------

def test_bare_machine_exits_nonzero(bare_machine, capsys):
    assert doctor.run([]) == 1
    out = capsys.readouterr().out
    assert "NOT ready" in out
    assert "ffmpeg" in out


def test_bare_machine_messages_are_actionable(bare_machine, capsys):
    doctor.run([])
    out = capsys.readouterr().out
    # every failing non-optional line names its fix command
    assert "pip install" in out or "winget" in out or "apt install" in out or "brew" in out
    # degraded modes are named, not implied
    assert "transcription is skipped" in out
    assert "caption OCR is skipped" in out
    assert "shot detection is skipped" in out
    assert "local files only" in out


def test_bare_machine_uoink_absence_is_calm(bare_machine, capsys):
    doctor.run([])
    out = capsys.readouterr().out
    assert "standalone" in out  # absent uoink is fine, not an error


def test_only_required_gates_exit_code(bare_machine, monkeypatch):
    # ffmpeg present but everything else still missing -> ready (exit 0)
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "C:/tools/bin" if name in ("ffmpeg", "ffprobe") else None,
    )
    assert doctor.run([]) == 0


# -- full machine ------------------------------------------------------------

def test_full_machine_exits_zero(full_machine, capsys):
    assert doctor.run([]) == 0
    assert "Ready." in capsys.readouterr().out


def test_json_output_is_parseable_and_complete(full_machine, capsys):
    assert doctor.run(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["required_missing"] == []
    names = {c["name"] for c in payload["checks"]}
    assert names == {
        "ffmpeg", "yt-dlp", "scenedetect", "faster-whisper", "ocr",
        "tts", "uoink",
    }
    tiers = {c["name"]: c["tier"] for c in payload["checks"]}
    assert tiers["ffmpeg"] == "required"
    assert tiers["scenedetect"] == "recommended"
    assert tiers["uoink"] == "optional"


def test_json_on_bare_machine_reports_required_missing(bare_machine, capsys):
    assert doctor.run(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["required_missing"] == ["ffmpeg"]


# -- yt-dlp staleness --------------------------------------------------------

def test_ytdlp_stale_version_warns_with_fix(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2025.01.15")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.ok is True  # stale is a warning, not a failure
    assert check.data["stale"] is True
    assert "pip install -U yt-dlp" in check.fix
    assert "days old" in check.detail


def test_ytdlp_fresh_version_is_quiet(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.data["stale"] is False
    assert check.fix == ""


def test_ytdlp_unparsable_version_does_not_crash(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "nightly-abc123")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.ok is True
    assert check.data["age_days"] is None


# -- B-Q12: JS-runtime coverage (yt-dlp needs deno/node for YouTube) ----------

def test_ytdlp_without_js_runtime_warns_with_fix(monkeypatch):
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name == "yt-dlp" else None,
    )
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    # Audit #201 P1 (re-found by Lane C SG-1 2026-07-19): this used to
    # assert ok=True "warning-grade, like staleness" — the exact leaf
    # test that let the fully-ready contradiction survive. A capability
    # the check itself says WILL fail is not a warning.
    assert check.ok is False
    assert check.mark == "degraded"
    assert "YouTube URL study fails" in check.degraded_mode
    assert "local files still work" in check.degraded_mode
    assert check.data["js_runtime"] is None
    assert "JS runtime" in check.detail and "YouTube" in check.detail
    assert "deno" in check.fix.lower()


def test_ytdlp_with_deno_is_quiet(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.data["js_runtime"] == "deno"
    assert "JS runtime" not in check.detail
    assert check.fix == ""


def test_stale_and_no_js_runtime_both_reported(monkeypatch):
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name == "yt-dlp" else None,
    )
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2025.01.15")
    check = doctor.check_ytdlp(today=date(2026, 7, 18))
    assert check.data["stale"] is True and check.data["js_runtime"] is None
    assert "days old" in check.detail and "JS runtime" in check.detail
    assert "pip install -U yt-dlp" in check.fix and "deno" in check.fix.lower()


# -- F-05: ocr check must match what the pipeline imports ---------------------
#
# study/captions.py imports `from rapidocr import RapidOCR` and nothing else.
# Doctor blessing rapidocr_onnxruntime or tesseract is a lie: study would skip
# OCR on those machines while doctor prints ok (S1-FIXLIST F-05, lane-a #2).

def test_ocr_ok_only_when_rapidocr_module_present(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(doctor, "_has_module", lambda name: name == "rapidocr")
    check = doctor.check_ocr()
    assert check.ok is True
    assert "rapidocr" in check.detail


def test_ocr_rapidocr_onnxruntime_alone_is_not_ok(monkeypatch):
    # The old package installs fine but the pipeline never imports it.
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(
        doctor, "_has_module", lambda name: name == "rapidocr_onnxruntime"
    )
    check = doctor.check_ocr()
    assert check.ok is False
    assert "rapidocr_onnxruntime" in check.detail  # found, but honestly not wired
    assert "myzing[study]" in check.fix
    assert "caption OCR is skipped" in check.degraded_mode


def test_ocr_tesseract_alone_is_not_ok(monkeypatch):
    # The pipeline has no tesseract backend; a binary on PATH changes nothing.
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "/usr/bin/tesseract" if name == "tesseract" else None,
    )
    check = doctor.check_ocr()
    assert check.ok is False
    assert "tesseract" in check.detail  # found, but honestly not wired
    assert "myzing[study]" in check.fix


def test_ocr_check_agrees_with_pipeline_import():
    captions_src = (
        Path(doctor.__file__).parent / "study" / "captions.py"
    ).read_text(encoding="utf-8")
    assert f"from {doctor.OCR_MODULE} import" in captions_src


# -- F-10: scenedetect is checked, and "Ready." is never unqualified ----------
#
# Shot detection is the core measurement; a fresh install without scenedetect
# used to print "Ready." while measuring zero shots (S1-FIXLIST F-10,
# lane-a #5).

def test_scenedetect_missing_is_recommended_with_fix(bare_machine):
    check = doctor.check_scenedetect()
    assert check.tier == "recommended"
    assert check.ok is False
    assert "myzing[study]" in check.fix
    assert "shot detection is skipped" in check.degraded_mode


def test_scenedetect_present_is_ok(monkeypatch):
    monkeypatch.setattr(doctor, "_has_module", lambda name: name == "scenedetect")
    check = doctor.check_scenedetect()
    assert check.ok is True


def test_scenedetect_check_agrees_with_pipeline_import():
    shots_src = (
        Path(doctor.__file__).parent / "study" / "shots.py"
    ).read_text(encoding="utf-8")
    assert f"import {doctor.SHOT_MODULE}" in shots_src


def test_no_unqualified_ready_when_scenedetect_missing(bare_machine, monkeypatch, capsys):
    # ffmpeg present (required tier satisfied), scenedetect still missing.
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "C:/tools/bin" if name in ("ffmpeg", "ffprobe") else None,
    )
    assert doctor.run([]) == 0  # recommended tier never fails the machine
    out = capsys.readouterr().out
    assert "Ready." not in out  # the unqualified verdict is reserved
    assert "scenedetect" in out


def test_full_machine_ready_is_unqualified(full_machine, capsys):
    assert doctor.run([]) == 0
    out = capsys.readouterr().out
    assert "Ready." in out
    assert "degraded" not in out.lower()


# -- summarize is the zing_status contract -----------------------------------

def test_summarize_shape(full_machine):
    summary = doctor.summarize(doctor.run_checks(today=date(2026, 7, 18)))
    assert set(summary) == {"ok", "required_missing", "checks"}
    for c in summary["checks"]:
        assert {"name", "tier", "ok", "detail", "fix", "degraded_mode", "data"} <= set(c)


# -- S5 install-gate observation #2: one-line verdict ------------------------

def test_verdict_line_bare_machine(bare_machine, capsys):
    doctor.run([])
    out = capsys.readouterr().out
    assert "Verdict: NOT ready" in out.splitlines()[2]
    assert "ffmpeg" in out.splitlines()[2]


def test_verdict_line_degraded(bare_machine, monkeypatch, capsys):
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: "C:/tools/bin" if name in ("ffmpeg", "ffprobe") else None,
    )
    doctor.run([])
    verdict = capsys.readouterr().out.splitlines()[2]
    assert "ready for local-file study" in verdict
    assert "degraded" in verdict


def test_verdict_line_fully_ready(full_machine, monkeypatch, capsys):
    # full_machine leaves tts/uoink optional-absent; verdict ignores optional
    doctor.run([])
    verdict = capsys.readouterr().out.splitlines()[2]
    assert verdict == "Verdict: fully ready"


# -- SW-3 (Lane A sweep finding): node-on-PATH is a false comfort -------------

def test_node_only_warns_about_default_runtimes(monkeypatch):
    """node present but no deno: yt-dlp won't use it without explicit
    config — signature-challenge videos 403 (SW-3). The check must warn
    with the config fix, not report quiet health."""
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name in ("yt-dlp", "node") else None,
    )
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert check.data["js_runtime"] == "node"
    assert "403" in check.detail
    assert "--js-runtimes node" in check.fix
    # Not satisfied-by-default → degraded, and honest about scope: the
    # STANDARD config locations were checked (D-13), custom
    # --config-locations remain invisible.
    assert check.ok is False and check.mark == "degraded"
    assert "standard" in check.degraded_mode
    assert "--config-locations" in check.degraded_mode


def test_js_runtime_fixes_point_at_troubleshooting_doc(monkeypatch):
    """D-9 docs half: both JS-runtime failure modes route the user to the
    fetch-troubleshooting page, and the page exists with the fix order."""
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name == "yt-dlp" else None,
    )
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    none_case = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert "FETCH-TROUBLESHOOTING" in none_case.fix

    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name in ("yt-dlp", "node") else None,
    )
    node_case = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert "FETCH-TROUBLESHOOTING" in node_case.fix

    doc = Path(doctor.__file__).resolve().parents[2] / "docs" / "FETCH-TROUBLESHOOTING.md"
    text = doc.read_text(encoding="utf-8")
    for marker in ("pip install -U yt-dlp", "deno", "bgutil", "cookies", "GPL-3.0"):
        assert marker in text
    # the fix ORDER the SG-4 scan established: update -> deno -> bgutil -> cookies
    assert (
        text.index("Update yt-dlp") < text.index("Install deno")
        < text.index("bgutil") < text.index("Cookies")
    )


# -- Audit #201: EJS solver + probe cache + durable ref -----------------------

def test_solver_missing_is_named_with_install_fix(monkeypatch):
    """Runtime without solver scripts reproduces as 'n challenge solving
    failed' — doctor must name the missing half distinctly."""
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(
        doctor, "_has_module", lambda name: name == "yt_dlp"
    )
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert check.data["ejs_solver"] is False
    assert "solver" in check.detail.lower()
    assert 'yt-dlp[default]' in check.fix


def test_solver_present_is_quiet(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert check.data["ejs_solver"] is True
    assert "solver" not in check.detail.lower()


def test_audit_201_no_js_runtime_is_never_fully_ready(full_machine, monkeypatch, capsys):
    """Audit #201 P1's ORIGINAL consumer-boundary reproduction, pinned
    where it failed: everything installed except a JS runtime, and the
    printed verdict must not say 'fully ready' while the yt-dlp detail
    says YouTube WILL fail. Leaf-field tests alone let #203 close this
    finding while the contradiction lived on (Lane C SG-1 2026-07-19)."""
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: None if name in ("deno", "node") else f"C:/tools/{name}.exe",
    )
    assert doctor.run([]) == 0  # recommended-tier: degraded, not fatal
    out = capsys.readouterr().out
    verdict = out.splitlines()[2]
    assert "fully ready" not in verdict
    assert "yt-dlp" in verdict and "degraded" in verdict
    assert "[degraded]" in out  # installed-but-failing, never [MISSING]
    assert "MISSING" not in out


def test_audit_201_solver_missing_is_never_fully_ready(full_machine, monkeypatch, capsys):
    """Same boundary, other half of #201: runtime present, EJS solver
    scripts absent — challenge solving fails, verdict must say so."""
    monkeypatch.setattr(doctor, "_has_module", lambda name: name != "yt_dlp_ejs")
    doctor.run([])
    verdict = capsys.readouterr().out.splitlines()[2]
    assert "fully ready" not in verdict
    assert "yt-dlp" in verdict


# -- S5 gate defects D-11 / D-13 ---------------------------------------------

def test_d11_resolver_prefers_binary_then_module_then_none(monkeypatch):
    """One resolver for doctor's probe AND study's fetch — the gate saw
    'fully ready' from a module probe while ingest ran the binary."""
    monkeypatch.setattr(doctor, "_which", lambda name: "/bin/yt-dlp")
    assert doctor.resolve_ytdlp_argv() == ["/bin/yt-dlp"]

    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(doctor, "_has_module", lambda name: name == "yt_dlp")
    assert doctor.resolve_ytdlp_argv() == [sys.executable, "-m", "yt_dlp"]

    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    assert doctor.resolve_ytdlp_argv() is None


def test_d11_check_reports_the_invocation_it_probed(monkeypatch):
    """data['invocation'] is the machine-readable half: whatever doctor
    verified is exactly what study will run."""
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert check.data["invocation"] == [sys.executable, "-m", "yt_dlp"]


def test_d13_applied_node_config_is_not_represcribed(monkeypatch, tmp_path):
    """The gate box had '--js-runtimes node' in %APPDATA%/yt-dlp/config
    and doctor prescribed it anyway. With the opt-in found in a standard
    location: healthy, quiet fix, and the config path is named."""
    cfg = tmp_path / "config"
    cfg.write_text("--no-mtime\n--js-runtimes node\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "_ytdlp_config_paths", lambda: [cfg])
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name in ("yt-dlp", "node") else None,
    )
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert check.ok is True
    assert check.fix == ""
    assert "enabled via yt-dlp config" in check.detail
    assert check.data["node_config"] == str(cfg)


def test_d13_commented_out_line_does_not_count(monkeypatch, tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("# --js-runtimes node\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "_ytdlp_config_paths", lambda: [cfg])
    monkeypatch.setattr(
        doctor, "_which",
        lambda name: f"/bin/{name}" if name in ("yt-dlp", "node") else None,
    )
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(doctor, "_run_version", lambda cmd: "2026.07.01")
    check = doctor.check_ytdlp(today=date(2026, 7, 19))
    assert check.ok is False and check.mark == "degraded"
    assert "--js-runtimes node" in check.fix


def test_d13_missing_config_file_reads_as_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        doctor, "_ytdlp_config_paths", lambda: [tmp_path / "nope" / "config"]
    )
    assert doctor._ytdlp_config_node_enabled() is None


def test_version_probe_is_cached(monkeypatch):
    calls = {"n": 0}

    def counting_version(cmd):
        calls["n"] += 1
        return "2026.07.01"

    monkeypatch.setattr(doctor, "_which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(doctor, "_run_version", counting_version)
    doctor.check_ytdlp(today=date(2026, 7, 19))
    doctor.check_ytdlp(today=date(2026, 7, 19))
    doctor.check_ytdlp(today=date(2026, 7, 19))
    assert calls["n"] == 1  # one probe, two cache hits inside the TTL


def test_troubleshooting_ref_resolves_to_an_existing_file():
    ref = doctor._troubleshooting_ref()
    assert Path(ref).is_file()  # never a dead pointer, checkout or wheel


def test_developer_guide_checklist_matches_doctor(full_machine):
    """Final review P3-7: the guide claimed to enumerate doctor's checks
    but listed 5 of 7. Pin the enumeration to run_checks() itself."""
    guide = (
        Path(doctor.__file__).resolve().parents[2] / "docs" / "DEVELOPER-GUIDE.md"
    ).read_text(encoding="utf-8")
    for check in doctor.run_checks(today=date(2026, 7, 19)):
        assert check.name in guide, (
            f"DEVELOPER-GUIDE.md's doctor checklist is missing {check.name!r}"
        )


# -- first-run: "Ready." was a correct dead end -------------------------------

def test_ready_names_the_next_command_on_an_empty_workspace(
    full_machine, zing_workspace, capsys
):
    """`zing doctor` is the first command a new user runs, and it ended
    on a bare "Ready." — true, and no help at all. The next step must
    depend on workspace STATE, not be a fixed advert."""
    doctor.run([])
    out = capsys.readouterr().out
    assert "Ready." in out
    assert "zing setup --list" in out
    assert "zing study" in out


def test_next_step_changes_once_something_is_studied(
    full_machine, zing_workspace, capsys
):
    from myzing import storage
    from myzing.schemas import Breakdown, VideoMeta

    storage.save_breakdown(
        Breakdown(meta=VideoMeta(source_url="https://x.test/v", platform="tiktok")),
        slug="tiktok-1",
    )
    doctor.run([])
    out = capsys.readouterr().out
    assert "1 studied video(s), no taste profile yet" in out
    assert "zing setup --links" in out


def test_next_step_is_silent_when_required_tools_are_missing(
    bare_machine, zing_workspace, capsys
):
    """Advice about what to do next is noise while the user cannot run
    anything — the fixes above are the only next step that matters."""
    doctor.run([])
    out = capsys.readouterr().out
    assert "NOT ready" in out
    assert "Next:" not in out


def test_next_step_never_breaks_the_report(full_machine, zing_workspace, monkeypatch, capsys):
    """Guidance is a courtesy; a storage failure must not cost the user
    their environment report."""
    from myzing import storage

    monkeypatch.setattr(
        storage, "list_breakdowns",
        lambda: (_ for _ in ()).throw(OSError("workspace unreadable")),
    )
    assert doctor.run([]) == 0
    out = capsys.readouterr().out
    assert "Ready." in out
    assert "Next:" not in out


def test_no_failing_check_strands_the_user(bare_machine, zing_workspace):
    """Every check that is NOT ok must either name a FIX or explain what
    is lost (degraded_mode) — ideally both. Mirrors Lane A's #353, which
    found dependency-broken warnings that said what failed but not what
    to do, while their missing-dependency siblings named the command.

    Uses the bare machine so every not-ok branch actually fires: an
    audit that only exercises today's host proves nothing about the
    states a new user is most likely to hit."""
    stranded = [
        c.name for c in doctor.run_checks(today=date(2026, 7, 20))
        if not c.ok and not c.fix and not c.degraded_mode
    ]
    assert not stranded, (
        f"check(s) report a problem with neither a fix nor a stated "
        f"consequence: {stranded}"
    )


def test_every_required_and_recommended_failure_names_a_command(
    bare_machine, zing_workspace
):
    """For the tiers a user can DO something about, the fix must be a
    runnable command rather than a description. Optional peers are
    exempt: 'no uoink at ...' is calm absence with nothing to run."""
    import re

    RUNNABLE = re.compile(r"pip install|winget|brew install|apt install|zing ")
    bad = [
        (c.name, c.fix)
        for c in doctor.run_checks(today=date(2026, 7, 20))
        if not c.ok and c.tier in (doctor.REQUIRED, doctor.RECOMMENDED)
        and not RUNNABLE.search(c.fix or "")
    ]
    assert not bad, f"fixable tier without a runnable command: {bad}"


class _Usage:
    """Minimal shutil.disk_usage stand-in (only .free is read)."""

    def __init__(self, free: int) -> None:
        self.free = free
        self.total = free * 10
        self.used = self.total - free


def _named(checks, name):
    for check in checks:
        if check.name == name:
            return check
    raise AssertionError(f"no {name} check in doctor output")


# -- check_whisper answers the question Lane A's #353 sends users to ask -------


def test_downloaded_model_is_reported_as_present(_hermetic_whisper_cache):
    """The warning says a failed load is 'usually a download or disk-space
    problem; run zing doctor'. Doctor has to speak to the download."""
    check = _named(doctor.run_checks(today=date(2026, 7, 20)), "faster-whisper")
    assert check.ok
    assert "is downloaded" in check.detail
    assert check.data["cached"] is True


def test_absent_model_is_named_with_the_room_available(
    monkeypatch, _hermetic_whisper_cache
):
    """Not downloaded yet is NOT a failure — it downloads on first run —
    but doctor must say so rather than implying the weights are here."""
    for entry in _hermetic_whisper_cache.iterdir():
        entry.rmdir()
    check = _named(doctor.run_checks(today=date(2026, 7, 20)), "faster-whisper")
    assert check.ok
    assert "downloads on the first" in check.detail
    assert check.data["cached"] is False


def test_no_room_for_the_model_is_a_fixable_failure(
    monkeypatch, _hermetic_whisper_cache
):
    """The disk-space half of that warning. Reporting READY here is what
    stranded the user: they were told to run doctor, and doctor said the
    package imports."""
    for entry in _hermetic_whisper_cache.iterdir():
        entry.rmdir()
    monkeypatch.setattr(
        doctor.shutil, "disk_usage", lambda path: _Usage(free=int(1.2e9))
    )
    check = _named(doctor.run_checks(today=date(2026, 7, 20)), "faster-whisper")

    assert not check.ok
    assert "1.2 GB is free" in check.detail
    assert check.fix, "a disk problem must name what to do"
    assert check.degraded_mode, "and what it costs"
    assert "ZING_WHISPER_MODEL=small" in check.fix


def test_a_missing_cache_directory_is_unknown_never_asserted_absent(
    monkeypatch, tmp_path
):
    """No cache dir yet means Zing cannot tell whether the weights fit —
    say that, do not report a size check that never happened."""
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "nothing-here"))
    check = _named(doctor.run_checks(today=date(2026, 7, 20)), "faster-whisper")
    assert check.ok
    assert "could not be checked" in check.detail
    assert check.data["cache"] is None


def test_the_model_checked_is_the_model_transcribe_will_load(
    monkeypatch, _hermetic_whisper_cache
):
    """Checking large-v2 while transcribe loads a different model would be
    a confident answer about the wrong file."""
    from myzing.study import transcribe

    monkeypatch.setenv(transcribe.ENV_MODEL, "small")
    check = _named(doctor.run_checks(today=date(2026, 7, 20)), "faster-whisper")

    assert check.data["model"] == "small"
    # large-v2 IS cached in the fixture; 'small' is not, so a check that
    # ignored the override would wrongly report the weights as present.
    assert check.data["cached"] is False
