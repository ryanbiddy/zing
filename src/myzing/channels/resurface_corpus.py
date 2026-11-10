"""Local episode metadata and timed cues for back-catalog search."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import sqlite3
import unicodedata
from bisect import bisect_right
from contextlib import closing
from datetime import date
from itertools import chain
from pathlib import Path, PureWindowsPath

from myzing.factory import source
from myzing.factory.pipeline import _write


def plain(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", html.unescape(text)).split())


def folded(text: str) -> str:
    return plain(text).casefold().replace("\u2019", "'").replace("\u2018", "'")


def names(values) -> list[str]:
    return list(dict.fromkeys(folded(value) for value in values if isinstance(value, str) and value.strip()))


def pattern(values) -> re.Pattern:
    terms = names(values)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(term) for term in terms) + r")(?!\w)" if terms else r"(?!)")


def _root(archive) -> Path:
    if str(archive).replace("\\", "/").startswith("//"):
        raise ValueError("archive must be a local folder")
    return Path(archive).expanduser().resolve()


def _transcript(root: Path, value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    if not value or path.is_absolute() or PureWindowsPath(value).drive or ":" in value:
        raise ValueError("transcript must be a path inside the archive")
    path = (root / path).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in (".srt", ".vtt", ".json"):
        raise ValueError("transcript must be an SRT, VTT or JSON file inside the archive")
    return path


def _manifest(root: Path):
    path = root / "manifest.json"
    if path.is_file():
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list):
            raise ValueError("manifest.json must contain a list")
        yield from rows
    else:
        with (root / "manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
            yield from csv.DictReader(stream)


def _episode(row, show: str) -> dict:
    if not isinstance(row, dict):
        raise ValueError("episode must be an object")
    for key in ("id", "title", "date"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"missing {key}")
    day = row["date"]
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError:
        raise ValueError("date must be the original publish date in YYYY-MM-DD") from None
    guests = row.get("guests") or []
    if isinstance(guests, str):
        guests = [guest.strip() for guest in guests.split(";") if guest.strip()]
    if not isinstance(guests, list) or any(not isinstance(guest, str) or not guest.strip() for guest in guests):
        raise ValueError("guests must be a list or names separated by semicolons")
    out = {key: plain(row[key]) for key in ("id", "title", "date")}
    for key in ("url", "description", "transcript", "media"):
        value = row.get(key) or ""
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        out[key] = plain(value) if key == "description" else value.strip()
    duration = row.get("duration")
    if duration in (None, ""):
        duration = None
    else:
        if isinstance(duration, bool):
            raise ValueError("duration must be a positive number of seconds")
        duration = float(duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration must be a positive number of seconds")
    return {**out, "guests": [plain(guest) for guest in guests], "show": show, "duration": duration}


def _fingerprint(path: Path) -> dict:
    stat = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}


def _cues(path: Path) -> tuple[list[dict], str]:
    segments, words = source.load_transcript(path)
    cues = []
    for cue in segments:
        if (not isinstance(cue, dict) or not isinstance(cue.get("text"), str)
                or any(type(cue.get(key)) not in (int, float) or not math.isfinite(cue[key]) for key in ("s", "e"))
                or not 0 <= cue["s"] < cue["e"]):
            raise ValueError("transcript has an invalid cue")
        text = plain(cue["text"])
        if text:
            cues.append({"s": cue["s"], "e": cue["e"], "text": text})
    if not cues:
        raise ValueError("transcript has no timed cues")
    return sorted(cues, key=lambda cue: (cue["s"], cue["e"])), "words" if words is not None else "captions"


def _coverage(cues: list[dict], duration: float | None) -> float:
    end, covered = 0.0, 0.0
    for cue in cues:
        stop = min(cue["e"], duration) if duration is not None else cue["e"]
        covered += max(0, stop - max(end, cue["s"]))
        end = max(end, stop)
    return covered


def _fts(db) -> bool:
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS cues_fts USING fts5("
                   "episode_id UNINDEXED, ordinal UNINDEXED, s UNINDEXED, e UNINDEXED, text UNINDEXED, terms)")
        return True
    except sqlite3.OperationalError as exc:
        if "no such module" not in str(exc).lower():
            raise
        return False


class Index:
    """Read episodes(), cues(id) and search(terms, episode_id=None) without fetching media."""

    def __init__(self, archive):
        self.archive = _root(archive)
        self.path = self.archive / ".zing" / "index.sqlite"
        with closing(self._connect()) as db:
            self.report = json.loads(db.execute("SELECT value FROM meta WHERE key = 'report'").fetchone()[0])
        self.backend = self.report["backend"]

    def _connect(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def _cue_path(self, ident):
        name = hashlib.sha256(ident.encode("utf-8")).hexdigest()
        return self.path.parent / "cues" / f"{name}.json"

    def episodes(self):
        with closing(self._connect()) as db:
            for row in db.execute("SELECT data FROM episodes ORDER BY id"):
                yield json.loads(row[0])

    def cues(self, episode_id: str) -> list[dict]:
        with closing(self._connect()) as db:
            if not db.execute("SELECT 1 FROM episodes WHERE id = ?", (episode_id,)).fetchone():
                return []
        return json.loads(self._cue_path(episode_id).read_text(encoding="utf-8"))["cues"]

    def search(self, terms, episode_id: str | None = None):
        terms = names([terms] if isinstance(terms, str) else terms)
        if not terms:
            return
        match = pattern(terms)
        tokens = sorted({token for term in terms for token in term.split() if re.search(r"\w", token)})
        query = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        if self.backend == "fts5" and query and all(re.search(r"\w", term) for term in terms):
            with closing(self._connect()) as db:
                sql = "SELECT DISTINCT episode_id FROM cues_fts WHERE cues_fts MATCH ?"
                args = [query]
                if episode_id is not None:
                    sql += " AND episode_id = ?"
                    args.append(episode_id)
                ids = [row[0] for row in db.execute(sql + " ORDER BY episode_id", args)]
        else:
            ids = [episode_id] if episode_id is not None else (episode["id"] for episode in self.episodes())
        for ident in ids:
            cues = self.cues(ident)
            offsets, parts, offset = [], [], 0
            for cue in cues:
                text = folded(cue["text"])
                offsets.append(offset)
                parts.append(text)
                offset += len(text) + 1
            hits = set()
            for found in match.finditer(" ".join(parts)):
                hits.update(range(bisect_right(offsets, found.start()) - 1, bisect_right(offsets, found.end() - 1)))
            for ordinal in sorted(hits):
                yield {"episode_id": ident, "cue": ordinal, **cues[ordinal]}


def build(archive, *, force_fallback: bool = False) -> Index:
    root = _root(archive)
    rows = iter(_manifest(root))
    missing = object()
    first = next(rows, missing)
    folder = root / ".zing"
    folder.mkdir(parents=True, exist_ok=True)
    seen, report = set(), {"indexed": 0, "unchanged": 0, "removed": 0, "errors": []}
    with closing(sqlite3.connect(folder / "index.sqlite")) as db:
        db.execute("CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        previous = db.execute("SELECT value FROM meta WHERE key = 'report'").fetchone()
        fts = not force_fallback and _fts(db)
        refresh = fts and (not previous or json.loads(previous[0])["backend"] != "fts5")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('report', ?)",
                   (json.dumps({**report, "backend": "json"}),))  # interrupted builds read the saved cues
        db.commit()
        if refresh:
            db.execute("DELETE FROM cues_fts")
        report["backend"] = "fts5" if fts else "json"
        for number, row in enumerate(chain([first], rows) if first is not missing else rows, 1):
            ident = row.get("id", "") if isinstance(row, dict) else ""
            try:
                episode = _episode(row, root.name)
                ident = episode["id"]
                if ident in seen:
                    raise ValueError("duplicate id")
            except (ValueError, TypeError, OverflowError) as exc:
                report["errors"].append(f"row {number} {ident!r}. {exc}")
                continue
            seen.add(ident)
            stored = db.execute("SELECT data FROM episodes WHERE id = ?", (ident,)).fetchone()
            old = json.loads(stored[0]) if stored else {}
            cue_path = folder / "cues" / (hashlib.sha256(ident.encode("utf-8")).hexdigest() + ".json")
            cues, fingerprint, timing, error = [], None, "captions", None
            try:
                path = _transcript(root, episode["transcript"])
                fingerprint = _fingerprint(path)
                same = old.get("fingerprint") == fingerprint and old.get("transcript") == episode["transcript"]
                if same and cue_path.is_file():
                    try:
                        cached = json.loads(cue_path.read_text(encoding="utf-8"))
                        cues, timing = cached["cues"], cached["timing_source"]
                        same = cached["fingerprint"] == fingerprint and not old.get("error")
                    except (OSError, ValueError, KeyError, TypeError):
                        same = False
                else:
                    same = False
                if not same:
                    cues, timing = _cues(path)
                    if _fingerprint(path) != fingerprint:
                        raise ValueError("transcript changed during the build. Run build again")
            except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as exc:
                same, cues, error = False, [], f"unreadable transcript. {exc}"
                report["errors"].append(f"row {number} {ident!r}. {error}")
            covered = _coverage(cues, episode["duration"])
            episode.update(fingerprint=fingerprint, timing_source=timing, cue_count=len(cues),
                           covered_seconds=covered, complete=bool(cues) and (episode["duration"] is None
                           or covered >= .8 * episode["duration"]), error=error)
            if not same:
                _write(cue_path, {"fingerprint": fingerprint, "timing_source": timing, "cues": cues})
            if fts and (not same or refresh):
                db.execute("DELETE FROM cues_fts WHERE episode_id = ?", (ident,))
                db.executemany("INSERT INTO cues_fts VALUES (?, ?, ?, ?, ?, ?)",
                               ((ident, i, cue["s"], cue["e"], cue["text"], folded(cue["text"]))
                                for i, cue in enumerate(cues)))
            db.execute("INSERT OR REPLACE INTO episodes VALUES (?, ?)", (ident, json.dumps(episode, ensure_ascii=False)))
            report["unchanged" if same else "indexed"] += 1
            db.commit()
        for (ident,) in db.execute("SELECT id FROM episodes").fetchall():
            if ident not in seen:
                db.execute("DELETE FROM episodes WHERE id = ?", (ident,))
                if fts:
                    db.execute("DELETE FROM cues_fts WHERE episode_id = ?", (ident,))
                report["removed"] += 1
        db.execute("INSERT OR REPLACE INTO meta VALUES ('report', ?)", (json.dumps(report),))
        db.commit()
    return Index(root)


def status(archive) -> dict:
    index = Index(archive)
    episodes = list(index.episodes())
    dates = [episode["date"] for episode in episodes]
    incomplete = [episode["id"] for episode in episodes if not episode["complete"]]
    return {"episodes": len(episodes), "cues": sum(episode["cue_count"] for episode in episodes),
            "complete": len(episodes) - len(incomplete), "incomplete": incomplete,
            "oldest": min(dates, default=None), "newest": max(dates, default=None),
            "backend": index.backend, "errors": index.report["errors"]}


def from_uoink(*args, **kwargs) -> Index:
    raise ValueError("Uoink cannot return timed cues yet")
