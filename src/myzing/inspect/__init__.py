"""Local, bounded inspection of rendered video timelines."""


class InspectionError(ValueError):
    """An inspection could not be completed; the message includes a remedy."""
