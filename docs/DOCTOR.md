# Doctor and speech setup

Run `zing doctor` to check dependencies and cached speech models. The command
only inspects model files; it neither downloads nor runs transcription. Its JSON
output includes each model's cache path and whether Zing verified its SHA-256.
`zing setup` prints the same inventory before listing taste presets.

For clips with speech, install the `study` extra and prepare a model:

```console
zing doctor --speech-model small.en
```

The command asks for **yes** before downloading. Enter cancels. You can use
`zing setup --speech-model small.en` for the same operation; this invocation
only prepares speech and does not start a taste study.

| Choice | Download | What to expect |
|---|---|---|
| `small.en` | ~486 MB | Faster first English draft. Review names, accents, quiet words and caption timing. |
| `large-v2` | ~3.09 GB | Slower and multilingual, with higher speech accuracy. Still the `zing study` default. |
| `skip` | 0 MB | No spoken captions or whole-line continuity. Studio may exclude clips without safe speech timing. |

For a script, choose a model and explicitly authorize its download:

```console
zing doctor --speech-model small.en --yes --json
zing setup --speech-model large-v2 --yes
```

Without `--yes`, non-interactive setup refuses an uncached download. `--yes`
alone is invalid. Plain `zing doctor --json` remains read-only.

Downloads use immutable Systran model revisions with SHA-256 verification for
the weights, configuration, tokenizer and vocabulary. Progress reports bytes
received; the receipt names verified hashes and bytes downloaded. The cache is
`ZING_HOME/models/speech/<model>/<revision>`. Temporary download files live beside
their destination and are removed on failure. A failed verification never
replaces a cached file. Zing checks the complete model before using it.

Existing complete local model directories and Hugging Face snapshots can also
be used offline. Doctor distinguishes these from Zing's verified cache and does
not claim to have tested native loading. `ZING_WHISPER_MODEL` selects the model
for ordinary study; Studio stores its choice per session. Downloading small.en
does not change the large-v2 default for other commands.

If inference is unavailable, install `myzing[study]`, inspect the study warnings,
and resume the saved Studio session. Missing timed words remain missing evidence;
an audio stream alone does not prove speech or establish safe caption timing.
