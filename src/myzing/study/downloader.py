"""yt-dlp Python adapter, run in the existing bounded fetch subprocess."""

import sys
import shutil


def runtime_options():
    runtime = next((name for name in ("deno", "node") if shutil.which(name)), None)
    return {"js_runtimes": {runtime: {}}} if runtime else {}


def main(args=None):
    # Keep yt-dlp's normal config/CLI parsing, then apply Zing's runtime choice
    # through its Python API. The parent owns timeout and cancellation.
    from yt_dlp import parse_options, YoutubeDL
    parsed = parse_options(sys.argv[1:] if args is None else args)
    options = {**parsed.ydl_opts, **runtime_options()}
    with YoutubeDL(options) as downloader:
        return downloader.download(parsed.urls)


if __name__ == "__main__":
    raise SystemExit(main())
