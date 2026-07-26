[CmdletBinding()]
param(
    [ValidateRange(1, 5)]
    [int]$Attempts = 3,

    [ValidateRange(0, 30)]
    [int]$DelaySeconds = 15,

    [string]$ChocolateyCommand = "choco"
)

$ErrorActionPreference = "Continue"

function Test-FfmpegCommands {
    $ffmpeg = Get-Command ffmpeg -CommandType Application -ErrorAction SilentlyContinue
    $ffprobe = Get-Command ffprobe -CommandType Application -ErrorAction SilentlyContinue
    return [bool]($ffmpeg -and $ffprobe)
}

if (Test-FfmpegCommands) {
    Write-Host "ffmpeg and ffprobe are already available"
    exit 0
}

for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    Write-Host "Chocolatey FFmpeg install attempt $attempt of $Attempts"
    $global:LASTEXITCODE = 1
    & $ChocolateyCommand install ffmpeg -y --no-progress
    $chocoExit = $LASTEXITCODE

    if (Test-FfmpegCommands) {
        Write-Host "ffmpeg and ffprobe are available after attempt $attempt"
        exit 0
    }

    Write-Warning (
        "Chocolatey attempt $attempt did not provide ffmpeg and ffprobe " +
        "(exit code $chocoExit)."
    )
    if ($attempt -lt $Attempts) {
        $delay = $DelaySeconds * $attempt
        Write-Host "Retrying after $delay second(s)"
        Start-Sleep -Seconds $delay
    }
}

Write-Error (
    "Chocolatey did not provide ffmpeg and ffprobe after $Attempts attempt(s)."
)
exit 1
