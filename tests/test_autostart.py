"""LaunchAgent generation tests that never open a GUI window."""

from __future__ import annotations

import importlib.util
import plistlib
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = ROOT / "ui" / "autostart" / "generate_plist.py"
TEMPLATE_PATH = ROOT / "ui" / "autostart" / "com.steward.floatwin.plist.template"
INSTALL_PATH = ROOT / "ui" / "autostart" / "install.sh"

SPEC = importlib.util.spec_from_file_location("generate_plist", GENERATOR_PATH)
assert SPEC and SPEC.loader
generate_plist = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_plist)


class TestAutostartGeneration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "workspace & spaces"
        self.ui = self.root / "ui"
        self.binary = (
            self.ui / "node_modules" / "electron" / "dist" /
            "Electron.app" / "Contents" / "MacOS" / "Electron"
        )
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"native fixture")
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        (self.ui / "node_modules" / "electron" / "path.txt").write_text(
            "Electron.app/Contents/MacOS/Electron\n", encoding="utf-8"
        )
        (self.ui / "package.json").write_text("{}\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_plist_uses_native_binary_and_ui_argument(self):
        payload = generate_plist.build_plist(TEMPLATE_PATH, self.ui, self.root / "logs")
        parsed = plistlib.loads(payload)
        self.assertEqual(parsed["ProgramArguments"], [
            str(self.binary.resolve()), str(self.ui.resolve()),
        ])
        self.assertNotIn(".bin/electron", payload.decode("utf-8"))

    def test_atomic_write_produces_valid_plist(self):
        destination = self.root / "LaunchAgents" / "steward.plist"
        generate_plist.write_plist(
            TEMPLATE_PATH, destination, self.ui, self.root / "logs"
        )
        with destination.open("rb") as handle:
            parsed = plistlib.load(handle)
        self.assertEqual(parsed["WorkingDirectory"], str(self.ui.resolve()))
        self.assertEqual(destination.stat().st_mode & 0o777, 0o644)

    def test_manifest_cannot_escape_electron_dist(self):
        (self.ui / "node_modules" / "electron" / "path.txt").write_text(
            "../../../../outside", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "escapes"):
            generate_plist.resolve_electron_binary(self.ui)

    def test_missing_install_has_clear_error(self):
        (self.ui / "node_modules" / "electron" / "path.txt").unlink()
        with self.assertRaisesRegex(ValueError, "npm install"):
            generate_plist.resolve_electron_binary(self.ui)

    def test_installer_never_uses_node_dependent_shim(self):
        installer = INSTALL_PATH.read_text(encoding="utf-8")
        self.assertNotIn("node_modules/.bin/electron", installer)
        self.assertIn("generate_plist.py", installer)
        self.assertIn("launchctl bootstrap", installer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
