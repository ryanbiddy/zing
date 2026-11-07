"""Local videos and copy ready for a person to upload."""
from __future__ import annotations

import html
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from myzing.factory import campaign, render, tools
from myzing.factory.pipeline import _read, _write

from . import gate, queue, registry, youtube

TEXTS = ("youtube", "tiktok", "instagram", "x", "first_comment")
LABELS = {"youtube_title": "YouTube title", "youtube": "YouTube description", "tiktok": "TikTok",
          "instagram": "Instagram", "x": "X", "first_comment": "First comment"}


def _link(channel: dict) -> str:
    bases = {"youtube": "https://www.youtube.com/", "tiktok": "https://www.tiktok.com/@",
             "instagram": "https://www.instagram.com/", "x": "https://x.com/"}
    for platform in registry.HANDLES:
        handle = channel["handles"].get(platform, "").strip()
        if handle:
            if handle.startswith(("https://", "http://")):
                return handle
            return bases[platform] + quote(handle if platform == "youtube" else handle.lstrip("@"), safe="@")
    return ""


def _youtube(post: dict, project: Path, channel: dict, source_id: str | None) -> str:
    src = _read(project / "source.json", {})
    registered = registry.source(channel, source_id) if source_id else {}
    name = src.get("name") or registered.get("name")
    url = next((url for url in (src.get("url"), registered.get("url"))
                if url and url.startswith(("http://", "https://"))), "")
    text = post.get("youtube") or post.get("youtube_description") or post.get("instagram", "")
    credit = " ".join(v for v in ("Source:", name if name and name not in text else "", url) if v) if name or url else ""
    network, link = channel["network"], _link(channel)
    body = [text, "" if credit == "Source:" else credit, network.get("line", ""), network.get("url", ""),
            f"More from {channel['name']}: {link}" if link else ""]
    title = " ".join(post.get("youtube_title", "").splitlines())
    return title + "\n\n" + "\n".join(line for line in body if line) + "\n"


def _video(src: Path, dest: Path) -> str | None:
    try:
        program = tools.ffmpeg()
    except tools.FactoryError:
        shutil.copyfile(src, dest)
        return "FFmpeg is missing. Copied the video without remuxing."
    tools.run(program, "-v", "error", "-y", "-i", src, "-map", "0", "-c", "copy", "-movflags", "+faststart", dest,
              capture_output=True)
    return None


def _index(out: Path, channel: dict, rows: list[dict]) -> Path:
    folders = {p.parent.resolve() for p in out.glob("*/post.json") if not p.parent.name.startswith(".kit-")}
    folders.update(Path(r["kit"]).resolve() for r in rows if r.get("kit") and Path(r["kit"]).is_dir())
    kits = sorted(((folder, _read(folder / "post.json", {})) for folder in folders),
                  key=lambda item: datetime.fromisoformat(item[1]["slot"]).timestamp())
    cards = []
    for i, (folder, post) in enumerate(kits):
        try:
            video = quote(Path(os.path.relpath(folder / "video.mp4", out)).as_posix(), safe="/")
        except ValueError:
            video = (folder / "video.mp4").as_uri()
        texts = []
        title, _, description = (folder / "youtube.txt").read_text(encoding="utf-8").partition("\n\n")
        for field in ("youtube_title", *TEXTS):
            text = {"youtube_title": title, "youtube": description}.get(field)
            if text is None:
                text = (folder / f"{field}.txt").read_text(encoding="utf-8")
            label = LABELS[field]
            texts.append(f'<label for="copy-{i}-{field}">{label}</label>'
                         f'<textarea id="copy-{i}-{field}" readonly>{html.escape(text)}</textarea>'
                         f'<button type="button" data-copy="copy-{i}-{field}">Copy {label}</button>')
        rights = campaign.RIGHTS.get(post.get("rights"), "unknown")
        try:
            grant = registry.source(channel, post["source"])["rights"].get("grant", "") if post.get("source") else ""
        except registry.ChannelError:
            grant = ""
        when = datetime.fromisoformat(post["slot"]).strftime("%a %b %d, %I:%M %p (UTC%z)")
        cards.append(f'<article><h2>{html.escape(post.get("youtube_title", ""))}</h2>'
                     f'<p>Post at {html.escape(when)}</p><p>Rights: {html.escape(rights)}'
                     + (f'. Grant: {html.escape(grant)}' if grant else "") + "</p>"
                     f'<video controls preload="metadata" src="{html.escape(video, quote=True)}"></video>'
                     + "".join(texts) + '<p><label><input type="checkbox"> Posted</label></p></article>')
    page = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Post kits</title><style>
body{max-width:760px;margin:32px auto;padding:0 16px;font:16px/1.5 system-ui;color:#222;background:#fafafa}
article{margin:32px 0;padding:20px;border:1px solid #ccc;background:white}video{display:block;max-width:100%;max-height:480px}
textarea{display:block;box-sizing:border-box;width:100%;min-height:100px;font:inherit}button{margin:8px 0 20px;padding:8px}
label{display:block;margin-top:12px}h2{overflow-wrap:anywhere}
</style><body><h1>''' + html.escape(channel["name"]) + ''' post kits</h1>
<p>Upload these files yourself. The Posted boxes only change this page.</p>
''' + "".join(cards) + '''<script>
document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
  const text=document.getElementById(button.dataset.copy);
  try{await navigator.clipboard.writeText(text.value)}catch{ text.focus();text.select();document.execCommand('copy') }
}));
</script></body></html>'''
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def _stale(d: Path, folder: Path) -> bool:
    pack = _read(d.parent / "factory.json", {}).get("pack", "zing")
    pairs = ((d / f"clip{render.suffix('9x16', pack)}.mp4", folder / "video.mp4"),
             (d / "post.json", folder / "post.json"))
    return any(src.is_file() and (not dest.is_file() or src.stat().st_mtime_ns > dest.stat().st_mtime_ns)
               for src, dest in pairs)


def kit(slug: str, out: Path | None = None, *, now: datetime | None = None, stop=None) -> dict:
    channel = registry.load(slug)
    registry.require_running(slug)
    with youtube.lock():
        return _kit(channel, out, stop, now)


def _kit(channel: dict, out: Path | None, stop, now=None) -> dict:
    from .publish import _outbox
    slug = channel["slug"]
    out = Path(out).expanduser().resolve() if out is not None else registry.directory(slug) / "kits"
    out.mkdir(parents=True, exist_ok=True)
    rows = queue.read(slug)
    uploading = {r["id"] for r in _outbox(slug) if r["state"] == "uploading"}
    made, blocked, warnings = [], {}, []
    for row in rows:
        if stop and stop():
            break
        if row["status"] not in ("queued", "kit") or row["id"] in uploading:
            continue
        project = Path(row["project"])
        d = project / row["clip"]
        stamp = datetime.fromisoformat(row["slot"]).strftime("%Y-%m-%d-%H%M")
        folder = Path(row["kit"]) if row.get("kit") else out / f"{stamp}-{project.name}-{row['clip']}"
        stale = _stale(d, folder)
        if row["status"] == "kit" and not stale:
            continue
        result = gate.check(project, row["clip"], channel, now=now)
        if not result["publishable"]:
            blocked[row["id"]] = result["blockers"]
            if row["status"] == "kit":
                row["status"] = "queued"
                queue.write(slug, rows)
            continue
        required = ["video.mp4", "post.json", *[f"{field}.txt" for field in TEXTS]]
        if folder.exists() and not all((folder / name).is_file() for name in required):
            raise registry.ChannelError(f"kit folder is incomplete. Remove it and try again at {folder}")
        if not folder.exists() or stale:
            post = _read(d / "post.json", {})
            cfg = _read(project / "factory.json", {})
            with tempfile.TemporaryDirectory(prefix=".kit-", dir=folder.parent) as temp:
                tmp, previous = Path(temp) / "ready", Path(temp) / "previous"
                tmp.mkdir()
                warning = _video(d / f"clip{render.suffix('9x16', cfg.get('pack', 'zing'))}.mp4", tmp / "video.mp4")
                if warning:
                    warnings.append(f"{row['id']} {warning}")
                for field in TEXTS:
                    text = _youtube(post, project, channel, cfg.get("source")) if field == "youtube" else post.get(field, "")
                    (tmp / f"{field}.txt").write_text(text, encoding="utf-8")
                _write(tmp / "post.json", {**post, "slot": row["slot"], "channel": slug, "rights": cfg.get("rights", "unknown"),
                                            "source": cfg.get("source"), "gate": result})
                if folder.exists():
                    folder.rename(previous)
                try:
                    tmp.rename(folder)
                except OSError:
                    if previous.exists():
                        previous.rename(folder)
                    raise
        row.update(status="kit", kit=str(folder))
        queue.write(slug, rows)
        made.append(str(folder))
    index = _index(out, channel, rows)
    return {"made": len(made), "kits": made, "blocked": blocked, "warnings": warnings, "index": str(index)}
