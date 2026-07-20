# SG-4 scan: verify every install command zing PRINTS

Prompted by CX-8 — a fabricated macOS install guide found in the suite,
promising a .dmg that never existed. The right paranoia to apply to my
own surface: doctor's whole promise is "every failing line prints the
exact command that fixes it". A wrong command there is worse than no
command, because the user trusts it and stops looking.

Verified on this machine where possible; checked against the source of
truth otherwise.

| Command printed | Verdict |
|---|---|
| `winget install Gyan.FFmpeg` | **VERIFIED live** — resolves to FFmpeg 8.1.2, publisher Gyan |
| `winget install DenoLand.Deno` | **VERIFIED live** — resolves to Deno 2.9.3, Deno Land Inc. |
| `brew install ffmpeg` / `sudo apt install ffmpeg` | standard, unverifiable from Windows — stated as unverified rather than claimed |
| `pip install "myzing[study]"` | correct: the extra declares yt-dlp/scenedetect/faster-whisper/onnxruntime/rapidocr |
| `pip install "yt-dlp[default]"` | correct: ships the EJS solver |
| `pip install "myzing[mcp]"` | correct: declares `mcp` |
| `pip install "myzing[render]"` **for kokoro** | **WRONG — mine, shipped last cycle** |

## The defect I shipped, found by scanning my own advice

`#324` fixed a TTS false-ready and, in the same change, told users:

> install the render extras so kokoro-onnx is importable:
> `python -m pip install "myzing[render]"`

`[render]` is `["pysubs2>=1.8.1"]`. **kokoro-onnx appears nowhere in
pyproject at all** — zero occurrences. That command can never make it
importable. I wrote a fix that cannot work, in the act of fixing a fix
that could not work.

**The correct facts already existed one module away**, in Lane C's
provider:

> kokoro-onnx is not installed. It is intentionally excluded from the
> default install because its runtime pulls espeakng-loader; install it
> separately on a supported Python 3.10-3.13 environment.

Deliberate exclusion, named reason, named Python range. I wrote a
parallel version instead of reading theirs — the same failure as the
TOKEN_LOCATION incompleteness, where another lane's text was more
correct than my code.

Corrected: doctor now prints `pip install kokoro-onnx` with the reason
and the Python range. Two tests pin it — one asserting doctor's advice
agrees with the provider's own error on package name and Python range,
one asserting no extra declares kokoro (so any future message
prescribing an extra for it fails).

## And my own test was pinning the wrong command

`test_doctor_prescribes_the_runtime_not_the_download`, written by me
one cycle ago, asserted `'myzing[render]' in check.fix`. It protected
my wrong advice for exactly one cycle. **Sixth instance of the
pinned-message trap this session, and the first one I authored myself.**

## Sources

- `winget show` on this machine (live)
- this repo's `pyproject.toml`; `src/myzing/render/tts.py`
