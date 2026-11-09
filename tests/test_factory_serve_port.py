"""An unavailable review port gets a plain message, not a raw socket error."""
from __future__ import annotations

import errno

import pytest

from myzing.factory import serve
from myzing.factory.command import run as main
from myzing.factory.tools import FactoryError


@pytest.mark.parametrize("error", [
    PermissionError(10013, "An attempt was made to access a socket in a way forbidden by its access permissions"),
    OSError(errno.EADDRINUSE, "Address already in use"),
])
def test_unavailable_port_names_the_port_and_the_fix(tmp_path, monkeypatch, capsys, error):
    def refuse(*args, **kwargs):
        raise error
    monkeypatch.setattr(serve, "ThreadingHTTPServer", refuse)
    monkeypatch.setattr(serve, "Studio", lambda project, judge: object())
    with pytest.raises(FactoryError, match=r"Port 8769 is not available on this computer .*--port 0"):
        serve.serve(tmp_path, 8769, "host", say=lambda m: None)
    assert main(["serve", str(tmp_path), "--port", "8769"]) != 0
    err = capsys.readouterr().err
    assert "Port 8769 is not available" in err and "WinError" not in err and "Traceback" not in err
