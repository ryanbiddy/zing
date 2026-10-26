# Releasing Zing

This checkout prepares `1.0.0rc1`. It does not publish anything. Every outward
step below is **Ryan only**. Once setup is complete, the release workflow
handles building, checking and uploading; Ryan starts the run and approves its
publish job. There is no stored PyPI token.

After this version is published on PyPI, a user with Python 3.10+ can install
the common features with one command:

```console
python -m pip install "myzing[mcp,render,memes]==1.0.0rc1"
```

Then run `zing studio`. For all optional Python features, use
`python -m pip install "myzing[all]==1.0.0rc1"`. FFmpeg is a separate system
requirement for video work. Models are separate, consented downloads. The
photo-meme path works without either. See [the README](../README.md) for prerequisites.

## One-time setup: Ryan only

1. **Ryan only:** In `ryanbiddy/zing` Settings > Environments, create `testpypi`
   and `pypi`. Give each a required reviewer of `ryanbiddy`, restrict deployments
   to `main`, and disable administrator bypass. Leave prevention of self-review
   off if Ryan both starts and approves runs. Confirm required-reviewer
   protection is available for the repository's plan. An environment name in
   YAML alone does not enforce approval. Do not run publication until these
   protections exist.
2. **Ryan only:** Sign in separately to TestPyPI and PyPI. If `myzing` already
   belongs to Ryan, open its Manage > Publishing page. Otherwise add a pending
   publisher under account Publishing. A pending publisher does not reserve
   the name. Use these exact values on each service:

   | Field | TestPyPI | PyPI |
   | --- | --- | --- |
   | Project name | `myzing` | `myzing` |
   | GitHub owner | `ryanbiddy` | `ryanbiddy` |
   | Repository | `zing` | `zing` |
   | Workflow filename | `release.yml` | `release.yml` |
   | Environment | `testpypi` | `pypi` |

   Use only the filename, without `.github/workflows/`. Save each publisher.
   Do not add a password or API-token secret. PyPI verifies GitHub's temporary
   OIDC identity. See the official [existing-project setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
   and [pending-project setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Local release checks

Keep `UOINK_URL=http://127.0.0.1:1` set for every command. On PowerShell:

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
uv sync --all-extras
uv build
uv run --frozen python packaging/audit_dist.py
uv run --frozen python packaging/release_notes.py --output zing-workspace/release-notes.md
uv venv zing-workspace/twine
uv pip install --python zing-workspace/twine/Scripts/python.exe twine
zing-workspace/twine/Scripts/python.exe -m twine check --strict dist/*
uv run --frozen python packaging/fresh_install_check.py --report zing-workspace/fresh-install.json
uv run --frozen pytest -ra
```

The fresh-install script creates two new venvs, installs the built wheel with
`mcp,render,memes` and `all`, and runs outside the source checkout. It checks
help, doctor, prompts, presets, the 37-tool MCP exchange and a generated-image
studio run. Product processes have networking blocked and empty model caches.
Dependency installation still needs the package index. Use `--work-dir` with a
new folder to retain both venvs, logs and images for review.

The JSON report saves each command, exit code, stderr tail and validation
failure as it happens. Exceptions include a full traceback. If pip explicitly
reports an unavailable optional dependency for `[all]`, the check tries each
optional extra in a separate venv and records the affected extras and pip
errors as `platform_limitations`. Available extras still run the full smoke
check. Core install or runtime failures, network failures and dependency
conflicts remain fatal. A report with `passed_with_platform_limitations` does
not prove that `[all]` installs on that platform. **Ryan only:** Review those
limitations before approving publication.

Release versions live in `pyproject.toml`, `src/myzing/__init__.py`, `uv.lock`,
`server.json`, the MCPB manifest and each prompt's `release_version`. Prompt
`version` fields track their individual contracts and stay independent. Update
the pinned installation examples and add a matching changelog heading. Run
`uv lock` after a version bump. The parity test catches mismatches. Historical
release links and recorded fixture versions are not current release pins.

## TestPyPI first: Ryan only

1. **Ryan only:** After review and merge, open Actions > Release > Run workflow.
   Select `main`, choose `testpypi`, leave `draft_release` off, and start the run.
2. **Ryan only:** Review the distribution artifacts, metadata check and all
   three fresh-install reports. Once they pass, approve the waiting `testpypi`
   deployment. This is the final manual approval that uploads the package.
3. **Ryan only:** Open the TestPyPI release page and check its files and
   description. Download the wheel from that release and test it in a new venv:

   ```console
   python -m pip install "./myzing-1.0.0rc1-py3-none-any.whl[mcp,render,memes]"
   zing --help
   zing studio
   ```

   This installs the wheel file you downloaded from TestPyPI; its
   dependencies come from regular PyPI, so TestPyPI need not contain them. Keep the safe
   UOINK_URL setting during verification.

## PyPI and GitHub: Ryan only

1. **Ryan only:** With the same reviewed commit still at `main`, start Release
   again with `target=pypi`. Optionally enable `draft_release`.
2. **Ryan only:** Check the run's commit, artifacts and three OS reports, then
   approve the `pypi` environment. The publish job downloads exactly the
   artifacts tested in that run. It cannot rebuild or replace them.
3. **Ryan only:** Verify the PyPI page and try the one-command install above in
   a clean venv. `1.0.0rc1` is a prerelease, so keep the explicit version pin.
4. **Ryan only:** If requested, the separate draft job attaches the wheel and
   sdist to `v1.0.0rc1` and uses only this version's changelog section. Open the
   draft in GitHub Releases, review the target commit and notes, keep the
   prerelease checkbox selected, then click Publish release when ready.
   If draft creation failed after PyPI succeeded, rerun only that failed job.
   Do not rerun a successful upload to reuse the same filenames.
5. **Ryan only:** If the optional job was left off, create a draft through
   GitHub Releases, choose tag `v1.0.0rc1` at the published commit, attach that
   run's distribution artifacts and paste its `release-notes` artifact. Review
   and publish it as a prerelease.

The workflow only accepts manual dispatch on `main`. Pushes and tags do not
publish. The RC workflow always creates GitHub drafts with the prerelease flag;
review that flag when preparing the final `1.0.0` release.

## MCP registry: Ryan only

**Ryan only:** After verifying PyPI, run the existing Actions > MCP Registry
workflow (`mcp-registry.yml`) on the published commit. Enter
`io.github.ryanbiddy/zing` as confirmation. It checks `server.json`, requires the
matching usable PyPI version and README verification marker, then publishes the
listing with GitHub OIDC. This is a separate outward action; Release does not
invoke it. See [the listing notes](DIRECTORY-SUBMISSIONS.md).

## Rollback: Ryan only

**Ryan only:** For a bad release, open the affected version in PyPI's project
management page and yank it with a clear reason. Do the same on TestPyPI if
needed. Do not delete and reupload the same version. Publish a corrected version
through the checks above, and update the GitHub release notes to direct users
to it. Yanking leaves the files available and exact version pins may still
install them; it does not remove an installed copy. See [PyPI's yanking guide](https://docs.pypi.org/project-management/yanking/).
