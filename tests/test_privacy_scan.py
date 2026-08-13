"""Tests for the public-repository privacy gate."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import privacy_scan  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class TestPrivacyPatterns(unittest.TestCase):
    def test_generic_identifiers_are_detected_without_echoing_values(self):
        samples = [
            b"/Users/" + b"private-user/project",
            b"/home/" + b"private-user/project",
            b"C:\\Users\\" + b"private-user\\project",
            b"person" + b"@mail.invalid-domain.test",
            b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
            b"OPENAI_API_KEY=" + b"sk" + b"-123456789012345678901234",
        ]
        rules = {
            finding.rule
            for sample in samples
            for finding in privacy_scan.scan_bytes("sample", sample, [])
        }
        self.assertTrue({
            "HOME_PATH", "WINDOWS_HOME_PATH", "EMAIL", "PRIVATE_KEY",
            "PROVIDER_TOKEN",
        }.issubset(rules))

    def test_examples_and_noreply_are_allowed(self):
        data = b"maintainer@example.com bot@users.noreply.github.com <workspace>"
        self.assertEqual(privacy_scan.scan_bytes("sample", data, []), [])

    def test_private_denylist_does_not_appear_in_finding(self):
        term = "专用".encode()
        findings = privacy_scan.scan_bytes("sample", b"prefix " + term, [term])
        rendered = repr(findings)
        self.assertEqual(findings[0].rule, "PRIVATE_DENYLIST")
        self.assertNotIn(term.decode(), rendered)


class TestPrivacyHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "Public Maintainer")
        _git(self.repo, "config", "user.email", "maintainer@users.noreply.github.com")

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, name: str, content: bytes) -> None:
        (self.repo / name).write_bytes(content)
        _git(self.repo, "add", name)
        _git(self.repo, "commit", "-q", "-m", "anonymous fixture")

    def test_deleted_historical_blob_is_still_detected(self):
        secret = b"/Users/" + b"historical-user/project"
        self._commit("old.txt", secret)
        (self.repo / "old.txt").unlink()
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "remove fixture")
        rules = {item.rule for item in privacy_scan.run(self.repo, "HEAD", None, False)}
        self.assertIn("HOME_PATH", rules)

    def test_clean_anonymous_history_passes(self):
        self._commit("README.md", b"anonymous fixture\n")
        self.assertEqual(privacy_scan.run(self.repo, "HEAD", None, False), [])

    def test_non_noreply_commit_identity_fails(self):
        _git(self.repo, "config", "user.email", "person@example.com")
        self._commit("README.md", b"anonymous fixture\n")
        rules = {item.rule for item in privacy_scan.run(self.repo, "HEAD", None, False)}
        self.assertIn("COMMIT_EMAIL_NOT_NOREPLY", rules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
