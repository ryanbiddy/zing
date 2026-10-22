"""The default test run skips real inference before any loader or hub call."""
from pathlib import Path


def test_default_real_asr_skips_before_loading_or_hub_calls(pytester, monkeypatch):
    from myzing.study import transcribe
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("default pytest attempted a model or hub call")
    monkeypatch.setattr(transcribe, "_load_model", forbidden)
    # No dependency on HF offline flags or whether a model happens to be cached.
    for name in ("ZING_REQUIRE_REAL_ASR", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(name, raising=False)
    try:
        import huggingface_hub
    except ImportError:
        pass
    else:
        monkeypatch.setattr(huggingface_hub, "snapshot_download", forbidden)
        monkeypatch.setattr(huggingface_hub, "hf_hub_download", forbidden)
    root = Path(__file__).parent
    pytester.makeconftest((root / "conftest.py").read_text(encoding="utf-8"))
    pytester.makepyfile(test_actual_real_asr=(root / "test_study_transcribe_real.py").read_text(encoding="utf-8"))
    result = pytester.runpytest_inprocess("-q", "-ra")
    result.assert_outcomes(passed=1, skipped=2)
    assert calls == []
    result.stdout.fnmatch_lines(["*real-model test requires explicit opt-in*"])
