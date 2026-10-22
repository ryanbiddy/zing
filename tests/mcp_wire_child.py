"""Deterministic host inputs for wire goldens; never a production entry point.

Run the real CLI with its actual SDK, handlers and serialization. Only doctor
inputs are fixed. No network is allowed, even if a future handler tries it.
"""
import os
from pathlib import Path
import runpy
import socket
import sys

assert os.environ["UOINK_URL"] == "disabled://mcp-wire"
assert Path(os.environ["ZING_HOME"]).is_absolute()


def offline(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        # Windows asyncio builds its private wakeup pipe with socketpair().
        caller = sys._getframe(1)
        if (event == "socket.connect" and caller.f_code.co_name == "_fallback_socketpair"
                and caller.f_code.co_filename == socket.__file__):
            return
        raise AssertionError("Wire fixture attempted network access")


sys.addaudithook(offline)

from myzing import doctor

doctor.run_checks = lambda: [
    doctor.Check("ffmpeg", doctor.REQUIRED, True, "wire fixture: available"),
    doctor.Check("uoink", doctor.OPTIONAL, False, "wire fixture: offline"),
]
sys.argv = ["zing", "serve-mcp"]
runpy.run_module("myzing.cli", run_name="__main__")
