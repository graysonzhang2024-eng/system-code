"""Integration tests for persistent Git privacy hooks and installer."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import install_privacy_guard  # noqa: E402


SOURCE_ROOT = Path(__file__).resolve().parent.parent


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


class TestPrivacyHooks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.remote = base / "public.git"
        subprocess.run(
            ["git", "init", "--bare", "-q", "-b", "main", str(self.remote)],
            check=True,
        )
        self.repo = base / "repo"
        self.repo.mkdir()
        self.assertEqual(run(self.repo, "init", "-q", "-b", "main").returncode, 0)
        self.assertEqual(run(self.repo, "remote", "add", "origin", str(self.remote)).returncode, 0)
        (self.repo / "scripts").mkdir()
        (self.repo / ".githooks").mkdir()
        shutil.copy2(SOURCE_ROOT / "scripts" / "privacy_scan.py", self.repo / "scripts")
        shutil.copy2(SOURCE_ROOT / ".githooks" / "pre-commit", self.repo / ".githooks")
        shutil.copy2(SOURCE_ROOT / ".githooks" / "pre-push", self.repo / ".githooks")
        run(self.repo, "config", "user.name", "Public Maintainer")
        run(self.repo, "config", "user.email", "maintainer@users.noreply.github.com")
        (self.repo / "README.md").write_text("anonymous fixture\n", encoding="utf-8")
        run(self.repo, "add", "-A")
        self.assertEqual(run(self.repo, "commit", "-q", "-m", "initial fixture").returncode, 0)
        self.denylist = base / "private-denylist.txt"
        self.denylist.write_text("private-literal\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_pre_commit_scans_exact_staged_snapshot(self):
        install_privacy_guard.install(self.repo, "personal", self.denylist)
        path = self.repo / "README.md"
        path.write_bytes(b"/Users/" + b"staged-user/project\n")
        run(self.repo, "add", "README.md")
        path.write_text("safe unstaged replacement\n", encoding="utf-8")
        result = run(self.repo, "commit", "-m", "must be blocked")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HOME_PATH", result.stdout + result.stderr)

    def test_pre_push_blocks_secret_deleted_from_tip(self):
        install_privacy_guard.install(self.repo, "personal", self.denylist)
        secret = self.repo / "old.txt"
        secret.write_bytes(b"/Users/" + b"historical-user/project\n")
        run(self.repo, "add", "old.txt")
        self.assertEqual(run(
            self.repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "fixture"
        ).returncode, 0)
        secret.unlink()
        run(self.repo, "add", "-A")
        self.assertEqual(run(
            self.repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "remove fixture"
        ).returncode, 0)
        result = run(self.repo, "push", "origin", "main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HOME_PATH", result.stdout + result.stderr)

    def test_work_install_disables_transport_push(self):
        install_privacy_guard.install(self.repo, "work", None)
        self.assertEqual(
            run(self.repo, "remote", "get-url", "--push", "origin").stdout.strip(),
            "disabled://system-code-read-only",
        )
        self.assertEqual(run(
            self.repo, "config", "--bool", "--get", "privacy.pushAllowed"
        ).stdout.strip(), "false")


if __name__ == "__main__":
    unittest.main(verbosity=2)
