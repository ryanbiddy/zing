"""Real-subprocess tests for the proc choke point (SG-2 coverage sweep).

Every other test mocks proc.run; these exercise the actual seam — offline,
fast, cross-platform (the child process is this same Python interpreter).
"""

from __future__ import annotations

import sys

import pytest

from myzing.study import proc


def test_run_captures_stdout_as_text():
    result = proc.run([sys.executable, "-c", "print('hello zing')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "hello zing"


def test_run_reports_nonzero_exit_and_stderr():
    result = proc.run([
        sys.executable, "-c",
        "import sys; sys.stderr.write('boom\\n'); sys.exit(3)",
    ])
    assert result.returncode == 3
    assert "boom" in result.stderr


def test_run_survives_undecodable_output():
    # Windows console tools emit whatever bytes they like; the seam must
    # replace rather than raise (cp1252/UTF-8 mix is the classic).
    result = proc.run([
        sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(b'ok \\xff\\xfe bytes')",
    ])
    assert result.returncode == 0
    assert "ok" in result.stdout and "bytes" in result.stdout


def test_missing_binary_raises_toolmissing_pointing_at_doctor():
    with pytest.raises(proc.ToolMissing, match="zing doctor") as excinfo:
        proc.run(["zing-definitely-not-a-real-binary-4718"])
    assert excinfo.value.tool == "zing-definitely-not-a-real-binary-4718"


def test_tail_keeps_last_nonempty_lines():
    text = "one\n\ntwo\nthree\nfour\nfive\nsix\n"
    assert proc.tail(text, lines=2) == "five\nsix"
    assert proc.tail("", lines=3) == ""
    assert proc.tail("only\n") == "only"
