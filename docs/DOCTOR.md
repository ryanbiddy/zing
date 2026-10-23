# Checking local capabilities

Run `zing doctor --json` for availability and remedies, or `zing doctor` for
the terminal summary. The checklist is in the [developer guide](DEVELOPER-GUIDE.md).

The `audio` check reports NumPy availability. The optional `audio-ml` check
reports sherpa-onnx package presence and version, and verifies both CED assets
against pinned SHA-256 and byte size. It requires sherpa-onnx 2.0 or newer,
because 1.x wheels link GPL espeak-ng; tagging falls back to the heuristic on
an older runtime. It exposes the revision, runtime version, paths, and
`network_used: false`. This is a package/cache check; it does not start native
inference or promise that inference will succeed.

Install `myzing[audio-ml]`, then explicitly run `zing audio fetch-model --consent`
with the same workspace. Installing the extra does not fetch weights. Until
both are available, audio and music use the labeled heuristic fallback. See
[Audio](AUDIO.md) for confidence limits and [notices](THIRD-PARTY-NOTICES.md)
for licenses and pins.

Doctor's existing Uoink peer check is separate from the offline audio checks.
During isolated acceptance, set `UOINK_URL=http://127.0.0.1:1` before running it.
