"""Runtime install advice must use the active installer and release version."""
from pathlib import Path
import re
import subprocess
import sys

import pytest


def test_no_literal_myzing_pip_install_hints():
    root = Path(__file__).resolve().parents[1] / "src/myzing"
    found = [f"{path.relative_to(root)}:{i}" for path in root.rglob("*.py")
             for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
             if re.search(r'pip install\s+["\']?myzing', line)]
    assert not found, "Use doctor._install_command for install hints. " + ", ".join(found)


@pytest.mark.parametrize("prefix,installer", [("/opt/pipx/venvs/myzing", "pipx install --force"),
                                            ("/opt/uv/tools/myzing", "uv tool install --force"),
                                            ("/opt/venvs/myzing", "python -m pip install")])
def test_shared_hints_use_the_active_installer_and_version(prefix, installer):
    code = '''
import sys
sys.prefix = sys.argv[1]
from myzing import __version__, mcp_server
from myzing.audio import tag_models
from myzing.fonts import library
from myzing.layout import detector
from myzing.memes import PILLOW_HINT
for text, extra in [(tag_models.INSTALL_HINT, "audio-ml"), (library.INSTALL_HINT, "fonts"),
                    (detector.INSTALL_HINT, "layout"), (PILLOW_HINT, "memes"),
                    (mcp_server.ENGINE_MISSING, "study"), (mcp_server.PROFILE_ENGINE_MISSING, "study")]:
    assert f'{sys.argv[2]} "myzing[{extra}]=={__version__}"' in text, text
'''
    result = subprocess.run([sys.executable, "-c", code, prefix, installer], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
