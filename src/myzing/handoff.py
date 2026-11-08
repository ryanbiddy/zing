"""Open a saved Uoink item in the clip factory."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

CONTRACT = "ryan.suite.handoff"
ERRORS = {
    "invalid_ref": "Use uoink://item/<id> or uoink:<id> for one saved item.",
    "uoink_unavailable": "Uoink could not resolve the item. Check that it is running and UOINK_TOKEN is set.",
    "media_unavailable": "The item's kept media is unavailable. Keep the video in Uoink and try again.",
    "download_needed": "Uoink did not keep this video. Zing can download it from {host}. Run again with --allow-download.",
    "download_failed": "Zing could not download this video. Check the source link and try again.",
    "project_exists": "That folder already holds another project. Choose a different --project folder.",
    "failed": "Zing could not open the hand-off. Check the arguments and project folder, then try again.",
}


class HandoffError(RuntimeError):
    def __init__(self, code: str, **values):
        self.code = code
        super().__init__(ERRORS[code].format(**values))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise HandoffError("failed")


def _project(ref: str, folder: Path | None, *, allow_download: bool = False, progress=None) -> tuple[Path, bool, bool]:
    from myzing import storage, uoink_bridge
    from myzing.factory import pipeline
    from myzing.project.references import _verified
    from myzing.study import ingest
    from myzing.urls import is_http_url

    result = uoink_bridge.resolve_kept_media(ref)
    code = result.get("code")
    if not result["ok"] and code not in {"not_kept", "missing"}:
        raise HandoffError("invalid_ref" if code == "invalid_ref" else "media_unavailable" if code in
                           {"not_found", "media_unavailable"} else "uoink_unavailable")
    data = result["data"] if result["ok"] else {}
    state = data.get("state", code)
    path = None
    if state == "available":
        media = data["media"]
        if uoink_bridge.redact(media["path"]) != media["path"]:
            raise HandoffError("failed")
        path = Path(media["path"])
        try:
            _verified(path, media["sha256"], media["byte_length"])
        except (OSError, ValueError):
            raise HandoffError("media_unavailable") from None
    elif state not in {"not_kept", "missing"}:
        raise HandoffError("media_unavailable")
    try:
        item = uoink_bridge.item_metadata(ref)
    except Exception:
        item = {}
    title = item.get("title", "").strip() if item.get("ok") else ""
    url = next((value for value in (data.get("source_url"), item.get("source_url") if item.get("ok") else None)
                if is_http_url(value)), "")
    host = urlsplit(url).hostname or ""
    if any(uoink_bridge.redact(value) != value for value in (title, url, host)):
        raise HandoffError("failed")
    if folder is None:
        home = storage.workspace_root() / "handoff"
        short = storage._hash8(ref.encode("utf-8"))
        folder = home / f"{storage._sanitize(title or uoink_bridge._item_id_from_ref(ref))}-{short}"
        for candidate in sorted(home.glob(f"*-{short}")):
            if candidate.is_dir() and not (candidate / "factory.json").is_file():
                raise HandoffError("project_exists")      # another launch is still downloading into it
            try:
                settings = pipeline._read(candidate / "factory.json", {})
            except (OSError, ValueError):
                continue
            if isinstance(settings, dict) and settings.get("uoink_ref") == ref:
                folder = candidate
                break
    folder = folder.expanduser().resolve()
    if uoink_bridge.redact(str(folder)) != str(folder):
        raise HandoffError("failed")
    if folder.exists():
        try:
            settings = pipeline._read(folder / "factory.json", {})
        except (OSError, ValueError):
            raise HandoffError("project_exists") from None
        if isinstance(settings, dict) and settings.get("uoink_ref") == ref:
            return folder, True, False
        if not folder.is_dir() or any(folder.iterdir()):
            raise HandoffError("project_exists")
    downloaded = path is None
    if downloaded:
        if not url:
            raise HandoffError("media_unavailable")
        if not allow_download:
            raise HandoffError("download_needed", host=host)
        created = False
        try:
            if not folder.exists():
                folder.mkdir(parents=True)
                created = True
            path = ingest.download(url, folder / "source", timeout=3600, progress=progress)
        except Exception:
            if created:
                shutil.rmtree(folder)
            raise HandoffError("download_failed") from None
    pipeline.init(folder, path, name=title or None, url=url, uoink_ref=ref)
    return folder, False, downloaded


def run(argv: list[str]) -> int:
    parser = Parser(prog="zing from-uoink", description=__doc__)
    parser.add_argument("ref", nargs="?", metavar="REF", help="a saved Uoink item reference")
    parser.add_argument("--probe", action="store_true", help="print the hand-off contract without contacting Uoink")
    parser.add_argument("--json", action="store_true", help="print one JSON line when the dashboard is ready")
    parser.add_argument("--no-open", action="store_true", help="leave the browser closed")
    parser.add_argument("--project", type=Path, metavar="DIR", help="the factory project folder")
    parser.add_argument("--allow-download", action="store_true", help="download the source video if Uoink did not keep it")
    parser.add_argument("--judge", choices=("host", "claude"), default="host", help="who answers the dashboard's prompts")
    parser.add_argument("--idle-minutes", type=int, default=60, help="stop after this many minutes without an HTTP request, at least 1")
    try:
        args = parser.parse_args(argv)
        if args.probe:
            from myzing.cli import _version
            print(json.dumps({"ok": True, "contract": CONTRACT, "version": 1, "service": "zing",
                              "service_version": _version(), "accepts": ["uoink.item/1"],
                              "needs": ["uoink.media.handoff/1"], "features": ["allow_download"]}), flush=True)
            return 0
        from myzing import uoink_bridge
        from myzing.factory.serve import serve
        from myzing.project.references import item_ref
        if args.idle_minutes < 1:
            raise HandoffError("failed")
        try:
            ref = item_ref(args.ref or "")
            if uoink_bridge.redact(ref) != ref:
                raise ValueError
        except ValueError:
            raise HandoffError("invalid_ref") from None
        reported = set()

        def progress(percent):
            whole = int(percent)
            if whole in reported:
                return
            reported.add(whole)
            line = (json.dumps({"contract": CONTRACT, "version": 1, "progress": "download", "percent": percent})
                    if args.json else f"Downloading {whole}%")
            print(line, file=sys.stderr, flush=True)

        project, reused, downloaded = _project(ref, args.project, allow_download=args.allow_download, progress=progress)

        def ready(page):
            if args.json:
                print(json.dumps({"ok": True, "contract": CONTRACT, "version": 1, "project": str(project),
                                  "page": page, "item_ref": ref, "reused": reused, "downloaded": downloaded}), flush=True)
            if not args.no_open:
                try:
                    webbrowser.open(page)
                except (OSError, webbrowser.Error):
                    pass

        serve(project, port=0, judge=args.judge, ready=ready, idle_seconds=args.idle_minutes * 60,
              say=lambda line: None if args.json else print(line, flush=True))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, HandoffError) else "failed"
        message = str(exc) if isinstance(exc, HandoffError) else ERRORS[code]
        result = {"ok": False, "contract": CONTRACT, "version": 1, "error": code, "message": message}
        print(json.dumps(result) if "--json" in argv else result["message"], flush=True)
        return 1
