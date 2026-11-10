# Releasing Zing

This checkout prepares `1.0.0rc1`. Ryan starts and approves every publication.
The release workflow builds and checks the files before either upload. It uses
Trusted Publishing with GitHub OIDC. No PyPI token is stored.

## Set up approvals and publishers first

1. In [GitHub Environments](https://github.com/ryanbiddy/zing/settings/environments),
   create `testpypi` and `pypi`. Set `ryanbiddy` as the required reviewer, restrict
   deployments to `main`, and turn administrator bypass off. Leave prevention
   of self-review off so Ryan can start and approve a run. Confirm these
   protections are available and enabled before publishing.
2. On [test.pypi.org](https://test.pypi.org/manage/account/publishing/), add a
   pending publisher for `myzing`. On [pypi.org](https://pypi.org/manage/project/myzing/settings/publishing/),
   add a publisher to the existing `myzing` project. Its `0.0.1` release is a
   placeholder. A pending publisher does not reserve a name.

   | Field | TestPyPI | PyPI |
   | --- | --- | --- |
   | Project | `myzing` | `myzing` |
   | GitHub owner | `ryanbiddy` | `ryanbiddy` |
   | Repository | `zing` | `zing` |
   | Workflow filename | `release.yml` | `release.yml` |
   | Environment | `testpypi` | `pypi` |

   Use the filename without `.github/workflows/`. See the official
   [existing-project guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
   and [pending-publisher guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Prepare the commit

1. Fold every `Unreleased` bullet into `1.0.0rc1`, preserve the groups, remove
   duplicates and extend the PR range through the last included PR. Leave
   `## Unreleased` empty. The notes check rejects unfolded bullets and short
   PR ranges.
2. Keep the version in `pyproject.toml`, `src/myzing/__init__.py`, `uv.lock`,
   `server.json`, the MCPB manifest and each prompt's `release_version` equal.
   Update pinned install examples and run `uv lock` after a version bump.
   Prompt `version` fields describe their contracts and stay independent.
3. Run the local checks with `UOINK_URL=http://127.0.0.1:1` set.

   ```powershell
   $env:UOINK_URL='http://127.0.0.1:1'
   uv sync --all-extras
   uv build
   uv run --frozen python packaging/audit_dist.py
   uv run --frozen python packaging/release_notes.py --output zing-workspace/release-notes.md
   uv venv zing-workspace/twine
   uv pip install --python zing-workspace/twine/Scripts/python.exe twine==7.0.0
   zing-workspace/twine/Scripts/python.exe -m twine check --strict dist/*
   uv run --frozen python packaging/fresh_install_check.py --report zing-workspace/fresh-install.json
   uv run --frozen pytest -ra
   ```

   Fresh installs check `mcp,render,memes` and `all` outside the checkout,
   with empty model caches and product networking blocked. They exercise
   help, doctor, prompts, presets, an image studio run and an MCP exchange
   that lists 44 MCP tools and calls `zing_status`. The
   [stdio check's tool list](../packaging/mcp_stdio_smoke.py) defines that count.
   Dependency installation still needs a package index. Reports retain
   commands, errors and tracebacks. Review any
   `passed_with_platform_limitations` result before approving. It does not
   prove that `[all]` installs on that platform.
4. Merge the reviewed changes. Check that `ci.yml` is green on the exact commit
   to release on `main`. An older green commit does not count. The workflow
   checks the latest push CI run for its SHA with a read-only GitHub token.

## Upload to TestPyPI, then PyPI

1. Open Actions > Release > Run workflow on `main`. Choose `testpypi` and
   leave `draft_release` off. Review the distributions, extracted notes and
   all 12 fresh-install reports across three OSes and Python 3.11–3.14.
   Approve the `testpypi` deployment when they pass.
2. Check the TestPyPI files and description. Download that release's wheel
   and test it in a new venv with the safe `UOINK_URL` setting.

   ```console
   python -m pip install "./myzing-1.0.0rc1-py3-none-any.whl[mcp,render,memes]"
   zing --help
   zing studio
   ```

   Dependencies come from regular PyPI. TestPyPI uploads are single-use per
   version. If the uploaded rc1 fails verification, fix it and bump to the
   next rc or a `.devN` version before uploading again. Deleting a release
   does not allow reuse. A failure before any upload can be retried.
3. With the same reviewed commit still at `main`, run Release with `target=pypi`.
   Optionally enable `draft_release`. The workflow accepts an earlier successful
   TestPyPI upload only for this exact commit, which also fixes the version.
   Otherwise it requires a successful `testpypi` job first. It never repeats
   a verified upload. Review the new reports and approve `pypi`. The publish
   job uploads the artifacts tested in that run without rebuilding them.
4. Verify the PyPI page and install in a clean venv.

   ```console
   python -m pip install "myzing[mcp,render,memes]==1.0.0rc1"
   zing studio
   ```

   For all optional Python features, use `myzing[all]==1.0.0rc1`. FFmpeg,
   models and Node sidecars need separate setup. Keep the version pin or use
   `--pre` for a release candidate. After rc1 is verified on PyPI, Ryan can
   yank the `0.0.1` placeholder so plain installs stop resolving to it.
5. Review the optional GitHub draft at `v1.0.0rc1`, its target commit, attached
   files and extracted notes. Keep it marked as a prerelease, then publish
   when ready. If draft creation failed after the upload, rerun only that
   failed job. If no draft was requested, create one from that run's
   distributions and `release-notes` artifact.

The workflow accepts only manual dispatch on `main`. Pushes and tags do not
publish. Review the prerelease flag again for the final `1.0.0` release.

## Publish the MCP listing

After verifying PyPI, Ryan can run Actions > MCP Registry (`mcp-registry.yml`)
on the published commit. Enter `io.github.ryanbiddy/zing` as confirmation.
It checks the listing, usable PyPI version and README verification marker,
then publishes with GitHub OIDC. Release does not invoke it. See
[the listing notes](DIRECTORY-SUBMISSIONS.md).

## Correct a bad release

Ryan can yank the affected version on PyPI or TestPyPI with a clear reason,
then publish a corrected version through these checks. Do not delete and
reupload the same version. Update GitHub's notes to point to the correction.
Yanking leaves files available to exact version pins and does not remove
installed copies. See [PyPI's yanking guide](https://docs.pypi.org/project-management/yanking/).
