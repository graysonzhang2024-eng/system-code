"""test_schema_work.py —— task / worklog 校验与状态机的考卷。

怎么跑:
    python3 -m pytest tests/                 # 有 pytest
    python3 tests/test_schema_work.py        # 没 pytest 也能跑
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os.entity import ValidationError  # noqa: E402
from system_os.machine import detect_machine  # noqa: E402
from system_os.schema_work import (  # noqa: E402
    check_transition,
    validate_task,
    validate_worklog,
)
from system_os.vault import Vault  # noqa: E402


def _base_task(**overrides):
    """造一条最小合法 task 的 frontmatter,再用 overrides 覆盖字段。"""
    meta = {
        "id": "task-x",
        "title": "测试任务",
        "status": "todo",
        "priority": "P1",
        "category": "事业",
        "energy_cost": "low",
        "domain": "work",
        "source_machine": "work",
    }
    meta.update(overrides)
    return meta


class TestValidateTask(unittest.TestCase):
    def test_minimal_valid(self):
        validate_task(_base_task())  # 不抛错即通过

    def test_missing_required(self):
        m = _base_task()
        del m["priority"]
        with self.assertRaises(ValidationError):
            validate_task(m)

    def test_bad_status(self):
        with self.assertRaises(ValidationError):
            validate_task(_base_task(status="飞了"))

    def test_bad_category(self):
        # category 只能是 5 分类之一
        with self.assertRaises(ValidationError):
            validate_task(_base_task(category="work"))

    def test_all_five_categories_ok(self):
        for c in ("事业", "学业", "人际", "生活", "系统"):
            validate_task(_base_task(category=c))

    def test_blocked_requires_reason(self):
        # blocked 不带原因 → 报错
        with self.assertRaises(ValidationError):
            validate_task(_base_task(status="blocked"))
        # 带了原因 → 通过
        validate_task(_base_task(status="blocked", blocked_reason="等参数"))

    def test_list_field_type(self):
        with self.assertRaises(ValidationError):
            validate_task(_base_task(depends_on="task-1"))  # 应是列表


class TestTransition(unittest.TestCase):
    def test_in_progress_blocked_by_unfinished_dep(self):
        task = _base_task(depends_on=["dep-1"])
        # 依赖还没 done → 不许进 in_progress
        with self.assertRaises(ValidationError):
            check_transition(task, "in_progress", {"dep-1": "todo"})

    def test_in_progress_ok_when_deps_done(self):
        task = _base_task(depends_on=["dep-1"])
        check_transition(task, "in_progress", {"dep-1": "done"})  # 不抛错

    def test_no_deps_can_start(self):
        check_transition(_base_task(), "in_progress", {})

    def test_bad_target_status(self):
        with self.assertRaises(ValidationError):
            check_transition(_base_task(), "睡觉", {})


class TestValidateWorklog(unittest.TestCase):
    def _base_log(self, **ov):
        m = {
            "id": "log-x",
            "date": "2026-07-17",
            "summary": "干了点活",
            "category": "系统",
            "domain": "work",
            "source_machine": "work",
        }
        m.update(ov)
        return m

    def test_minimal_valid(self):
        validate_worklog(self._base_log())

    def test_missing_summary(self):
        m = self._base_log()
        del m["summary"]
        with self.assertRaises(ValidationError):
            validate_worklog(m)

    def test_bad_energy_actual(self):
        with self.assertRaises(ValidationError):
            validate_worklog(self._base_log(energy_actual="爆炸"))

    def test_rule_candidates_must_be_list(self):
        with self.assertRaises(ValidationError):
            validate_worklog(self._base_log(rule_candidates="一条规则"))


class TestFixturesValidate(unittest.TestCase):
    """fixtures 里的样例必须全部通过校验(它们是格式的活文档)。"""

    def setUp(self):
        self.vault = Vault(Path(__file__).resolve().parent.parent / "fixtures" / "work")

    def test_task_fixtures_valid(self):
        for tid in ("task-2026-0001", "task-2026-0002"):
            meta = self.vault.read(tid)["meta"]
            validate_task(meta)

    def test_worklog_fixture_valid(self):
        meta = self.vault.read("log-2026-0001")["meta"]
        validate_worklog(meta)

    def test_blocked_fixture_has_reason(self):
        meta = self.vault.read("task-2026-0002")["meta"]
        self.assertEqual(meta["status"], "blocked")
        self.assertTrue(meta.get("blocked_reason"))


class TestMachine(unittest.TestCase):
    def test_detect_returns_valid(self):
        self.assertIn(detect_machine(), {"work", "personal"})

    def test_env_override(self):
        import os

        old = os.environ.get("MACHINE_ID")
        try:
            os.environ["MACHINE_ID"] = "personal"
            self.assertEqual(detect_machine(), "personal")
        finally:
            if old is None:
                os.environ.pop("MACHINE_ID", None)
            else:
                os.environ["MACHINE_ID"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
