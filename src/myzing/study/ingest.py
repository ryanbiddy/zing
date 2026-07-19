"""Media ingest: URL or local file -> media staged in the breakdown folder
plus an honest `VideoMeta`.

Storage (paths, slugs, layout) belongs to `myzing.storage` — this module
never invents paths. The one canonical media file per breakdown is
``media.<ext>`` (storage's `find_media` contract).

Measurement-critical policy (critique A#5, binding): every downstream
timestamp assumes a constant frame rate, so sources that are VFR (common on
TikTok/IG) or in codecs the measurement stack can't decode reliably are
normalized to CFR H.264 once, here, and the normalized file REPLACES the
staged media. The re-encode is recorded as a warning — we say what we did
to the evidence.

VFR detection is two-tier (F-06): the cheap avg-vs-declared fps gate keeps
catching gross VFR, but locally-VFR H.264 (bursty frame drops on
phone/TikTok sources) can sit well under that 2% while frame-index
timestamps drift past the eval's own ±0.15s cut budget. So h264 sources
that pass the cheap gate get a per-frame PTS delta scan (ffprobe packet
timestamps, demux-only — no decode): normalize when delta variation
exceeds ``_PTS_DELTA_CV_MAX`` or worst frame-index drift exceeds
``_PTS_DRIFT_BUDGET_S``; when normalization is skipped despite measurable
drift — or the scan itself cannot run — the residual risk is recorded as
an explicit warning, never assumed away.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from myzing import doctor, storage
from myzing.schemas import VideoMeta

from . import proc
from .proc import MediaError

# Prefer H.264 mp4 from yt-dlp: it is the one container/codec combo that
# every stage (OpenCV on Windows included) decodes with reliable timestamps.
YTDLP_FORMAT = "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"

_SAFE_VCODECS = {"h264"}
_VFR_TOLERANCE = 0.02  # relative avg-vs-declared fps disagreement (cheap gate)

# F-06 PTS-delta scan thresholds (documented, deliberate):
# - _PTS_DELTA_CV_MAX: normalize when the coefficient of variation
#   (stddev/mean) of per-frame PTS deltas exceeds 5%. Clean CFR is ~0%;
#   millisecond-timebase rounding jitter (33/34ms at 29.97fps) stays ~1.5-3%;
#   real dropped/duplicated frames blow past 5% on short-form lengths.
# - _PTS_DRIFT_BUDGET_S: normalize when the worst deviation between true PTS
#   and the constant-rate timeline (frame_index/fps, what shots/OCR assume)
#   exceeds the eval's own ±0.15s cut tolerance — on long clips a few drops
#   keep CV low while drift quietly breaks the budget.
# - _PTS_DRIFT_WARN_S: below both normalize thresholds but drifting more
#   than a third of the budget, we skip normalization AND say so — an
#   explicit residual-risk warning instead of silence.
_PTS_DELTA_CV_MAX = 0.05
_PTS_DRIFT_BUDGET_S = 0.15
_PTS_DRIFT_WARN_S = 0.05
_PTS_MIN_SAMPLES = 10  # fewer usable timestamps than this = no verdict


@dataclass
class IngestResult:
    slug: str
    meta: VideoMeta
    media_path: Path              # absolute path to the file measurements run on
    breakdown_dir: Path
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


def is_url(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def detect_platform(source: str) -> str:
    if not is_url(source):
        return "file"
    host = urlparse(source).netloc.lower()
    if "tiktok" in host:
        return "tiktok"
    if "instagram" in host or "instagr.am" in host:
        return "instagram"
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "t.co"):
        return "x"
    return "url"


def ingest(
    source: str, kept_media: str | Path | None = None
) -> IngestResult:
    """Workspace routing is storage's job (ContextVar pin via
    use_workspace); ingest never carries roots around.

    ``kept_media`` (A-S6): a locally kept copy of a URL source (uoink
    keep_media). When usable it is staged with a sha256 anchor and ZERO
    network fetch; when missing, unreadable, or failing the probe, the
    fallback to a normal fetch is named in warnings — never silent.
    """
    warnings: list[str] = []
    provenance: dict[str, Any] = {}
    slug = storage.slug_for(source)
    dest = storage.breakdown_dir(slug)
    dest.mkdir(parents=True, exist_ok=True)

    probed = None
    if is_url(source):
        media = None
        info = {}
        if kept_media is not None:
            media = _stage_kept(kept_media, slug, warnings, provenance)
        if media is not None:
            try:
                probed = probe(media)
            except MediaError as exc:
                warnings.append(
                    f"kept media failed probe ({exc}) — falling back to fetch"
                )
                provenance.clear()
                # The staged copy is the same bad bytes — remove it so the
                # fetch fallback cannot "reuse" it as existing media.
                try:
                    media.unlink()
                except OSError:
                    pass
                media = None
        if media is None:
            media = _fetch(source, slug, dest, warnings)
            info = _read_info_json(dest)
    else:
        if kept_media is not None:
            warnings.append(
                "kept_media ignored: source is already a local file"
            )
        media = _stage_local(source, slug)
        info = {}

    if probed is None:
        probed = probe(media)
    vstream = _video_stream(probed, media)

    need, why = _needs_normalize(vstream)
    if not need:
        # Cheap gates passed — verify the CFR assumption against real
        # per-frame PTS before trusting frame-index timestamps (F-06).
        need, why = _check_frame_timing(media, warnings)
    if need:
        warnings.append(why)
        target_fps = _fps(vstream.get("avg_frame_rate", "0/0")) or 30.0
        media = _normalize(media, target_fps)
        probed = probe(media)
        vstream = _video_stream(probed, media)

    if _first_stream(probed, "audio") is None:
        warnings.append(
            "no audio stream: transcription and audio measurements will be skipped"
        )

    duration = _duration(probed, vstream)
    meta = VideoMeta(
        source_url=source if is_url(source) else str(Path(source).resolve()),
        platform=detect_platform(source),
        author=str(info.get("uploader") or info.get("channel") or ""),
        title=str(info.get("title") or ("" if is_url(source) else Path(source).stem)),
        duration=round(duration, 3),
        width=int(vstream.get("width", 0) or 0),
        height=int(vstream.get("height", 0) or 0),
        fps=round(_fps(vstream.get("avg_frame_rate", "0/0")), 3),
        # Relative to the breakdown folder (contract rule): the folder
        # survives being moved; storage resolves to absolute at load.
        media_path=media.name,
    )
    return IngestResult(
        slug=slug, meta=meta, media_path=media, breakdown_dir=dest,
        warnings=warnings, provenance=provenance,
    )


# -- fetch / stage ----------------------------------------------------------

def _stage_kept(
    kept: str | Path,
    slug: str,
    warnings: list[str],
    provenance: dict[str, Any],
) -> Path | None:
    """A-S6: stage an already-kept media file instead of refetching.

    Returns the staged path, or None (with a named warning) when the
    kept file cannot be used — the caller then fetches normally.
    """
    src = Path(kept)
    if not src.is_file():
        warnings.append(
            f"kept media unavailable ({src}) — falling back to fetch"
        )
        return None
    try:
        digest = hashlib.sha256()
        with src.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        target = storage.media_target(slug, src.suffix or ".mp4")
        if not (
            target.exists() and target.stat().st_size == src.stat().st_size
        ):
            shutil.copy2(src, target)
    except OSError as exc:
        warnings.append(
            f"kept media unreadable ({exc}) — falling back to fetch"
        )
        return None
    provenance["media_source"] = "kept-media"
    provenance["kept_media_path"] = str(src.resolve())
    provenance["kept_media_sha256"] = digest.hexdigest()
    return target

def _fetch(url: str, slug: str, dest: Path, warnings: list[str]) -> Path:
    existing = storage.find_media(slug)
    if existing is not None:
        warnings.append(f"reusing already-downloaded media: {existing.name}")
        return existing
    # S5 gate defect D-11 (routed Lane B; Lane A please re-review): run
    # EXACTLY what doctor probes — the literal "yt-dlp" binary here made
    # module-only envs pass doctor and then fail every fetch.
    ytdlp = doctor.resolve_ytdlp_argv()
    if ytdlp is None:
        raise MediaError(
            "yt-dlp is not installed (no binary on PATH, module not "
            'importable) — python -m pip install "myzing[study]"'
        )
    cmd = [
        *ytdlp,
        "--no-playlist",
        "-f", YTDLP_FORMAT,
        "--merge-output-format", "mp4",
        "--write-info-json",
        "-o", "media.%(ext)s",
        "-P", str(dest),
        url,
    ]
    res = proc.run(cmd, timeout=600)
    if res.returncode != 0:
        raise MediaError(
            f"yt-dlp could not fetch {url} (exit {res.returncode}):\n"
            f"{proc.tail(res.stderr)}"
        )
    media = storage.find_media(slug)
    if media is None:
        raise MediaError(
            f"yt-dlp exited 0 but no media file landed in {dest} — "
            "cannot measure a video we do not have"
        )
    return media


def _stage_local(path_str: str, slug: str) -> Path:
    src = Path(path_str)
    if not src.is_file():
        raise MediaError(f"no such file: {src}")
    target = storage.media_target(slug, src.suffix)
    if not (target.exists() and target.stat().st_size == src.stat().st_size):
        shutil.copy2(src, target)
    return target


def _read_info_json(dest: Path) -> dict:
    path = dest / "media.info.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# -- probe / normalize ------------------------------------------------------

def probe(path: Path) -> dict:
    res = proc.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)]
    )
    if res.returncode != 0:
        raise MediaError(f"ffprobe failed on {path.name}:\n{proc.tail(res.stderr)}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise MediaError(f"ffprobe produced unparseable output for {path.name}") from e


def _first_stream(probed: dict, kind: str) -> dict | None:
    for stream in probed.get("streams", []):
        if stream.get("codec_type") == kind:
            return stream
    return None


def _video_stream(probed: dict, media: Path) -> dict:
    vstream = _first_stream(probed, "video")
    if vstream is None:
        raise MediaError(f"{media.name} has no video stream — nothing to study")
    return vstream


def _needs_normalize(vstream: dict) -> tuple[bool, str]:
    codec = str(vstream.get("codec_name", ""))
    if codec not in _SAFE_VCODECS:
        return True, (
            f"source codec '{codec}' is not reliable for frame-accurate "
            "measurement here; re-encoded to H.264"
        )
    avg = _fps(vstream.get("avg_frame_rate", "0/0"))
    declared = _fps(vstream.get("r_frame_rate", "0/0"))
    if avg > 0 and declared > 0 and abs(declared - avg) / avg > _VFR_TOLERANCE:
        return True, (
            f"variable frame rate detected (average {avg:.2f} fps vs declared "
            f"{declared:.2f}); normalized to constant frame rate so timestamps "
            "stay trustworthy"
        )
    return False, ""


def _check_frame_timing(media: Path, warnings: list[str]) -> tuple[bool, str]:
    """F-06: per-frame PTS delta scan for locally-VFR sources the cheap
    avg-vs-declared gate cannot see. Returns (normalize?, reason) and
    appends residual-risk warnings itself when normalization is skipped
    but the CFR assumption is not fully verified."""
    pts, problem = _read_packet_pts(media)
    if problem:
        warnings.append(
            f"could not verify constant frame timing ({problem}); timestamps "
            "assume CFR — residual risk: a variable-frame-rate source would "
            "drift frame-index timestamps beyond the ±0.15s eval budget "
            "without detection"
        )
        return False, ""
    cv, drift = _pts_delta_stats(pts)
    if cv > _PTS_DELTA_CV_MAX or drift > _PTS_DRIFT_BUDGET_S:
        return True, (
            f"variable frame timing detected (per-frame PTS delta variation "
            f"{cv:.1%}, worst frame-index drift {drift:.3f}s vs thresholds "
            f"{_PTS_DELTA_CV_MAX:.0%} / {_PTS_DRIFT_BUDGET_S:.2f}s); "
            "normalized to constant frame rate so timestamps stay trustworthy"
        )
    if drift > _PTS_DRIFT_WARN_S:
        warnings.append(
            f"frame-timing jitter detected (per-frame PTS delta variation "
            f"{cv:.1%}, worst frame-index drift {drift:.3f}s) is under the "
            "normalization thresholds, so normalization was skipped — "
            f"residual risk: frame-index timestamps may sit up to "
            f"{drift:.3f}s off true PTS (eval cut budget is ±0.15s)"
        )
    return False, ""


def _read_packet_pts(media: Path) -> tuple[list[float], str]:
    """All video packet presentation timestamps, sorted into presentation
    order (demux-only; no decode). Returns ([], problem) when no verdict
    is possible — the caller must warn, not guess."""
    res = proc.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(media)],
        timeout=300,
    )
    if res.returncode != 0:
        return [], f"ffprobe packet scan failed: {proc.tail(res.stderr)}"
    pts: list[float] = []
    for line in res.stdout.splitlines():
        token = line.strip().strip(",")
        if not token or token.upper() == "N/A":
            continue
        try:
            pts.append(float(token))
        except ValueError:
            continue
    if len(pts) < _PTS_MIN_SAMPLES:
        return [], f"only {len(pts)} usable packet timestamp(s)"
    # Packets arrive in decode order; B-frames land out of presentation
    # order. Sort so reordering is never mistaken for VFR.
    pts.sort()
    return pts, ""


def _pts_delta_stats(pts: list[float]) -> tuple[float, float]:
    """(cv, worst_drift) for sorted presentation timestamps.

    cv: coefficient of variation (stddev/mean) of per-frame PTS deltas —
    0 for clean CFR, small for timebase rounding, large for real VFR.
    worst_drift: max |true PTS - constant-rate timeline| where the
    constant-rate timeline steps by the median delta (the nominal frame
    duration downstream frame-index math assumes)."""
    deltas = [b - a for a, b in zip(pts, pts[1:])]
    mean = sum(deltas) / len(deltas)
    if mean <= 0:
        return float("inf"), float("inf")  # duplicate PTS everywhere: broken
    variance = sum((d - mean) ** 2 for d in deltas) / len(deltas)
    cv = math.sqrt(variance) / mean
    step = statistics.median(deltas)
    drift = max(abs(t - (pts[0] + i * step)) for i, t in enumerate(pts))
    return cv, drift


def _normalize(media: Path, fps: float) -> Path:
    """Re-encode to CFR H.264 and replace the staged media in place, so
    ``media.mp4`` stays the single canonical file storage knows about.
    The original is refetchable (URL) or still at the user's source path
    (local copy), so nothing irreplaceable is discarded."""
    tmp = media.with_name("media_normalizing.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(media),
        "-fps_mode", "cfr", "-r", f"{fps:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        str(tmp),
    ]
    res = proc.run(cmd, timeout=900)
    if res.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise MediaError(
            f"ffmpeg failed to normalize {media.name} (exit {res.returncode}):\n"
            f"{proc.tail(res.stderr)}"
        )
    if not tmp.is_file():
        raise MediaError("ffmpeg exited 0 but produced no normalized file")
    final = media.with_name("media.mp4")
    if media != final:
        media.unlink()
    tmp.replace(final)
    return final


# -- parsing helpers --------------------------------------------------------

def _fps(rate: str) -> float:
    """Parse ffprobe rational rates like '30000/1001'; 0.0 when unknown."""
    num, _, den = str(rate).partition("/")
    try:
        n = float(num)
        d = float(den) if den else 1.0
    except ValueError:
        return 0.0
    return n / d if d else 0.0


def _duration(probed: dict, vstream: dict) -> float:
    for holder in (probed.get("format", {}), vstream):
        raw = holder.get("duration")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return 0.0
