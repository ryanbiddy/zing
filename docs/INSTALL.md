# Install Zing

Zing is pre-alpha. It runs in a terminal, the window where you paste commands
and press Enter. No Zing account or API key is needed. Install Python, Zing's
Python packages and FFmpeg, then let `zing doctor` check them.

**Until the PyPI release, use the source checkout below.** The planned package
install is `pipx install "myzing[all]"`, or `uv tool install "myzing[all]"`.
These registry commands are not an available install today.

## Windows

1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/).
   In the installer, enable the option to add Python to PATH. PATH is the list
   of folders Windows searches for commands. Close and reopen PowerShell.
   Alternatively, install [uv](https://docs.astral.sh/uv/getting-started/installation/),
   which can install a suitable Python for you. The checkout path needs uv.
2. Open PowerShell in a folder you own, such as Documents. Check Python:

   ```console
   python --version
   ```

3. Install FFmpeg with Windows Package Manager:

   ```console
   winget install --id Gyan.FFmpeg -e
   ```

   This ID selects Gyan's full build, which includes libass and libx264.
   If winget is missing, install Microsoft's App Installer from the Microsoft
   Store and reopen PowerShell. If you already use Chocolatey, its alternative is
   `choco install ffmpeg-full` in an administrator terminal. You only need one.
4. Reopen PowerShell so the new commands can be found. Continue with the source
   checkout below. After the PyPI release, a pipx install will instead be:

   ```console
   python -m pip install --user pipx
   python -m pipx ensurepath
   pipx install "myzing[all]"
   ```

   Reopen PowerShell after `ensurepath`. With uv, the equivalent package install
   is `uv tool install "myzing[all]"`. Choose one tool, not both.

## macOS

1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/macos/),
   or install [uv](https://docs.astral.sh/uv/getting-started/installation/) and let
   it manage Python. Open Terminal from Applications > Utilities.
2. Install [Homebrew](https://brew.sh/) using its instructions. Install FFmpeg:

   ```sh
   brew install ffmpeg-full
   export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
   ```

   Homebrew's plain `ffmpeg` bottle lacks libass. `ffmpeg-full` is keg-only,
   so installing it does not put its commands first on PATH. Add the export
   line above to your `~/.zprofile` file to keep it for new Terminal windows
   (or your shell's startup file if you do not use zsh).
3. Continue with the source checkout. After the PyPI release, use
   `uv tool install "myzing[all]"`, or install pipx through Homebrew with
   `brew install pipx`, run `pipx ensurepath`, reopen Terminal, then run
   `pipx install "myzing[all]"`.

## Linux

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), which
   can supply Python. If using your distribution's Python instead, it must be
   3.10 or newer. Open Terminal.
2. On Ubuntu or Debian, refresh the package list and install FFmpeg:

   ```sh
   sudo apt update
   sudo apt install ffmpeg
   ```

   On Fedora, use `sudo dnf install ffmpeg` after enabling a repository that
   supplies the full codecs, such as [RPM Fusion](https://rpmfusion.org/Configuration).
   Fedora's `ffmpeg-free` may lack libx264. Follow that repository's current
   instructions if packages conflict. Zing does not enable repositories or
   remove conflicting packages for you.
3. Continue with the source checkout. After the PyPI release, use
   `uv tool install "myzing[all]"`. For pipx, install your distribution's `pipx`
   package, run `pipx ensurepath`, reopen Terminal, then run
   `pipx install "myzing[all]"`.

## Source checkout, available now

On the [Zing repository](https://github.com/ryanbiddy/zing), choose **Code >
Download ZIP**, extract it into a folder you own, then open your terminal in
that folder. You should see `pyproject.toml` in the file browser. Install uv
using the link above if you have not already, then run:

```console
uv sync --all-extras
uv run --frozen zing doctor
uv run --frozen zing studio
```

The first command installs the Python packages and can download Python. It
does not install FFmpeg or download speech models. In this checkout, put
`uv run --frozen` before each `zing` command in the guides. For example,
`zing setup --ffmpeg` becomes `uv run --frozen zing setup --ffmpeg`.

After a package install through pipx or uv tool, use `zing doctor`, then
`zing studio` directly. Follow [your first draft](STUDIO.md#your-first-draft-in-10-minutes)
to try generated media before using your own clips.

## Let Zing help with FFmpeg

`zing setup --ffmpeg` shows the OS package-manager command, then asks you to
type **yes** in a terminal. Enter, `y` and `no` decline. It runs the package
manager only after that answer, then checks the FFmpeg found on PATH again.
The package manager may also ask for administrator credentials or confirmation.

`--yes` never skips this prompt. It also cannot select FFmpeg setup by itself.
`zing setup --ffmpeg --json` and `zing setup --ffmpeg --non-interactive` only
print instructions, as does piped input. They do not install anything.

Doctor requires FFmpeg and ffprobe 6.0 or newer, the libx264 encoder, libass
(`ass` or `subtitles`), and the drawtext, sidechaincompress, lut3d, xfade,
acrossfade and zoompan filters. Drawtext is used by some text features.
An installed binary alone does not prove that these are available.

If setup finishes but verification fails, reopen the terminal, apply any PATH
step shown and run doctor again. It checks the selected binary, so an older
copy earlier on PATH can hide your new install. Zing never downloads or bundles
FFmpeg binaries itself. Your package manager supplies them under their own
licenses, including GPL builds.

## Models and disk space

For speech, Studio offers **small.en**, about 486 MB for English,
**large-v2**, about 3.09 GB for multilingual speech, or **skip**, with no download.
Selecting a model and confirming a plan are separate from consenting to its
download. Type **yes** only if you want the listed files. To prepare English
speech separately, run `zing doctor --speech-model small.en` and confirm.

Speech downloads use pinned revisions and SHA-256 checks. They are cached in
`ZING_HOME/models/speech`; doctor names the cache and reports available space.
By default, Zing's model workspace is `.zing` in your user home folder; Studio
puts projects under `zing-workspace` in the current folder. Set `ZING_HOME` to
a folder you own if you want the model cache elsewhere. Reserve space for
Python packages, models, your source clips, temporary renders and draft copies.
The model size is not the total installation size. There is no fixed total
because source length, output shape and draft count change it.

OCR reads text already visible in a reference. If doctor reports missing
caption OCR assets, the explicit download command in a checkout is
`uv run --frozen python -m myzing.study.caption_models --fetch`. This command
is the consent step; it does not ask a second time. It downloads pinned,
hash-checked assets. Speech and OCR are unnecessary for the silent generated
clip walkthrough. See [troubleshooting](TROUBLESHOOTING.md) for optional face
and font setup, and [privacy](PRIVACY.md) for the older study command's OCR caveat.

## Uninstall

For a pipx install, run `pipx uninstall myzing`. For uv tool, run
`uv tool uninstall myzing`. For a checkout, close Zing and delete its `.venv`
folder in your file browser, then delete the source folder when you no longer
need it. Keep any drafts you want first.

These steps do not remove model caches, source media or exported drafts. Review
your `ZING_HOME` or `zing-workspace` folder before deleting it. Existing Hugging
Face caches can be shared with other tools. Remove FFmpeg through the package
manager only if no other app needs it. Remove Python, pipx or uv separately if
you no longer use them.

## Command verification

The Windows source workflow and generated-media walkthrough were exercised for
REL2 with FFmpeg 8.1.2. Package installation and uninstallation were checked in
isolated tool directories using this checkout. PyPI commands remain unverified
until release. Windows system installers were not run: winget is unavailable in
the test shell. macOS and Linux instructions were checked against package docs
only in this pass. The repository CI config installs ffmpeg-full on macOS and
apt FFmpeg on Ubuntu; that config is not a new CI run for this patch.

Package references: [Microsoft's Gyan.FFmpeg manifest](https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Gyan/FFmpeg),
[Gyan build contents and Chocolatey commands](https://www.gyan.dev/ffmpeg/builds/),
[Homebrew ffmpeg-full](https://formulae.brew.sh/formula/ffmpeg-full).
