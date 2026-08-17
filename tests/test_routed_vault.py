"""Tests for physical work/personal vault routing."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os import actions  # noqa: E402
from system_os.entity import ValidationError  # noqa: E402
from system_os.vault import Vault  # noqa: E402


class TestRoutedVault(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.work = base / "work"
        self.personal = base / "personal"
        self.work.mkdir()
        self.personal.mkdir()
        os.environ["WORK_VAULT_PATH"] = str(self.work)
        os.environ["PERSONAL_VAULT_PATH"] = str(self.personal)
        os.environ["PERSONAL_VAULT_ROUTING"] = "enabled"

    def tearDown(self):
        for key in (
            "WORK_VAULT_PATH", "PERSONAL_VAULT_PATH",
            "PERSONAL_VAULT_ROUTING", "MACHINE_ID",
        ):
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def test_personal_categories_are_physically_routed(self):
        os.environ["MACHINE_ID"] = "personal"
        life = actions.add_task("anonymous life fixture", category="生活")
        work = actions.add_task("anonymous work fixture", category="事业")
        self.assertTrue(Vault(self.personal).exists(life["meta"]["id"]))
        self.assertFalse(Vault(self.work).exists(life["meta"]["id"]))
        self.assertTrue(Vault(self.work).exists(work["meta"]["id"]))
        titles = {item["meta"]["title"] for item in actions.list_tasks()}
        self.assertEqual(titles, {"anonymous life fixture", "anonymous work fixture"})

    def test_work_machine_rejects_personal_category(self):
        os.environ["MACHINE_ID"] = "work"
        with self.assertRaisesRegex(ValidationError, "工作机拒绝"):
            actions.add_task("anonymous private fixture", category="人际")
        self.assertEqual(list(Vault(self.work).list()), [])
        self.assertEqual(list(Vault(self.personal).list()), [])

    def test_existing_shared_record_is_not_silently_migrated(self):
        os.environ["MACHINE_ID"] = "personal"
        record = actions.add_task("anonymous shared fixture", category="事业")
        with self.assertRaisesRegex(ValidationError, "备份迁移"):
            actions._work_vault().update(record["meta"]["id"], {"category": "生活"})
        self.assertTrue(Vault(self.work).exists(record["meta"]["id"]))
        self.assertFalse(Vault(self.personal).exists(record["meta"]["id"]))

    def test_personal_child_note_and_daily_log_do_not_leak_to_work(self):
        os.environ["MACHINE_ID"] = "personal"
        item = actions.add_knowledge("anonymous fixture", category="生活")
        note = actions.add_knowledge_note(item["meta"]["id"], "anonymous note")
        daily = actions.generate_daily_log(actions._today())
        personal = Vault(self.personal)
        work = Vault(self.work)
        for entity_id in (item["meta"]["id"], note["meta"]["id"], daily["meta"]["id"]):
            self.assertTrue(personal.exists(entity_id))
            self.assertFalse(work.exists(entity_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
