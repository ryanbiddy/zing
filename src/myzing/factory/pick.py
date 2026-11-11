"""Vision pick: every candidate for every visual request on one labeled sheet; the judge picks the best or none."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .tools import data_path, ffmpeg, run
from .visuals import nsfw

TW, TH, BAND = 360, 240, 64
VIDEO = (".mp4", ".mov", ".webm", ".gif")
MODE_RULES = {
    "context": "Pick what a sharp human editor would cut to: the most relevant, specific and visually striking candidate "
               "for what the speaker is saying at that moment. Prefer modern, clear, well-lit, uncluttered images; real "
               "footage of the exact thing named beats a loosely related or archival picture.",
    "documentary": "Pick what a documentary editor would cut to: an authentic period photograph, painting, document, map or "
                   "portrait of exactly what is being said, shot or made at the time (for today's news, a recent photograph "
                   "or the news article itself). Black and white is fine (the clip is graded). "
                   "Reject modern stock, logos, clip art, illustrations made to look old, and anything only loosely related.",
    "fun": "Pick what makes the moment more fun to watch while still clearly about what's being said: a playful, literal "
           "or delightfully absurd visual punchline. It must never mock the speaker or a real person, and must still "
           "make sense to a viewer.",
}


def _thumb(path: Path):
    from PIL import Image
    p = Path(path)
    if p.suffix.lower() in VIDEO:
        still = p.with_suffix(".pick.jpg")
        for seek in (["-ss", "1.5"], []):
            if not still.exists():
                run(ffmpeg(), "-v", "error", "-y", *seek, "-i", str(p), "-frames:v", "1", str(still), check=False)
        p = still
    im = Image.open(p).convert("RGB")
    im.thumbnail((TW, TH))
    canvas = Image.new("RGB", (TW, TH), (20, 24, 36))
    canvas.paste(im, ((TW - im.width) // 2, (TH - im.height) // 2))
    return canvas


def title_label(c: dict) -> str:
    return " ".join((c.get("title") or "").split())[:40]


def sheet(visdir: Path, requests: list[dict], manifest: dict) -> Path | None:
    from PIL import Image, ImageDraw, ImageFont
    rows = [r for r in requests if any(not nsfw(c) for c in (manifest.get(r["id"]) or []))]
    if not rows:
        return None
    cols = max(len(manifest[r["id"]]) for r in rows)
    img = Image.new("RGB", (220 + cols * (TW + 12), len(rows) * (TH + BAND + 16) + 10), (8, 10, 18))
    dr = ImageDraw.Draw(img)
    font = str(Path(str(data_path())).parent / "fonts" / "ZingCaption-800.ttf")
    f_big, f_small = ImageFont.truetype(font, 30), ImageFont.truetype(font, 17)
    y = 10
    for r in rows:
        dr.text((12, y + 6), r["id"], fill=(255, 210, 63), font=f_big)
        dr.text((220, y + 4), (r.get("query", "") + "  |  says: " + r.get("context", ""))[:150], fill=(230, 233, 240), font=f_small)
        for i, c in enumerate(manifest[r["id"]]):
            if nsfw(c):
                continue
            x = 220 + i * (TW + 12)
            try:
                img.paste(_thumb(visdir / c["path"]), (x, y + BAND - 26))
            except Exception:
                continue
            dr.rectangle([x, y + BAND - 26, x + 110, y + BAND + 2], fill=(255, 210, 63))
            dr.text((x + 8, y + BAND - 25), f"{i + 1}" + ("  VIDEO" if c.get("media_type") == "video" else ""),
                    fill=(8, 18, 51), font=f_small)
            title = title_label(c)
            while dr.textbbox((0, 0), title, font=f_small)[2] > TW:
                title = title[:-1]
            dr.text((x, y + BAND + TH - 20), title, fill=(230, 233, 240), font=f_small)
        y += TH + BAND + 16
    out = visdir / "pick_sheet.jpg"
    img.save(out, quality=88)
    return out


REJECT = """- doesn't show what's being talked about, or shows the wrong subject;
- names or shows a particular place, police force, team or company the speaker isn't talking about (lettering on a car, a sign or a jersey counts);
- shows nudity, sexual content, or anything not safe for a general audience;
- has burned-in text, titles, captions, watermarks or a logo bug that would clash with our captions;
- is blurry, tiny, a scan of a document, a diagram, a map, or visual clutter;
- is a dull archival picture when the moment calls for something vivid.
"""
REJECT_DOC = """- doesn't show what's being talked about, or shows the wrong subject, place or period;
- names or shows a particular place, police force, team or company the speaker isn't talking about (lettering on a car, a sign or a jersey counts);
- shows nudity, sexual content, or anything not safe for a general audience;
- has a watermark or a logo bug;
- is blurry, tiny or visual clutter. A period map, letter, register or newspaper of the exact subject is evidence:
  keep it, and so is a screenshot of a news article about the story.
"""


def prompt(sheet_path: Path, mode: str, sensitive_reason: str | None) -> str:
    sensitive = ("THIS CLIP IS ON A SENSITIVE SUBJECT (" + sensitive_reason + "). Choose none rather than anything that "
                 "depicts violence, suffering or people being harmed, anything festive or upbeat, or anything only loosely "
                 "related. Restrained, documentary, dignified images only.") if sensitive_reason is not None else ""
    return f"""Read the image at {sheet_path.resolve().as_posix()}. It is a contact sheet for a social video clip cut from a podcast.
Each row is one moment that needs a visual: the left label is its id, the top line is the search query and what the speaker says there,
and the numbered tiles (1, 2, 3, ...) are the candidates found. Titles appear below the tiles. Some tiles are stills from a video and are marked VIDEO.

{MODE_RULES["context" if sensitive and mode != "documentary" else mode]}

Reject a candidate (and choose none for the row if nothing passes) when it:
{REJECT_DOC if mode == "documentary" else REJECT}Prefer VIDEO when it is as relevant as the best still.
{sensitive}

Reply with ONLY a JSON object, no prose and no code fence, mapping every row id to
{{"pick": <tile number or null>, "why": "<max 12 words>"}}."""


def picks_from(answer: dict) -> dict[str, dict]:
    out = {}
    for rid, v in answer.items():
        n = v.get("pick") if isinstance(v, dict) else v
        idx = int(n) - 1 if isinstance(n, (int, float)) or (isinstance(n, str) and n.isdigit()) else None
        out[rid] = {"pick": idx, "why": v.get("why", "") if isinstance(v, dict) else ""}
    return out


def chosen(visdir: Path, requests: list[dict], manifest: dict, picks: dict[str, dict]) -> dict[str, dict]:
    """The picked candidate per request (top unflagged choice when the judge skipped a row), with credit and fit."""
    found = {}
    for rid, cands in manifest.items():
        if rid in picks:
            k = picks[rid]["pick"]
            if k is None or not 0 <= k < len(cands) or nsfw(cands[k]):
                continue                                 # a flagged pick shows nothing, not a tile nobody vetted
            cands = [cands[k]]
        else:
            cands = [c for c in (cands or []) if not c.get("places_off")]
        c = next((c for c in (cands or []) if not nsfw(c)), None)
        if c is None:
            continue
        credit = c.get("attribution") or c.get("creator") or c.get("source") or ""
        lic = c.get("license") or ""
        text = c.get("credit_text") or (f"{credit} · {lic}" if credit and lic else credit or lic)
        if c.get("rights") == "attribution" and len(text) > 80 and lic:
            room = max(0, 77 - len(lic))
            title = c.get("title") or ""
            credit = credit or text.split(lic, 1)[0].rstrip(" ·,")
            if title and credit and room > 3:
                credit = credit[:room // 2]
                credit = f"{title[:room - len(credit) - 3].rstrip()} / {credit}"
            text = f"{credit[:room].rstrip()} · {lic}" if room and credit else lic
        else:
            text = text[:80]
        kind = next((r.get("kind") for r in requests if r.get("id") == rid), "")
        whole = kind == "logo" or c.get("source") in ("screenshot", "scroll", "ogimage")   # never crop a logo or a page
        found[rid] = {"path": str(visdir / c["path"]), "credit": text,
                      "rights": c.get("rights", "unknown"), **({"fit": "contain"} if whole else {})}
    return found
