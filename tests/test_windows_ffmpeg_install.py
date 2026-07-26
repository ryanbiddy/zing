"""Windows CI must reject Chocolatey's false-success package installs."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "packaging" / "install_ffmpeg_windows.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
CAN_RUN_WINDOWS_MUTATION = os.name == "nt" and POWERSHELL is not None


def test_windows_jobs_share_the_verified_installer():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count(
        "pwsh -NoProfile -File packaging/install_ffmpeg_windows.ps1"
    ) == 2
    assert "run: choco install ffmpeg" not in workflow


@pytest.mark.skipif(
    not CAN_RUN_WINDOWS_MUTATION,
    reason="Windows PowerShell mutation",
)
@pytest.mark.parametrize(
    ("succeed_on", "expected_exit", "expected_attempts"),
    [
        (2, 0, 2),
        (0, 1, 2),
    ],
)
def test_installer_retries_false_success_and_requires_commands(
    tmp_path: Path,
    succeed_on: int,
    expected_exit: int,
    expected_attempts: int,
):
    fake_choco = tmp_path / "fake-choco.ps1"
    counter = tmp_path / "attempts.txt"
    fake_choco.write_text(
        """
$count = if (Test-Path $env:FAKE_CHOCO_COUNTER) {
    [int](Get-Content $env:FAKE_CHOCO_COUNTER)
} else {
    0
}
$count += 1
Set-Content -Path $env:FAKE_CHOCO_COUNTER -Value $count
if ([int]$env:FAKE_CHOCO_SUCCEED_ON -gt 0 -and
    $count -ge [int]$env:FAKE_CHOCO_SUCCEED_ON) {
    Set-Content -Path (Join-Path $PSScriptRoot "ffmpeg.cmd") -Value "@exit /b 0"
    Set-Content -Path (Join-Path $PSScriptRoot "ffprobe.cmd") -Value "@exit /b 0"
}
exit 0
""".lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)
    env["FAKE_CHOCO_COUNTER"] = str(counter)
    env["FAKE_CHOCO_SUCCEED_ON"] = str(succeed_on)

    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-File",
            str(INSTALLER),
            "-Attempts",
            "2",
            "-DelaySeconds",
            "0",
            "-ChocolateyCommand",
            str(fake_choco),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == expected_exit, result.stdout + result.stderr
    assert int(counter.read_text(encoding="utf-8").strip()) == expected_attempts
    if expected_exit == 0:
        assert "available after attempt 2" in result.stdout
    else:
        error = " ".join(result.stderr.split())
        assert "did not provide ffmpeg and ffprobe" in error
