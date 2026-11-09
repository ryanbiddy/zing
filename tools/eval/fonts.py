"""Font paths for generated media."""

from pathlib import Path


BUNDLED_FONT = Path(__file__).resolve().parents[2] / "src/myzing/_data/fonts/IBMPlexSans.ttf"


def drawtext_fontfile(path=BUNDLED_FONT):
    path = str(path).replace("\\", "/").replace(":", r"\:")
    return path.replace("'", r"'\\\''")  # Escape both filtergraph and option parsing.
