"""通用 Agent 闭环、专项根授权和外挂工作区测试。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os import actions  # noqa: E402
from system_os.agent_workspace import write_text_artifact, workspace_root  # noqa: E402
from system_os.entity import ValidationError  # noqa: E402
from system_os.executors import get_agent_profile  # noqa: E402
from system_os.schema_work import validate_task  # noqa: E402
from system_os.vault import Vault  # noqa: E402


def _task(task_id: str, title: str, **extra):
    meta = {
        "id": task_id,
        "title": title,
        "status": "todo",
        "priority": "P1",
        "category": "学业",
        "energy_cost": "medium",
        "domain": "personal",
        "source_machine": "personal",
        "executor": "user",
    }
    meta.update(extra)
    return meta


class TestAgentWorkflow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._workspace = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self._tmp.name
        os.environ["MACHINE_ID"] = "personal"
        os.environ["INTERNSHIP_AGENT_ROOT_ID"] = "task-9000p"
        os.environ["INTERNSHIP_WORKSPACE_PATH"] = self._workspace.name
        self.vault = Vault(self._tmp.name)
        self.vault.create(
            "task-9000p", _task("task-9000p", "求职专项", standing=True))
        self.vault.create(
            "task-9100p", _task(
                "task-9100p", "脱敏简历", parent="task-9000p"), "初始说明")
        self.vault.create(
            "task-9101p", _task("task-9101p", "根外任务", category="生活"))

    def tearDown(self):
        self._workspace.cleanup()
        self._tmp.cleanup()
        for key in (
            "WORK_VAULT_PATH", "MACHINE_ID", "INTERNSHIP_AGENT_ROOT_ID",
            "INTERNSHIP_WORKSPACE_PATH",
        ):
            os.environ.pop(key, None)

    def test_executor_schema_is_explicit_and_extensible_in_registry(self):
        valid = _task("task-1", "合法", executor="internship_agent")
        validate_task(valid)
        invalid = _task("task-2", "非法", executor="mystery_agent")
        with self.assertRaisesRegex(ValidationError, "executor 非法"):
            validate_task(invalid)

    def test_agent_root_reads_runtime_env_and_has_safe_default(self):
        profile = get_agent_profile("internship_agent")
        self.assertEqual(profile.resolved_root_id(), "task-9000p")
        os.environ.pop("INTERNSHIP_AGENT_ROOT_ID")
        self.assertEqual(profile.resolved_root_id(), "task-demo-career-root")
        os.environ["INTERNSHIP_AGENT_ROOT_ID"] = "task-9001p"
        self.assertEqual(profile.resolved_root_id(), "task-9001p")
        os.environ["INTERNSHIP_AGENT_ROOT_ID"] = "task-9000p"

    def test_internship_full_review_cycle_generates_worklog(self):
        actions.propose_agent_task("task-9100p", executor="internship_agent")
        self.assertEqual(self.vault.read("task-9100p")["meta"]["status"], "pending_start")

        actions.approve_agent_task("task-9100p", executor="internship_agent")
        actions.request_agent_decision(
            "task-9100p", "采用一页版吗？", executor="internship_agent")
        queue = actions.list_agent_queue("internship_agent")
        self.assertEqual([x["id"] for x in queue["pending_decision"]], ["task-9100p"])
        self.assertEqual(queue["pending_decision"][0]["agent_label"], "实习攻略")

        actions.answer_agent_decision(
            "task-9100p", "采用一页版", executor="internship_agent")
        actions.submit_agent_review(
            "task-9100p", "已生成脱敏版本", executor="internship_agent")
        review = actions.list_review_queue()
        self.assertEqual([x["id"] for x in review["pending_review"]], ["task-9100p"])

        result = actions.accept_agent_task("task-9100p", executor="internship_agent")
        self.assertEqual(result["meta"]["status"], "done")
        outcome = result["meta"]["outcome_ref"]
        log = self.vault.read(outcome)
        self.assertEqual(log["meta"]["task_ref"], "task-9100p")
        self.assertIn("实习攻略验收通过", log["meta"]["summary"])

    def test_scope_blocks_outside_task_and_root_override(self):
        with self.assertRaisesRegex(ValidationError, "无权操作"):
            actions.propose_agent_task("task-9101p", executor="internship_agent")
        with self.assertRaisesRegex(ValidationError, "只允许任务根"):
            actions.propose_agent_task(
                "task-9101p", executor="internship_agent", root_id="task-9101p")

    def test_executor_cannot_take_task_owned_by_other_agent(self):
        self.vault.update("task-9100p", {"executor": "dev_agent"})
        with self.assertRaisesRegex(ValidationError, "已分配给 dev_agent"):
            actions.propose_agent_task("task-9100p", executor="internship_agent")

    def test_queue_filters_executor_and_root(self):
        self.vault.update("task-9100p", {
            "executor": "internship_agent", "status": "in_progress"})
        self.vault.update("task-9101p", {
            "executor": "internship_agent", "status": "in_progress"})
        queue = actions.list_agent_queue("internship_agent")
        self.assertEqual([x["id"] for x in queue["in_progress"]], ["task-9100p"])

    def test_direct_task_controls_cannot_bypass_agent_workflow(self):
        actions.propose_agent_task("task-9100p", executor="internship_agent")
        for operation in (
            lambda: actions.start_task("task-9100p"),
            lambda: actions.toggle_focus("task-9100p"),
            lambda: actions.toggle_done("task-9100p"),
            lambda: actions.complete_task("task-9100p"),
            lambda: actions.block_task("task-9100p", "绕过流程"),
        ):
            with self.assertRaisesRegex(ValidationError, "审核流程"):
                operation()

    def test_user_can_confirm_takeover_and_complete_agent_task(self):
        actions.propose_agent_task("task-9100p", executor="internship_agent")
        actions.approve_agent_task("task-9100p", executor="internship_agent")
        with self.assertRaisesRegex(ValidationError, "必须明确确认"):
            actions.take_over_agent_task("task-9100p")

        done = actions.take_over_agent_task(
            "task-9100p", confirmed_by_user=True)
        self.assertEqual(done["meta"]["status"], "done")
        self.assertEqual(done["meta"]["executor"], "user")
        self.assertEqual(done["meta"]["taken_over_from"], "internship_agent")
        self.assertEqual(done["meta"]["completion_actor"], "user")
        self.assertEqual(
            actions.list_agent_queue("internship_agent")["in_progress"], [])
        log = self.vault.read(done["meta"]["outcome_ref"])
        self.assertEqual(log["meta"]["task_ref"], "task-9100p")
        self.assertIn("中途接管", log["body"])

    def test_takeover_os_api_requires_confirmation(self):
        from system_os.os_api import _run
        actions.propose_agent_task("task-9100p", executor="internship_agent")
        actions.approve_agent_task("task-9100p", executor="internship_agent")
        with self.assertRaisesRegex(ValidationError, "必须明确确认"):
            _run("agent_takeover_complete", {"id": "task-9100p"})
        result = _run("agent_takeover_complete", {
            "id": "task-9100p", "confirmed_by_user": True})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "done")
        self.assertEqual(result["data"]["taken_over_from"], "internship_agent")

    def test_parent_toggle_cannot_complete_agent_descendant(self):
        actions.propose_agent_task("task-9100p", executor="internship_agent")
        with self.assertRaisesRegex(ValidationError, "审核流程"):
            actions.toggle_done("task-9000p")
        self.assertEqual(self.vault.read("task-9000p")["meta"]["status"], "todo")
        self.assertEqual(
            self.vault.read("task-9100p")["meta"]["status"], "pending_start")

    def test_completed_agent_descendant_does_not_block_parent_completion(self):
        actions.propose_agent_task("task-9100p", executor="internship_agent")
        actions.approve_agent_task("task-9100p", executor="internship_agent")
        actions.submit_agent_review(
            "task-9100p", "完成", executor="internship_agent")
        actions.accept_agent_task("task-9100p", executor="internship_agent")
        parent = actions.toggle_done("task-9000p")
        self.assertEqual(parent["meta"]["status"], "done")
        self.assertEqual(self.vault.read("task-9100p")["meta"]["status"], "done")
        self.assertEqual(
            self.vault.read("task-9100p")["meta"]["executor"], "internship_agent")

    def test_scoped_agent_task_creation_requires_registered_root(self):
        with self.assertRaisesRegex(ValidationError, "必须位于 task-9000p"):
            actions.add_task("越界新任务", executor="internship_agent")
        created = actions.add_task(
            "根内新任务", parent="task-9000p", executor="internship_agent")
        self.assertEqual(created["meta"]["parent"], "task-9000p")
        self.assertEqual(created["meta"]["executor"], "internship_agent")

    def test_dev_agent_compatibility_wrappers_still_work(self):
        self.vault.create("task-0300p", _task(
            "task-0300p", "系统开发", category="系统"))
        actions.propose_task("task-0300p")
        self.assertEqual(
            [x["id"] for x in actions.list_dev_queue()["pending_start"]],
            ["task-0300p"],
        )
        actions.approve_task("task-0300p")
        actions.submit_for_review("task-0300p", "兼容包装通过")
        result = actions.accept_task("task-0300p")
        self.assertEqual(result["meta"]["status"], "done")

    def test_workspace_write_and_boundary(self):
        root = Path(self._workspace.name).resolve()
        self.assertEqual(workspace_root("internship_agent"), root)
        artifact = write_text_artifact(
            "internship_agent", "_system_test/summary.md", "脱敏测试产物\n")
        self.assertEqual(artifact.read_text(encoding="utf-8"), "脱敏测试产物\n")
        with self.assertRaisesRegex(ValueError, "越过"):
            write_text_artifact("internship_agent", "../outside.md", "no")
        with self.assertRaisesRegex(ValueError, "未配置外挂工作区"):
            workspace_root("dev_agent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
