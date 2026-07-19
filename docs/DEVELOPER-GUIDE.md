# Zing Developer Guide

Welcome to the Zing project. This guide helps new developers set up, run, and test the Zing codebase.

---

## 1. Development Installation

Zing uses [uv](https://github.com/astral-sh/uv) to manage python environments and dependencies. Follow these commands to set up:

```bash
# Clone the repository
git clone <repository-url>
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
* [schemas.py](../src/myzing/schemas.py): Pydantic data schemas defining video breakdowns, style profiles, and EDLs.
* [storage.py](../src/myzing/storage.py): Local JSON-based storage manager.
* [study/](../src/myzing/study): Submodule containing video ingest and metadata extraction logic.

---

## 5. Development Workflow

Zing utilizes git worktrees for parallel lane development:
* **Lane A:** Study engine and video ingestion.
* **Lane B:** Surface, doctor, storage, and MCP server.
* **Lane C:** Pacing, audio ducking, and video renderer.
* **Lane D (Antigravity):** Taste guidelines, truth data, and QA review.

All changes must be submitted via pull requests targeting `main` with squash-merge enabled.
