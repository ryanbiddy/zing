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

# "like" is the one filler candidate that is ALSO an ordinary verb,
# preposition and comparative. Measured on a real 62-min interview
# (handoff/research/RAW-FILLER-PRECISION-2026-07-20.md), ~25% of raw
# "like" hits were non-filler uses. These guards skip only the
# unambiguous ones — a word BEFORE "like" that makes it a verb or
# preposition, or a word AFTER it that makes it a comparative. Genuine
# filler and quotative "like" ("I was like, dude") are untouched.
LIKE_VERB_OR_PREP_BEFORE = {
    "don't", "dont", "doesn't", "doesnt", "didn't", "didnt", "not",
    "sound", "sounds", "sounded", "look", "looks", "looked",
    "feel", "feels", "felt", "seem", "seems", "seemed",
    "act", "acts", "acted", "just", "much", "more",
}
LIKE_COMPARATIVE_AFTER = {"this", "that", "these", "those", "it", "him", "her", "them", "us", "me"}


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
class Keeper:
    """A measured segment most likely usable as-is (S3 support evidence).

    Measurement claims only what it can: the span is one uninterrupted
    take, contains no lexicon fillers, has no interior dead air, and its
    loudness stays near the recording's speech level. Whether the CONTENT
    is any good stays with the AI — `evidence` lists exactly why this
    span qualified so the citation writes itself.
    """
    start: float
    end: float
    word_count: int
    text_preview: str
    evidence: list[str] = field(default_factory=list)
    repeated_with: tuple[float, float] | None = None


@dataclass
class RawResult:
    dead_air: list[DeadAir] = field(default_factory=list)
    filler_counts: dict[str, int] = field(default_factory=dict)
    filler_locations: list[tuple[str, float]] = field(default_factory=list)
    repeated_takes: list[RepeatedTake] = field(default_factory=list)
    keepers: list[Keeper] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


KEEPER_MIN_S = 2.0
KEEPER_LEVEL_TOLERANCE_DB = 12.0


def _clean_stretches(
    chunk: list[Word],
    filler_times: list[float],
    dead_air: list[DeadAir],
) -> list[tuple[list[Word], bool]]:
    """Split one take chunk at filler words and interior dead air into
    maximal clean stretches. Returns (words, was_split) pairs — a 48s
    monologue with one 'literally' in the middle yields two keepers, not
    zero (learned on the real gate video)."""
    cut = [
        i for i, w in enumerate(chunk)
        if any(abs(w.start - t) < 0.05 for t in filler_times)
        or any(d.start < w.end and d.end > w.start for d in dead_air)
    ]
    if not cut:
        return [(chunk, False)]
    stretches: list[tuple[list[Word], bool]] = []
    previous = 0
    for index in cut:
        if index > previous:
            stretches.append((chunk[previous:index], True))
        previous = index + 1
    if previous < len(chunk):
        stretches.append((chunk[previous:], True))
    return stretches


def find_keepers(
    words: list[Word],
    filler_locations: list[tuple[str, float]],
    dead_air: list[DeadAir],
    repeated_takes: list[RepeatedTake],
    loudness_curve: list[float],
) -> list[Keeper]:
    """Maximal clean stretches inside takes that pass every measurable
    usability check, each with the evidence the judging AI can cite."""
    filler_times = [t for _, t in filler_locations]
    speech_levels = [level for level in loudness_curve if level > -50.0]
    speech_median = (
        sorted(speech_levels)[len(speech_levels) // 2] if speech_levels else None
    )
    keepers: list[Keeper] = []
    for chunk in _chunks(words):
        for stretch, was_split in _clean_stretches(chunk, filler_times, dead_air):
            if len(stretch) < TAKE_MIN_WORDS:
                continue
            start, end = stretch[0].start, stretch[-1].end
            if end - start < KEEPER_MIN_S:
                continue
            evidence = [
                f"clean stretch within a take ({end - start:.1f}s)"
                if was_split
                else f"one uninterrupted take ({end - start:.1f}s)",
                "no filler words",
                "no interior dead air",
            ]

            if speech_median is not None:
                buckets = [
                    loudness_curve[i]
                    for i in range(
                        int(start), min(int(end) + 1, len(loudness_curve))
                    )
                ]
                if buckets and any(
                    level < speech_median - KEEPER_LEVEL_TOLERANCE_DB
                    for level in buckets
                ):
                    continue
                evidence.append(
                    f"loudness within {KEEPER_LEVEL_TOLERANCE_DB:.0f} dB of "
                    "speech level throughout"
                )
            else:
                # Degraded state stated at the consumer artifact, not
                # silently omitted (Lane C SG-1 process observation).
                evidence.append("CAVEAT: loudness not verified (no curve)")

            repeated_with = None
            for take in repeated_takes:
                if abs(take.first_start - start) < 0.2:
                    repeated_with = (take.second_start, take.second_end)
                    break
                if abs(take.second_start - start) < 0.2:
                    repeated_with = (take.first_start, take.first_end)
                    break
            if repeated_with is not None:
                evidence.append(
                    f"NOTE: repeated take exists at "
                    f"{repeated_with[0]:.1f}-{repeated_with[1]:.1f}s — "
                    "compare before choosing"
                )

            preview = " ".join(w.text.strip() for w in stretch)
            keepers.append(Keeper(
                start=round(start, 3),
                end=round(end, 3),
                word_count=len(stretch),
                text_preview=preview[:100],
                evidence=evidence,
                repeated_with=repeated_with,
            ))
    return keepers


def measure_raw(
    words: list[Word],
    speech_segments: list[tuple[float, float]] | None,
    duration: float,
    loudness_curve: list[float] | None = None,
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

    # Keeper honesty (Lane C SG-1 P1 finding): a keeper's definition
    # REQUIRES the dead-air check, so when VAD never ran the check cannot
    # pass — deriving keepers anyway would hand the judging AI the false
    # evidence "no interior dead air". Skip derivation and say so.
    if speech_segments is None:
        result.warnings.append(
            "raw: keeper derivation skipped — its definition requires "
            "dead-air measurement, which was unavailable (VAD)"
        )
        return result

    result.keepers = find_keepers(
        words,
        result.filler_locations,
        result.dead_air,
        result.repeated_takes,
        loudness_curve or [],
    )
    if result.keepers:
        spans = ", ".join(
            f"{k.start:.1f}-{k.end:.1f}s" for k in result.keepers[:6]
        )
        more = (
            f" (+{len(result.keepers) - 6} more)"
            if len(result.keepers) > 6 else ""
        )
        result.warnings.append(
            f"raw: {len(result.keepers)} keeper segment(s) — {spans}{more}"
        )
    else:
        result.warnings.append(
            "raw: no keeper segments passed every check — every span has "
            "fillers, dead air, level drops, or is too short"
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
            if text == "like" and _like_is_not_filler(cleaned, index):
                index += 1
                continue
            counts[text] = counts.get(text, 0) + 1
            locations.append((text, word.start))
        index += 1
    return counts, locations



def _like_is_not_filler(cleaned: list[tuple[str, Word]], index: int) -> bool:
    """True when "like" is unambiguously a verb, preposition or
    comparative rather than a filler. Deliberately conservative: it
    resolves only the clear cases and leaves anything ambiguous counted,
    so the measurement errs toward reporting rather than hiding."""
    prev = cleaned[index - 1][0] if index > 0 else ""
    nxt = cleaned[index + 1][0] if index + 1 < len(cleaned) else ""
    if prev in LIKE_VERB_OR_PREP_BEFORE:
        return True
    return nxt in LIKE_COMPARATIVE_AFTER


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
