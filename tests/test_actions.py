"""test_actions.py —— 高层工具层(agent 的手)的考卷。

关键:每个测试用独立临时目录当 vault(通过 WORK_VAULT_PATH 环境变量注入),
这既隔离了测试、又顺便验证了"配置翻转"机制(.env 指向哪就读哪)。

怎么跑:
    python3 -m pytest tests/
    python3 tests/test_actions.py
"""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os.entity import ValidationError  # noqa: E402


class ActionsTestBase(unittest.TestCase):
    def setUp(self):
        # 建临时 vault,并让 MACHINE_ID 固定为 work(结果可预期)
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self._tmp.name
        os.environ["MACHINE_ID"] = "work"
        # 重新加载 config 和 actions,让新环境变量生效
        import system_os.config as config
        import system_os.actions as actions
        importlib.reload(config)
        importlib.reload(actions)
        self.actions = actions

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("MACHINE_ID", None)


class TestAddAndList(ActionsTestBase):
    def test_add_task_autofills(self):
        rec = self.actions.add_task("写周报", priority="P1", category="事业")
        m = rec["meta"]
        self.assertTrue(m["id"].startswith("task-"))
        self.assertEqual(m["status"], "todo")          # 自动 todo
        self.assertEqual(m["domain"], "work")           # 按机器身份自动填
        self.assertIn("created_at", m)                  # 自动时间戳

    def test_id_autoincrement(self):
        a = self.actions.add_task("任务A")
        b = self.actions.add_task("任务B")
        self.assertNotEqual(a["meta"]["id"], b["meta"]["id"])

    def test_add_task_bad_category_rejected(self):
        with self.assertRaises(ValidationError):
            self.actions.add_task("x", category="work")  # 非5分类

    def test_list_filters_and_sorts(self):
        self.actions.add_task("低优先", priority="P3")
        self.actions.add_task("高优先", priority="P0")
        tasks = self.actions.list_tasks()
        # P0 应排在最前
        self.assertEqual(tasks[0]["meta"]["priority"], "P0")

    def test_list_by_status(self):
        self.actions.add_task("t1")
        todos = self.actions.list_tasks(status="todo")
        self.assertEqual(len(todos), 1)


class TestStateMachine(ActionsTestBase):
    def test_start_task(self):
        t = self.actions.add_task("干活")
        started = self.actions.start_task(t["meta"]["id"])
        self.assertEqual(started["meta"]["status"], "in_progress")

    def test_start_blocked_by_dependency(self):
        dep = self.actions.add_task("前置")
        main = self.actions.add_task("主任务", depends_on=[dep["meta"]["id"]])
        # 依赖还是 todo,不能开工
        with self.assertRaises(ValidationError):
            self.actions.start_task(main["meta"]["id"])
        # 依赖完成后可以开工
        self.actions.complete_task(dep["meta"]["id"])
        started = self.actions.start_task(main["meta"]["id"])
        self.assertEqual(started["meta"]["status"], "in_progress")

    def test_block_requires_reason(self):
        t = self.actions.add_task("会卡的任务")
        blocked = self.actions.block_task(t["meta"]["id"], reason="等外部确认")
        self.assertEqual(blocked["meta"]["status"], "blocked")
        self.assertEqual(blocked["meta"]["blocked_reason"], "等外部确认")


class TestCompleteFlow(ActionsTestBase):
    def test_complete_generates_worklog(self):
        t = self.actions.add_task("发周报")
        tid = t["meta"]["id"]
        done = self.actions.complete_task(tid, summary="发完了", time_spent=2)
        # 任务标 done 且挂了 outcome_ref
        self.assertEqual(done["meta"]["status"], "done")
        self.assertTrue(done["meta"]["outcome_ref"].startswith("log-"))
        # 对应 worklog 真的存在,且回指本任务
        from system_os.vault import Vault
        import system_os.config as config
        importlib.reload(config)
        v = Vault(config.work_vault_path())
        log = v.read(done["meta"]["outcome_ref"])
        self.assertEqual(log["meta"]["task_ref"], tid)


class TestDailyReview(ActionsTestBase):
    def test_daily_review_aggregates(self):
        self.actions.add_task("今天建的任务")
        t2 = self.actions.add_task("今天完成的")
        self.actions.complete_task(t2["meta"]["id"], summary="搞定")
        review = self.actions.daily_review()
        self.assertGreaterEqual(len(review["created_tasks"]), 2)
        self.assertGreaterEqual(len(review["done_tasks"]), 1)
        self.assertGreaterEqual(len(review["worklogs"]), 1)


class TestConfigFlip(ActionsTestBase):
    def test_uses_configured_path(self):
        # 验证"配置翻转":WORK_VAULT_PATH 指向临时目录,数据就落在那
        self.actions.add_task("落地测试")
        files = list(Path(self._tmp.name).glob("task-*.md"))
        self.assertEqual(len(files), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
