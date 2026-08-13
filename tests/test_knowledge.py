"""知识库数据模型、动作和 Electron 桥测试。"""

import importlib
import os
import tempfile
import unittest
from pathlib import Path

from system_os.entity import ValidationError
from system_os.schema_knowledge import validate_knowledge, validate_knowledge_note


def _item(**overrides):
    meta = {
        "id": "knowledge-x", "title": "一篇论文", "kind": "paper",
        "status": "want", "priority": "P1", "category": "学业",
        "domain": "work", "source_machine": "work",
    }
    meta.update(overrides)
    return meta


class TestKnowledgeSchema(unittest.TestCase):
    def test_valid_item_and_note(self):
        validate_knowledge(_item())
        validate_knowledge_note({
            "id": "knote-x", "knowledge_ref": "knowledge-x",
            "note_type": "insight", "captured_on": "2026-08-13",
            "domain": "work", "source_machine": "work",
        })

    def test_invalid_enums_and_numbers(self):
        with self.assertRaises(ValidationError):
            validate_knowledge(_item(kind="电影"))
        with self.assertRaises(ValidationError):
            validate_knowledge(_item(status="看一半"))
        with self.assertRaises(ValidationError):
            validate_knowledge(_item(rating=6))
        with self.assertRaises(ValidationError):
            validate_knowledge(_item(duration_minutes=-1))

    def test_note_requires_knowledge_ref_and_date(self):
        with self.assertRaises(ValidationError):
            validate_knowledge_note({
                "id": "knote-x", "knowledge_ref": "task-x",
                "note_type": "insight", "captured_on": "今天",
                "domain": "work", "source_machine": "work",
            })

    def test_fixtures_are_valid(self):
        from system_os.vault import Vault
        vault = Vault(Path(__file__).resolve().parent.parent / "fixtures" / "work")
        validate_knowledge(vault.read("knowledge-2026-0001")["meta"])
        validate_knowledge_note(vault.read("knote-2026-0001")["meta"])


class TestKnowledgeActions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self.tmp.name
        os.environ["MACHINE_ID"] = "personal"
        import system_os.config as config
        import system_os.actions as actions
        importlib.reload(config)
        importlib.reload(actions)
        self.actions = actions

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("MACHINE_ID", None)

    def test_add_item_routes_to_knowledge_directory(self):
        rec = self.actions.add_knowledge(
            "Attention Is All You Need", kind="paper", priority="P0",
            creator="Vaswani et al.", source_url="https://example.test/paper")
        self.assertTrue(rec["meta"]["id"].startswith("knowledge-"))
        files = list(Path(self.tmp.name, "knowledge").glob("knowledge-*.md"))
        self.assertEqual(len(files), 1)

    def test_add_notes_and_list_expanded_item(self):
        item = self.actions.add_knowledge("一期播客", kind="podcast")
        iid = item["meta"]["id"]
        note = self.actions.add_knowledge_note(
            iid, "核心不是提高意志力，而是减少切换成本。", note_type="insight")
        self.assertTrue(note["meta"]["id"].startswith("knote-"))
        listed = self.actions.list_knowledge()
        self.assertEqual(listed[0]["id"], iid)
        self.assertEqual(listed[0]["notes"][0]["note_type"], "insight")
        self.assertIn("减少切换成本", listed[0]["notes"][0]["body"])

    def test_learning_flow_and_auto_learned_date(self):
        item = self.actions.add_knowledge("一本书", kind="book")
        iid = item["meta"]["id"]
        learning = self.actions.update_knowledge(iid, status="learning", priority="P0")
        self.assertEqual(learning["meta"]["status"], "learning")
        learned = self.actions.update_knowledge(iid, status="learned", rating=5)
        self.assertEqual(learned["meta"]["learned_on"], self.actions._today())
        self.assertEqual(learned["meta"]["rating"], 5)

    def test_empty_or_orphan_note_rejected(self):
        item = self.actions.add_knowledge("课程", kind="course")
        with self.assertRaisesRegex(ValidationError, "不能为空"):
            self.actions.add_knowledge_note(item["meta"]["id"], "  ")
        with self.assertRaisesRegex(ValidationError, "不存在"):
            self.actions.add_knowledge_note("knowledge-missing", "内容")

    def test_os_api_returns_stats_and_can_write_note(self):
        from system_os.os_api import _run
        item = self.actions.add_knowledge(
            "完成的论文", kind="paper", status="learned", duration_minutes=40)
        result = _run("knowledge_list", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["stats"]["learned"], 1)
        self.assertEqual(result["data"]["stats"]["papers"], 1)
        self.assertEqual(result["data"]["stats"]["minutes"], 40.0)
        note = _run("knowledge_add_note", {
            "id": item["meta"]["id"], "content": "一个新想法", "note_type": "connection"})
        self.assertTrue(note["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
