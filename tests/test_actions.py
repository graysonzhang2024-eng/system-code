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
from unittest.mock import patch

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

    def test_unblock_returns_task_to_todo(self):
        t = self.actions.add_task("阻塞后恢复")
        self.actions.block_task(t["meta"]["id"], reason="等待条件")
        unblocked = self.actions.unblock_task(t["meta"]["id"])
        self.assertEqual(unblocked["meta"]["status"], "todo")
        self.assertEqual(unblocked["meta"]["blocked_reason"], "")

    def test_task_moves_between_backlog_today_and_focus(self):
        task = self.actions.add_task("三层流转")
        tid = task["meta"]["id"]

        today = self.actions.set_task_layer(tid, "today")
        self.assertEqual(today["meta"]["status"], "todo")
        self.assertEqual(today["meta"]["today_date"], self.actions._today())

        focus = self.actions.set_task_layer(tid, "focus")
        self.assertEqual(focus["meta"]["status"], "in_progress")
        self.assertEqual(focus["meta"]["today_date"], self.actions._today())

        demoted = self.actions.set_task_layer(tid, "today")
        self.assertEqual(demoted["meta"]["status"], "todo")
        backlog = self.actions.set_task_layer(tid, "backlog")
        self.assertEqual(backlog["meta"]["today_date"], "")

    def test_focus_layer_keeps_dependency_guard(self):
        dep = self.actions.add_task("前置")
        main = self.actions.add_task("后置", depends_on=[dep["meta"]["id"]])
        self.actions.set_task_layer(main["meta"]["id"], "today")
        with self.assertRaisesRegex(ValidationError, "依赖未完成"):
            self.actions.set_task_layer(main["meta"]["id"], "focus")

    def test_task_layer_rejects_parent_and_agent_task(self):
        parent = self.actions.add_task("父任务")
        self.actions.add_subtask(parent["meta"]["id"], "子任务")
        with self.assertRaisesRegex(ValidationError, "叶子任务"):
            self.actions.set_task_layer(parent["meta"]["id"], "today")

        agent = self.actions.add_task("Agent 任务", category="系统", executor="dev_agent")
        with self.assertRaisesRegex(ValidationError, "系统开发管理"):
            self.actions.set_task_layer(agent["meta"]["id"], "today")

    def test_set_layer_os_api_returns_layer_and_date(self):
        from system_os.os_api import _run
        task = self.actions.add_task("桥接今日待办")
        result = _run("set_layer", {"id": task["meta"]["id"], "layer": "today"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["layer"], "today")
        self.assertEqual(result["data"]["today_date"], self.actions._today())

    def test_tree_exposes_today_date_without_expiring_data(self):
        task = self.actions.add_task("昨日缓存", today_date="2026-08-11")
        tree = self.actions.list_task_tree()
        node = tree["事业"][0]
        self.assertEqual(node["id"], task["meta"]["id"])
        self.assertEqual(node["today_date"], "2026-08-11")


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

    def test_record_completed_task_creates_done_task_and_worklog(self):
        done = self.actions.record_completed_task(
            "临时修复线上问题",
            category="事业",
            summary="问题已修复",
            what_done="定位并修复配置错误。",
            time_spent=0.5,
        )
        self.assertEqual(done["meta"]["status"], "done")
        self.assertEqual(done["meta"]["executor"], "user")
        self.assertEqual(done["meta"]["done_machine"], "work")

        from system_os.vault import Vault
        import system_os.config as config
        importlib.reload(config)
        vault = Vault(config.work_vault_path())
        log = vault.read(done["meta"]["outcome_ref"])
        self.assertEqual(log["meta"]["task_ref"], done["meta"]["id"])
        self.assertEqual(log["meta"]["summary"], "问题已修复")
        self.assertEqual(log["meta"]["time_spent"], 0.5)
        self.assertIn("定位并修复", log["body"])

    def test_record_completed_task_is_in_daily_review_not_todo(self):
        done = self.actions.record_completed_task("计划外完成事项", category="系统")
        review = self.actions.daily_review()
        self.assertIn(done["meta"]["id"], {
            rec["meta"]["id"] for rec in review["done_tasks"]})
        self.assertIn(done["meta"]["outcome_ref"], {
            rec["meta"]["id"] for rec in review["worklogs"]})
        self.assertNotIn(done["meta"]["id"], {
            rec["meta"]["id"] for rec in self.actions.list_tasks(status="todo")})

    def test_record_completed_task_cannot_create_agent_task(self):
        with self.assertRaisesRegex(ValidationError, "必须走批准与验收闭环"):
            self.actions.record_completed_task(
                "不能绕过验收", executor="internship_agent")

    def test_add_done_os_api_returns_completed_task(self):
        from system_os.os_api import _run
        result = _run("add_done", {
            "title": "桥接补录测试",
            "category": "系统",
            "what_done": "验证 JSON 桥返回完成状态。",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "done")
        self.assertTrue(result["data"]["outcome_ref"].startswith("log-"))

    def test_record_completed_task_syncs_once(self):
        with patch.object(self.actions, "_sync_after") as sync_after:
            self.actions.record_completed_task("一次性补录")
        sync_after.assert_called_once()


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
        # (任务按类型存 task/ 子目录,用 rglob 递归查找)
        self.actions.add_task("落地测试")
        files = list(Path(self._tmp.name).rglob("task-*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent.name, "task")  # 确认存进了 task/ 子目录


if __name__ == "__main__":
    unittest.main(verbosity=2)
