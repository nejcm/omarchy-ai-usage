import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from providers import common  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
FUTURE_EXP = 4102444800
PAST_EXP = 1000000000

NODE = shutil.which("node")
# /usr/bin/qmltestrunner is Qt 5 on some distros, so only Qt 6 locations are probed.
QMLTESTRUNNER = os.environ.get("QMLTESTRUNNER") or next(
    (path for path in ("/usr/lib/qt6/bin/qmltestrunner", "/usr/lib64/qt6/bin/qmltestrunner",
                       "/usr/lib/x86_64-linux-gnu/qt6/bin/qmltestrunner") if Path(path).exists()), None)
requires_node = unittest.skipUnless(NODE, "node not installed")
requires_qml = unittest.skipUnless(QMLTESTRUNNER, "Qt 6 qmltestrunner not found; set QMLTESTRUNNER")


def model_source():
    return (ROOT / "Model.js").read_text().replace(".pragma library", "")


def run_node(case, script):
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    case.assertEqual(result.returncode, 0, result.stderr)
    return result.stdout


def run_qml(case, test_file, stubs=True):
    imports = ["-import", str(ROOT / "tests/qml-stubs")] if stubs else []
    result = subprocess.run(
        [QMLTESTRUNNER, *imports, "-input", str(ROOT / "tests" / test_file), "-o", "-,txt"],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
             "QT_QUICK_BACKEND": "software", "QT_LOGGING_TO_CONSOLE": "1"},
        capture_output=True, text=True, timeout=60,
    )
    case.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def load(name):
    return json.loads((FIXTURES / name).read_text())


def jwt(payload):
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_jwt(exp):
    return jwt({"alg": "none"}) + "." + jwt({"exp": exp}) + ".sig"


class FakeRequest:
    """Routes a request to a Response by URL substring; records calls.

    A list-valued route is consumed one response per call; the last repeats.
    """

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, hosts, headers, body=None, error_body=False):
        self.calls.append({"method": method, "url": url, "hosts": tuple(hosts), "headers": dict(headers)})
        for needle, response in self.routes.items():
            if needle in url:
                if isinstance(response, list):
                    return response.pop(0) if len(response) > 1 else response[0]
                return response
        return common.Response(0, None, "network")


def write(home, relative, content):
    path = Path(home) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text)
    return path


class ProviderCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
