"""The on-disk state marker and the assembled status have different contracts."""
from myzing.factory import pipeline


def test_status_docstring_names_the_marker_and_full_report():
    text = pipeline.status.__doc__ or ""
    assert "status.json" in text and "marker only" in text
    assert "zing factory status" in text
