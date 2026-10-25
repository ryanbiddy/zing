"""Cross-platform acceptance failures must stay diagnosable and fail honestly."""
import json
import os
import subprocess
import sys
import zipfile

import pytest

from test_release_packaging import load


@pytest.mark.parametrize("name", ["socketpair", "_fallback_socketpair"])
def test_windows_tcp_self_pipe_with_both_stdlib_names(name):
    # Use the actual stdlib TCP implementation even on POSIX. Emulate the older
    # public name with no private helper, which local 3.11.14 otherwise misses.
    code = f'''
import ast, asyncio, socket, types
from pathlib import Path
# POSIX can select a native implementation at import time. Load the Windows
# fallback from the same stdlib source so every OS tests the actual TCP path.
tree = ast.parse(Path(socket.__file__).read_text(encoding='utf-8'))
definition = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)
                  and node.name in ('socketpair', '_fallback_socketpair')
                  and any(isinstance(call, ast.Attribute) and call.attr == 'connect'
                          for call in ast.walk(node)))
namespace = dict(vars(socket))
exec(compile(ast.Module(body=[definition], type_ignores=[]), socket.__file__, 'exec'), namespace)
pair = namespace[definition.name]
pair = types.FunctionType(pair.__code__.replace(co_name={name!r}),
                          pair.__globals__, {name!r}, pair.__defaults__)
socket.socketpair = pair
if hasattr(socket, '_fallback_socketpair'):
    del socket._fallback_socketpair
'''
    code += load("fresh_install_check").BLOCK_NETWORK
    code += '''
a, b = socket.socketpair()
a.sendall(b'pipe')
assert b.recv(4) == b'pipe'
a.close(); b.close()
async def main():
    await asyncio.sleep(0)
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("operation", [
    "socket.socket().connect(('127.0.0.1', 1))",
    "socket.socket().connect(('127.0.0.1', 5179))",
    "socket.socket().connect(('192.0.2.1', 80))",
    "socket.socket(socket.AF_INET6).connect(('::1', 5179))",
    "socket.getaddrinfo('example.invalid', 80)",
    "socket.socket(type=socket.SOCK_DGRAM).sendto(b'x', ('127.0.0.1', 5179))",
    # A matching function name outside socket.py is still an application call.
    "exec('def socketpair(): socket.socket().connect((\"127.0.0.1\", 5179))'); socketpair()",
])
def test_guard_blocks_application_network_before_io(operation):
    code = load("fresh_install_check").BLOCK_NETWORK + "\n" + operation
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "fresh-install: network disabled" in result.stderr


@pytest.mark.parametrize("failure", ["exit", "timeout", "validation", "launch"])
def test_step_records_command_failure_and_partial_output(tmp_path, failure):
    module = load("fresh_install_check")
    steps, snapshots = [], []
    call = module.Recorder(tmp_path, dict(os.environ), "common", steps,
                           lambda: snapshots.append(json.loads(json.dumps(steps))))
    code = "import sys; print('started', flush=True); print('details', file=sys.stderr, flush=True); "
    command = [sys.executable, "-c", code + ("sys.exit(7)" if failure == "exit" else
               "import time; time.sleep(10)" if failure == "timeout" else "pass")]
    if failure == "launch":
        command = [str(tmp_path / "missing-executable")]

    def validate(_):
        raise AssertionError()  # The exact empty-error regression.

    with pytest.raises(Exception):
        call("broken", command, timeout=1,
             validate=validate if failure == "validation" else None)
    assert snapshots[0][0]["status"] == "running"
    step = snapshots[-1][0]
    assert step["command"] == command and step["status"] == "failed"
    assert step["error"] and "Traceback" in step["traceback"]
    assert step["returncode"] == {"exit": 7, "validation": 0}.get(failure)
    if failure != "launch":
        assert "started" in step["stdout_tail"] and "details" in step["stderr_tail"]
    assert "Traceback" in (tmp_path / "broken.log").read_text(encoding="utf-8")


def test_report_keeps_steps_and_traceback_on_empty_exception(tmp_path, monkeypatch, capsys):
    module = load("fresh_install_check")
    wheel = tmp_path / "wheel.whl"
    wheel.write_bytes(b"placeholder")
    report_path = tmp_path / "report.json"

    def fail(wheel, root, extras, steps, checkpoint):
        steps.append({"step": "studio", "command": ["zing", "studio"], "returncode": 0,
                      "stderr_tail": "", "status": "passed"})
        checkpoint()
        assert json.loads(report_path.read_text())["checks"][extras] == steps
        raise AssertionError()

    monkeypatch.setattr(module, "run_check", fail)
    assert module.main(["--wheel", str(wheel), "--work-dir", str(tmp_path / "work"),
                        "--report", str(report_path)]) == 1
    report = json.loads(report_path.read_text())
    assert report["checks"]["mcp,render,memes"][0]["step"] == "studio"
    assert report["error"] == "AssertionError: " and report["status"] == "failed"
    assert "Traceback" in report["traceback"] and "Traceback" in capsys.readouterr().err


def studio_result(root, output):
    (root / "studio").mkdir()
    (root / "studio/studio-result.json").write_text(json.dumps(
        {"ok": True, "status": "ready", "outputs": [str(output)]}), encoding="utf-8")


def test_studio_resolves_temp_alias_like_macos_var(tmp_path):
    real = tmp_path / "private" / "var"
    real.mkdir(parents=True)
    alias = tmp_path / "var"
    if os.name == "nt":
        # Directory junctions do not require Windows symlink privileges.
        import _winapi
        _winapi.CreateJunction(str(real), str(alias))
    else:
        alias.symlink_to(real, target_is_directory=True)
    try:
        output = real / "image.png"
        output.write_bytes(b"generated fixture")
        studio_result(real, output)
        assert not output.is_relative_to(alias)  # Old assertion fails.
        load("fresh_install_check").validate_studio(alias)
    finally:
        if os.name == "nt":
            alias.rmdir()  # Remove only this test's junction, never its target.
        else:
            alias.unlink()


@pytest.mark.parametrize("missing", [True, False])
def test_studio_rejects_missing_or_escaped_output(tmp_path, missing):
    root = tmp_path / "run"
    root.mkdir()
    output = tmp_path / "escaped.png"
    if not missing:
        output.write_bytes(b"outside")
    studio_result(root, output)
    with pytest.raises((FileNotFoundError, ValueError), match="escaped.png"):
        load("fresh_install_check").validate_studio(root)


def fake_wheel(tmp_path):
    wheel = tmp_path / "test.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("myzing-1.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: myzing\nVersion: 1\n" +
            "".join(f"Provides-Extra: {extra}\n" for extra in
                    ("dev", "all", "mcp", "render", "memes", "audio-ml", "fonts", "study")))
    return wheel


@pytest.mark.parametrize("failure", ["optional", "core", "network", "smoke", "aggregate"])
def test_optional_platform_limitations_do_not_hide_core_or_runtime_failures(tmp_path, monkeypatch, failure):
    module = load("fresh_install_check")
    report = {"checks": {}, "environments": {}, "platform_limitations": []}
    visited = []

    def run(wheel, root, extras, steps, checkpoint):
        visited.append(extras)
        broken = extras == "all" or (failure == "optional" and extras.endswith(",audio-ml"))
        broken |= failure == "core" and extras == "mcp,render,memes"
        if broken:
            step = {"step": "mcp-stdio" if failure == "smoke" else "install", "returncode": 1,
                    "command": ["pip", "install", extras], "stdout_tail": "", "status": "failed",
                    "stderr_tail": ("Retrying: connection failed\n" if failure == "network" else "") +
                    "ERROR: No matching distribution found for unavailable-runtime"}
            steps.append(step)
            raise module.StepError(step)

    monkeypatch.setattr(module, "run_check", run)
    if failure == "optional":
        module.check_environments(fake_wheel(tmp_path), tmp_path, report, lambda: None)
        assert report["environments"]["optional-audio-ml"] == "platform_limitation"
        assert report["environments"]["optional-fonts"] == "passed"
        assert report["environments"]["optional-study"] == "passed"
        assert report["environments"]["all"] == "platform_limitation"
        assert "No matching distribution" in report["platform_limitations"][0]["pip_error"]["stderr_tail"]
    else:
        with pytest.raises(module.StepError):
            module.check_environments(fake_wheel(tmp_path), tmp_path, report, lambda: None)
        assert not report["platform_limitations"]
        if failure == "core":
            assert visited == ["mcp,render,memes"]
