# Zing Developer Guide

Welcome to the Zing project. This guide helps new developers set up, run, and test the Zing codebase.

---

## 1. Development Installation

Zing uses [uv](https://github.com/astral-sh/uv) to manage python environments and dependencies. Follow these commands to set up:

```bash
# Clone the repository
git clone https://github.com/ryanbiddy/zing
cd zing

# Synchronize the environment with all development and study extras
uv sync --all-extras
```

Alternatively, if you are using standard `pip`:

```bash
# Install the package in editable mode with dev and study extras
pip install -e ".[dev,study]"
```

---

## 2. Environment Verification

Run `zing doctor` to ensure all external dependencies are correctly configured:

```bash
# Run the doctor command via uv
uv run zing doctor
```

This command checks for (pinned by a test against doctor's real check
list — update both together):
1. **ffmpeg & ffprobe (required):** video and audio analysis. If missing on Windows: `winget install Gyan.FFmpeg`.
2. **yt-dlp (recommended):** fetching remote reference videos, including its JS-runtime and EJS-solver readiness for YouTube.
3. **scenedetect (recommended):** shot-boundary detection.
4. **faster-whisper (recommended):** transcription with word-level timestamps.
5. **ocr — rapidocr (recommended):** burned-caption text extraction from frames.
6. **tts (optional):** voiceover synthesis (kokoro local, or ElevenLabs with an API key).
7. **uoink (optional):** the suite peer on port 5179, probed per INTEGRATION-CONTRACT v1 (absent is calm; unhealthy names its code).
8. **pillow (optional):** local still meme rendering; in a checkout, run `uv sync --extra memes`.
9. **layout (optional):** pinned OpenCV runtime and verified local YuNet model; fetch explicitly with `zing layout fetch-model`.
10. **color (optional):** NumPy for local SDR look matching and LUT application; in a checkout, run `uv sync --extra color`.
11. **hyperframes (optional):** sidecar prerequisites: Node 24, the pinned npm install, a configured local browser, and FFmpeg. See [HyperFrames setup](HYPERFRAMES-SIDECAR.md); `zing render` uses the adapter for v2 HyperFrames captions.
12. **libass (optional):** FFmpeg caption burn-in needs the `ass` or `subtitles` filter. Captioned renders check before media probing, file creation, or voiceover synthesis; the filter probe is cached per executable for the process lifetime. Restart Zing after replacing a binary at the same path. The HyperFrames caption sidecar does not need libass.

On macOS, install `brew install ffmpeg-full`, then select its binaries:

```bash
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
ffmpeg -hide_banner -filters
```

Homebrew's regular `ffmpeg` 9.0.2 bottle lacks libass. The
[ffmpeg-full formula](https://formulae.brew.sh/formula/ffmpeg-full) enables it,
provides Apple Silicon bottles, and is keg-only, so the PATH step is required.
Alternatively, `sudo port install ffmpeg` installs
[MacPorts FFmpeg](https://ports.macports.org/port/ffmpeg/details/) with libass;
put `/opt/local/bin` first on PATH. Both options were checked on October 21, 2026.

13. **caption_geometry (optional):** study runtime packages and verified local OCR assets. See [caption geometry](CAPTION-GEOMETRY.md) for explicit model provisioning and the sidecar contract.
14. **fonts (optional):** Pillow/OpenCV and verified local font/license pairs. In a checkout, run `uv sync --extra fonts`; `zing fonts fetch --all` explicitly provisions the library. See [font candidates](FONT-CANDIDATES.md).
15. **audio (optional):** NumPy for beat, onset, role and loudness analysis; in a checkout, run `uv sync --extra audio`.
16. **heic (optional):** HEIC/HEIF photos for `zing meme` and `zing still` decode through FFmpeg. Doctor probes a 248-byte HEIF header (no encoder or sample photo needed): FFmpeg 8.1.2 reads HEIF image items, 6.1.1 does not. Zing bundles no HEIC decoder; convert photos to JPEG/PNG or use FFmpeg 7.1 or newer.

---

## 3. Running Tests

Zing has a comprehensive test suite managed by `pytest`. Run tests to verify the installation:

```bash
# Run the test suite using uv
uv run pytest
```

All tests are located in the [tests](../tests) directory.

---

## 4. Codebase Architecture

The codebase is organized in the [src/myzing](../src/myzing) directory:

* [cli.py](../src/myzing/cli.py): CLI routing entrypoint.
* [doctor.py](../src/myzing/doctor.py): Environment checking script.
* [schemas.py](../src/myzing/schemas.py): Stdlib dataclass schemas defining video breakdowns, style profiles, and EDLs.
* [storage.py](../src/myzing/storage.py): Local JSON-based storage manager.
* [study/](../src/myzing/study): Submodule containing video ingest and metadata extraction logic.

---

## 5. Development Workflow

All changes are submitted as pull requests targeting `main` with
squash-merge enabled, and the full test suite must pass. The codebase is
partitioned by subsystem (see the module map above) so that independent
work rarely touches the same files; `src/myzing/schemas.py` is the shared
contract and changes to it are coordinated deliberately.

## 6. Workspace and media paths

To move an assembled edit, move its project folder with the EDL and media
inside it. For example, assembly writes this layout:

```text
project/workspace/breakdowns/<slug>/
  breakdown.json
  media.mp4
  draft-edl.json       # clips[].src is "media.mp4"
```

After moving `project`, render the EDL from its new location:

```bash
zing render "moved project/workspace/breakdowns/<slug>/draft-edl.json"
```

A relative `clips[].src` or `audio[].src` is interpreted from the EDL
file's directory, independent of the current working directory and
`ZING_HOME`. References such as `../assets/music.wav` are supported. New
assembly output uses relative paths with forward slashes. Schema version
1 EDLs with absolute paths remain readable; those references still point
to the original location and must be edited if their assets move. Moving
only the EDL changes the base of its relative references, so move the
assets with it or update `src` values.

The CLI resolves `--workspace` (or the `ZING_HOME`/home default) once at
the command boundary. MCP handlers capture the resolved workspace before
dispatch. Inner storage and engine calls receive that path through the
workspace argument or `storage.use_workspace()`; worker threads retain it
even if the process changes directory or `ZING_HOME` later. Python callers
should use `storage.resolve_workspace(root)` at their own entry point and
pass the result inward.

Render resolves asset references once, checks every video and audio file
before probing or synthesis, and passes the resolved paths through to
FFmpeg. MCP rejects missing assets before creating a render job and checks
again when its worker runs. Errors name the missing file and tell the user
to restore it or update the EDL reference. No render work directory or
output is created for a missing asset; an existing output is preserved.
Python callers rendering an in-memory EDL must supply its asset directory
as `base_dir` (the default is the current directory).

`tests/test_workspace_paths.py` generates its own media with FFmpeg. The
study path runs ingest, shots, keyframes, audio measurement, and storage;
transcription and OCR are stubbed so these path tests need no downloads.
It covers relative/absolute/environment roots, spaces and apostrophes,
moved projects, legacy absolute EDLs, relative audio, missing assets, and
workspace capture before MCP dispatch. Run the full suite and required
FFmpeg gate with:

```bash
uv run --frozen pytest -ra
ZING_REQUIRE_OCR=1 ZING_REQUIRE_FFMPEG=1 uv run --frozen pytest -q -m ffmpeg --expected-ffmpeg-tests 364
```

CI (`.github/workflows/ci.yml`) runs that gate on four FFmpeg stacks, with
skips counted as failures:

| Job | Runner | FFmpeg and libass | Tests |
|---|---|---|---|
| `ffmpeg-gates-ubuntu` | `ubuntu-24.04`, pinned | apt FFmpeg 6.1.1, libass 0.17.1 | full gate |
| `ffmpeg-gates-ubuntu-latest` | `ubuntu-latest` (Ubuntu 26.04 since October 2026) | apt FFmpeg 8.0.1, libass 0.17.4 | full gate |
| `ffmpeg-smoke-windows` | `windows-latest` | Chocolatey FFmpeg 9.x | full gate |
| `ffmpeg-smoke-macos` | `macos-latest` | Homebrew `ffmpeg-full` 9.0.2, libass 0.17.5 | listed subset |

The 24.04 job stays pinned so FFmpeg 6 keeps coverage; the `ubuntu-latest`
job follows GitHub's newest image so new distro stacks fail in CI first.
Tests that use FFmpeg `drawtext` as an independent text reference render one
line per call: FFmpeg 6.1.4, 7.1.3, 8.0.1 and 8.1.0 draw a `.notdef` box for
each newline ([FFmpeg issue #21565](https://code.ffmpeg.org/FFmpeg/FFmpeg/issues/21565),
fixed in 7.1.4, 8.0.2 and 8.1.1).

Real-model tests require explicit opt-in even when models are already cached:
`ZING_REQUIRE_REAL_ASR=1` for Whisper, `ZING_REQUIRE_OCR=1` for the generated
OCR fixtures, `ZING_REQUIRE_YUNET=1` for face inference, and
`ZING_REQUIRE_KOKORO=1` for synthesis. The separate caption real-media test
requires `ZING_CG2_REAL_ROOT` to name its local fixture directory. The shared
`real_model(env=...)` marker skips before fixture/model loading; its reason is
registered in `tests/test_skip_registry.py`.

Default `pytest` needs no HF offline environment variables to avoid real model
loads. `tests/test_real_model_opt_in.py` removes those variables and poisons
the ASR loader and hub download functions to prove the default skips first.
The opted-in Whisper test also sets `local_files_only=True`: provision a model
explicitly outside the tests before running it. The mandatory FFmpeg gate
opts into OCR with pre-provisioned assets; missing assets still fail the gate.
