"""Raw-footage measurement mode (A-Q12, the measurement half of S3 Direct).

Raw recordings need different facts than published edits: where the dead
air is, where the filler words are, and which spans are repeated takes of
the same line. All three are deterministic measurements over data study
already produces (VAD speech spans + word timestamps) — judgment about
WHICH take is better stays with the AI.

Surfacing (until a schema slot is approved via NOTES): compact summary
lines in Breakdown.warnings plus a facts section in breakdown.md. The
structured results live on the internal RawResult for the CLI/S3 callers.

Honest limits: filler detection is a fixed lexicon over ASR output —
disfluencies whisper drops (stutters, partial words) are invisible here;
repeated-take detection needs ≥4-word chunks and reads word text only, so
re-phrasings below the similarity floor will not match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from myzing.schemas import Word

DEAD_AIR_MIN_S = 1.5
TAKE_GAP_S = 0.8              # word gap that splits raw speech into chunks
TAKE_MIN_WORDS = 4
TAKE_SIMILARITY = 0.75

FILLER_WORDS = {"um", "uh", "uhm", "erm", "hmm", "like", "literally"}
FILLER_BIGRAMS = {("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of")}


@dataclass
class DeadAir:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class RepeatedTake:
    first_start: float
    first_end: float
    second_start: float
    second_end: float
    similarity: float
    text: str                  # the (longer) take's words, for the report


@dataclass
class RawResult:
    dead_air: list[DeadAir] = field(default_factory=list)
    filler_counts: dict[str, int] = field(default_factory=dict)
    filler_locations: list[tuple[str, float]] = field(default_factory=list)
    repeated_takes: list[RepeatedTake] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def measure_raw(
    words: list[Word],
    speech_segments: list[tuple[float, float]] | None,
    duration: float,
) -> RawResult:
    result = RawResult()

    if speech_segments is None:
        result.warnings.append(
            "raw mode: dead-air measurement skipped (VAD unavailable)"
        )
    else:
        result.dead_air = dead_air_spans(speech_segments, duration)
        if result.dead_air:
            spans = ", ".join(
                f"{d.start:.1f}-{d.end:.1f}s" for d in result.dead_air[:8]
            )
            more = (
                f" (+{len(result.dead_air) - 8} more)"
                if len(result.dead_air) > 8 else ""
            )
            total = sum(d.duration for d in result.dead_air)
            result.warnings.append(
                f"raw: {len(result.dead_air)} dead-air span(s) totaling "
                f"{total:.1f}s — {spans}{more}"
            )

    if not words:
        result.warnings.append(
            "raw: filler and repeated-take measurement skipped (no transcript)"
        )
        return result

    result.filler_counts, result.filler_locations = find_fillers(words)
    if result.filler_counts:
        counts = ", ".join(
            f"{text}×{count}"
            for text, count in sorted(
                result.filler_counts.items(), key=lambda kv: -kv[1]
            )
        )
        result.warnings.append(
            f"raw: {sum(result.filler_counts.values())} filler word(s) — {counts}"
        )

    result.repeated_takes = find_repeated_takes(words)
    for take in result.repeated_takes:
        result.warnings.append(
            f"raw: repeated take (similarity {take.similarity:.2f}) — "
            f"{take.first_start:.1f}-{take.first_end:.1f}s vs "
            f"{take.second_start:.1f}-{take.second_end:.1f}s: "
            f'"{take.text[:80]}"'
        )
    return result


def dead_air_spans(
    speech_segments: list[tuple[float, float]], duration: float
) -> list[DeadAir]:
    """Gaps in VAD speech longer than DEAD_AIR_MIN_S, including leading
    and trailing silence — in a raw recording those are cuttable too."""
    spans: list[DeadAir] = []
    cursor = 0.0
    for start, end in sorted(speech_segments):
        if start - cursor >= DEAD_AIR_MIN_S:
            spans.append(DeadAir(round(cursor, 3), round(start, 3)))
        cursor = max(cursor, end)
    if duration > 0 and duration - cursor >= DEAD_AIR_MIN_S:
        spans.append(DeadAir(round(cursor, 3), round(duration, 3)))
    return spans


def _clean(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def find_fillers(
    words: list[Word],
) -> tuple[dict[str, int], list[tuple[str, float]]]:
    counts: dict[str, int] = {}
    locations: list[tuple[str, float]] = []
    cleaned = [(_clean(w.text), w) for w in words]
    index = 0
    while index < len(cleaned):
        text, word = cleaned[index]
        if index + 1 < len(cleaned):
            bigram = (text, cleaned[index + 1][0])
            if bigram in FILLER_BIGRAMS:
                label = " ".join(bigram)
                counts[label] = counts.get(label, 0) + 1
                locations.append((label, word.start))
                index += 2
                continue
        if text in FILLER_WORDS:
            counts[text] = counts.get(text, 0) + 1
            locations.append((text, word.start))
        index += 1
    return counts, locations


def _chunks(words: list[Word]) -> list[list[Word]]:
    """Split the transcript at natural pauses — in raw footage a re-take
    almost always follows a gap."""
    chunks: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current and word.start - current[-1].end > TAKE_GAP_S:
            chunks.append(current)
            current = []
        current.append(word)
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= TAKE_MIN_WORDS]


def find_repeated_takes(words: list[Word]) -> list[RepeatedTake]:
    chunks = _chunks(words)
    takes: list[RepeatedTake] = []
    for i in range(len(chunks)):
        text_i = " ".join(_clean(w.text) for w in chunks[i])
        for j in range(i + 1, len(chunks)):
            text_j = " ".join(_clean(w.text) for w in chunks[j])
            similarity = SequenceMatcher(None, text_i, text_j).ratio()
            if similarity >= TAKE_SIMILARITY:
                longer = chunks[i] if len(text_i) >= len(text_j) else chunks[j]
                takes.append(RepeatedTake(
                    first_start=round(chunks[i][0].start, 3),
                    first_end=round(chunks[i][-1].end, 3),
                    second_start=round(chunks[j][0].start, 3),
                    second_end=round(chunks[j][-1].end, 3),
                    similarity=round(similarity, 3),
                    text=" ".join(w.text.strip() for w in longer),
                ))
    return takes
