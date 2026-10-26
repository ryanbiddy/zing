"""Fast, offline checks before any study or model loading."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from myzing.brief.api import load_brief
from myzing.brief.models import Brief
from myzing.project.probe import MEDIA_EXTENSIONS, MEDIA_DEMUXERS, parse_probe
from myzing.study import proc, speech_models
from myzing.urls import is_http_url

OPTIONAL = "Optional: OCR, color, audio tagging, font matching and automatic face analysis; unavailable measurements use disclosed fallbacks."


def probe(path):
    with path.open("rb") as stream:
        stream.read(1)
    result = proc.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file",
                       "-format_whitelist", MEDIA_DEMUXERS, "-enable_drefs", "0", "-use_absolute_path", "0",
                       "-show_streams", "-show_format", "-of", "json", str(path)], timeout=2)
    if result.returncode:
        raise ValueError(proc.tail(result.stderr))
    info = parse_probe(json.loads(result.stdout))
    if not info.duration or "no_video" in info.flags:
        raise ValueError("no readable video with a known duration")
    return info


def check(reference, clips, out, *, brief=None, answers=None, studio_options=None,
          ref_start=None, ref_end=None, reference_range=None, **options):
    problems, warnings = [], [OPTIONAL]
    from .api import validate
    try:
        validate(reference, clips, out, brief=brief, answers=answers, studio_options=studio_options,
                 ref_start=ref_start, ref_end=ref_end, reference_range=reference_range, **options)
    except (ValueError, OSError) as exc:
        problems.append(str(exc))
    selected = None
    try:
        selected = load_brief(brief) if brief else Brief.from_answers(answers) if answers is not None else load_brief(Path(out) / "brief.json")
    except (ValueError, OSError) as exc:
        message = f"Brief/target invalid: {exc}. Supply corrected --answers or --brief."
        problems.append(message)
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        problems.append("Missing " + ", ".join(missing) + "; install FFmpeg and put ffmpeg/ffprobe on PATH (zing doctor).")
    if selected and selected.framing == "reframe":
        if importlib.util.find_spec("cv2") is None:
            problems.append('Framing=reframe needs OpenCV; run python -m pip install "myzing[layout]", or choose framing=fit.')
        from myzing.layout.detector import model_path, verified_model
        if not verified_model(model_path()):
            problems.append("Face model required for framing=reframe; run zing layout fetch-model, or choose framing=fit.")
    paths = []
    directory = Path(clips).expanduser()
    try:
        paths = sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS) if directory.is_dir() else []
        if not paths:
            problems.append("No readable video clips; put supported video files in --clips.")
    except OSError as exc:
        problems.append(f"Clips unreadable: {exc}; restore read access to --clips.")
    local_reference = isinstance(reference, str) and not is_http_url(reference) and not reference.startswith("uoink:")
    ref = Path(reference).expanduser() if local_reference else None
    if ref is not None:
        paths.insert(0, ref)
    has_audio = False
    if "ffprobe" not in missing:
        for path in paths:
            try:
                info = probe(path)
                has_audio |= info.has_audio
                if path == ref:
                    from myzing.reference_range import validate_duration
                    validate_duration(info.duration, ref_start, ref_end, reference_range, limit=60)
            except (OSError, ValueError, proc.MediaError, subprocess.SubprocessError) as exc:
                problems.append(f"Unreadable/invalid media {path}: {exc}. Replace/remux the file or correct the reference range.")
    model = None
    if has_audio:
        try:
            model = speech_models.resolve_name((studio_options or {}).get("speech_model"))
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
    try:
        where = speech_models.existing_ancestor(Path(out).expanduser())
        if not where.is_dir():
            raise ValueError("output or an output parent is a file")
        # Three drafts plus intermediates: reserve 1 GB or 10 MB per target second.
        needed = max(1_000_000_000, int((selected.target_length_seconds if selected else 30) * 10_000_000))
        free = shutil.disk_usage(where).free
        if free < needed:
            problems.append(f"Output needs at least {needed / 1e9:.2f} GB free at {where}; {free / 1e9:.2f} GB available. Free space or change --out.")
    except (OSError, ValueError) as exc:
        problems.append(f"Output unavailable: {exc}; choose a writable --out folder.")
    return {"problems": list(dict.fromkeys(problems)), "warnings": warnings, "speech_model": model, "outputs": []}


def check_reference(path, choice=None):
    """URL/Uoink audio is known only after acquisition, still before study."""
    if probe(Path(path)).has_audio:
        speech_models.resolve_name(choice)
