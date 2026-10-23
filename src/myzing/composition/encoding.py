"""Opt-in x264 delivery budgets, in decimal MB or video kilobits/second."""

from dataclasses import dataclass

from myzing.contracts import Record, bounded


@dataclass
class DeliveryEncoding(Record):
    target_mb: float | None = None
    video_bitrate_kbps: float | None = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if (self.target_mb is None) == (self.video_bitrate_kbps is None):
            raise ValueError("delivery: supply exactly one of target_mb or video_bitrate_kbps")
        if self.target_mb is not None:
            bounded(self.target_mb, .05, 100000, "target_mb")
        if self.video_bitrate_kbps is not None:
            bounded(self.video_bitrate_kbps, 16, 1000000, "video_bitrate_kbps")

    def video_rate(self, duration):
        # Reserve AAC at its configured 192 kb/s, plus 1.5% container overhead.
        rate = self.video_bitrate_kbps if self.target_mb is None else self.target_mb * 8000 * .985 / duration - 192
        if rate < 16:
            raise ValueError("Delivery target leaves less than 16 kb/s for video after audio; increase target MB")
        return round(rate * 1000)
