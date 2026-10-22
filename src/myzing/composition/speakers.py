"""Optional source-clock dialogue evidence, separate from the legacy Word schema."""

from dataclasses import dataclass

from myzing.contracts import Record, bounded, interval, nonempty


@dataclass
class SpeechWord(Record):
    asset_id: str
    text: str
    start: float
    end: float
    speaker: str | None = None
    face_track_id: str | None = None
    confidence: float = 1.0
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.asset_id, "speech asset_id")
        nonempty(self.text, "speech word")
        interval(self.start, self.end, "speech word")
        bounded(self.confidence, 0, 1, "speech confidence")
        for value in (self.speaker, self.face_track_id):
            if value is not None:
                nonempty(value, "speaker/face identity")
        if self.face_track_id is not None and self.speaker is None:
            raise ValueError("a face association needs a named speaker")


@dataclass
class SpeakerTurn(Record):
    start: float  # Clip-local output seconds.
    end: float
    speaker: str | None
    face_track_id: str | None
    confidence: float
    method: str
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        interval(self.start, self.end, "speaker turn")
        bounded(self.confidence, 0, 1, "speaker confidence")
        nonempty(self.method, "speaker method")
