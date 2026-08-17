"""双机并行:A 方案的测试。

覆盖三块:
1. id 分机编号 —— 新 id 带机器后缀(w/p),且兼容老的纯数字 id 取最大编号
2. 日志分机生成 —— 完成/新增按机器归属,各机只生成自己的 dailylog
3. sync 冲突保双份 —— 用真实 git 仓(本地 bare remote)模拟两台机改同一文件

测试不依赖全局 git 配置(sync 内置提交身份),不依赖网络(remote 是本地目录)。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os import actions, sync  # noqa: E402
from system_os.vault import Vault  # noqa: E402


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True)


# ============================================================
# 1 + 2:id 分机编号 & 日志分机生成(临时目录当 vault,无 git)
# ============================================================
class TestDualMachineIds(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self._tmp.name
        os.environ["MACHINE_ID"] = "work"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("WORK_VAULT_EXPECTED_REMOTE", None)
        os.environ.pop("MACHINE_ID", None)

    def test_new_id_has_machine_suffix(self):
        rec = actions.add_task("第一台机的任务")
        self.assertTrue(rec["meta"]["id"].endswith("w"), rec["meta"]["id"])

    def test_next_id_compatible_with_old_plain_ids(self):
        # 老数据:纯数字 id(task-0093);新数据:带后缀(task-0094w)。取最大编号要两种都认。
        v = Vault(self._tmp.name)
        v.create("task-0093", {"title": "老任务", "status": "todo", "domain": "work"})
        v.create("task-0094w", {"title": "新任务", "status": "todo", "domain": "work"})
        rec = actions.add_task("又一条")
        self.assertEqual(rec["meta"]["id"], "task-0095w")

    def test_suffix_switches_with_machine(self):
        actions.add_task("工作机的")
        os.environ["MACHINE_ID"] = "personal"
        rec = actions.add_task("个人机的")
        self.assertTrue(rec["meta"]["id"].endswith("p"), rec["meta"]["id"])

    def test_toggle_done_stamps_done_machine(self):
        tid = actions.add_task("盖章测试")["meta"]["id"]
        actions.toggle_done(tid)
        rec = Vault(self._tmp.name).read(tid)
        self.assertEqual(rec["meta"].get("done_machine"), "work")
        # 取消完成 → 章清掉
        actions.toggle_done(tid)
        rec = Vault(self._tmp.name).read(tid)
        self.assertIsNone(rec["meta"].get("done_machine"))

    def test_dailylog_per_machine(self):
        # 工作机建并完成一条任务
        tid = actions.add_task("工作机干的活")["meta"]["id"]
        actions.toggle_done(tid)
        today = actions._today()

        # 工作机生成自己的日志:包含这条
        log_w = actions.generate_daily_log(today)
        self.assertEqual(log_w["meta"]["id"], f"dailylog-{today}-w")
        self.assertIn("工作机干的活", log_w["body"])

        # 切到个人机:生成的是另一份日志,完成/新增都不含工作机这条
        os.environ["MACHINE_ID"] = "personal"
        log_p = actions.generate_daily_log(today)
        self.assertEqual(log_p["meta"]["id"], f"dailylog-{today}-p")
        self.assertNotIn("工作机干的活", log_p["body"])

        # 两台机的日志是不同文件,互不覆盖
        v = Vault(self._tmp.name)
        self.assertTrue(v.exists(f"dailylog-{today}-w"))
        self.assertTrue(v.exists(f"dailylog-{today}-p"))


# ============================================================
# 3:sync 冲突保双份(真实 git 仓)
# ============================================================
class TestSyncConflict(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.remote = base / "remote.git"
        _git(base, "init", "--bare", "-b", "main", str(self.remote))
        self.a = base / "machineA"   # 工作机
        _git(base, "clone", str(self.remote), str(self.a))
        os.environ["MACHINE_ID"] = "work"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("WORK_VAULT_EXPECTED_REMOTE", None)
        os.environ.pop("MACHINE_ID", None)

    def _use(self, machine_dir: Path, machine: str) -> None:
        os.environ["WORK_VAULT_PATH"] = str(machine_dir)
        os.environ["WORK_VAULT_EXPECTED_REMOTE"] = str(self.remote)
        os.environ["MACHINE_ID"] = machine

    def test_remote_mismatch_fails_before_staging(self):
        self._use(self.a, "work")
        self._write_task(self.a, "todo")
        os.environ["WORK_VAULT_EXPECTED_REMOTE"] = str(self.remote) + "-other"
        result = sync.sync_now()
        self.assertEqual(result["error"], "work-vault-remote-mismatch")
        staged = _git(self.a, "diff", "--cached", "--name-only").stdout
        self.assertEqual(staged, "")

    def test_private_visibility_failure_keeps_local_commit(self):
        self._use(self.a, "work")
        self._write_task(self.a, "todo")
        original = sync._private_remote_verified
        sync._private_remote_verified = lambda root, remote: (
            False, "remote-visibility-auth-missing"
        )
        try:
            result = sync.sync_now()
        finally:
            sync._private_remote_verified = original
        self.assertTrue(result["committed"])
        self.assertFalse(result["pushed"])
        self.assertEqual(result["error"], "remote-visibility-auth-missing")
        self.assertEqual(_git(self.a, "status", "--porcelain").stdout, "")

    def _write_task(self, root: Path, status: str) -> None:
        (root / "task").mkdir(exist_ok=True)
        (root / "task" / "task-0001.md").write_text(
            f"---\nid: task-0001\nstatus: {status}\n---\n", encoding="utf-8")

    def test_conflict_keeps_both_versions(self):
        # A(工作机)建任务并推上去
        self._use(self.a, "work")
        self._write_task(self.a, "todo")
        r = sync.sync_now()
        self.assertTrue(r["pushed"], r)

        # B(个人机)此刻才克隆(已有数据的仓)——等价于个人机首次部署
        self.b = Path(self._tmp.name) / "machineB"
        _git(Path(self._tmp.name), "clone", str(self.remote), str(self.b))

        # A 把任务改成 done 并推上去
        self._use(self.a, "work")
        self._write_task(self.a, "done")
        r = sync.sync_now()
        self.assertTrue(r["pushed"], r)

        # B 在没拉取的情况下把同一任务改成 blocked(并行写!→ 冲突)
        self._use(self.b, "personal")
        self._write_task(self.b, "blocked")
        r = sync.sync_now()

        # 冲突被识别;本机版(blocked)留正本;对方版(done)存副本;且已推回远端
        self.assertEqual(r["conflicts"], ["task/task-0001.md"], r)
        self.assertIn("blocked", (self.b / "task" / "task-0001.md").read_text())
        copies = list((self.b / "task").glob("*.conflict-*"))
        self.assertEqual(len(copies), 1)
        self.assertIn("done", copies[0].read_text())
        self.assertTrue(r["pushed"], r)
        self.assertEqual(sync.list_conflicts(), [f"task/task-0001.md.conflict-{copies[0].name.split('.conflict-')[1]}"])

        # A 再同步一轮:拿到 B 的解决结果,冲突副本两边都看得见
        self._use(self.a, "work")
        r = sync.sync_now()
        self.assertIn("blocked", (self.a / "task" / "task-0001.md").read_text())
        self.assertEqual(len(list((self.a / "task").glob("*.conflict-*"))), 1)

    def test_parallel_different_files_merge_cleanly(self):
        # A 建任务1并推
        self._use(self.a, "work")
        self._write_task(self.a, "todo")
        sync.sync_now()
        self.b = Path(self._tmp.name) / "machineB"
        _git(Path(self._tmp.name), "clone", str(self.remote), str(self.b))

        # A 加 task-0002w,B 加 task-0002p(撞号不撞名)→ 各自推,自动合并无冲突
        self._write_task(self.a, "todo")
        (self.a / "task" / "task-0002w.md").write_text(
            "---\nid: task-0002w\nstatus: todo\n---\n", encoding="utf-8")
        r_a = sync.sync_now()

        self._use(self.b, "personal")
        (self.b / "task" / "task-0002p.md").write_text(
            "---\nid: task-0002p\nstatus: todo\n---\n", encoding="utf-8")
        r_b = sync.sync_now()

        self.assertEqual(r_b["conflicts"], [])
        self.assertTrue((self.b / "task" / "task-0002w.md").exists())  # B 拉到了 A 的
        self.assertTrue((self.b / "task" / "task-0002p.md").exists())


if __name__ == "__main__":
    unittest.main()


# ============================================================
# 4:日常任务(routine)—— 打卡制、分机归属、日志总结
# ============================================================
class TestRoutines(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self._tmp.name
        os.environ["MACHINE_ID"] = "work"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("MACHINE_ID", None)

    def test_add_and_toggle(self):
        rid = actions.add_routine("健身")["meta"]["id"]
        self.assertTrue(rid.startswith("routine-") and rid.endswith("w"))
        # 勾=今天打卡,再勾=取消
        actions.toggle_routine(rid)
        items = actions.list_routines()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["done_today"])
        self.assertEqual(items[0]["total_days"], 1)
        actions.toggle_routine(rid)
        self.assertFalse(actions.list_routines()[0]["done_today"])

    def test_dailylog_includes_punch(self):
        rid = actions.add_routine("背单词")["meta"]["id"]
        actions.toggle_routine(rid)  # 本机今天打卡
        today = actions._today()
        log = actions.generate_daily_log(today)
        self.assertIn("日常打卡", log["body"])
        self.assertIn("背单词", log["body"])
        # 个人机的日志不含这台机的打卡
        os.environ["MACHINE_ID"] = "personal"
        log_p = actions.generate_daily_log(today)
        self.assertNotIn("背单词", log_p["body"])

    def test_catch_up_counts_punch_days(self):
        # 模拟:昨天打过卡(但没生成日志)→ catch_up 应补上昨天的日志
        rid = actions.add_routine("冥想")["meta"]["id"]
        import datetime as dt
        yesterday = (dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
                     - dt.timedelta(days=1)).date().isoformat()
        v = Vault(self._tmp.name)
        v.update(rid, {"done_log": {yesterday: "work"}})
        gen = actions.catch_up_logs()
        self.assertIn(yesterday, gen)
        log = v.read(f"dailylog-{yesterday}-w")
        self.assertIn("冥想", log["body"])


# ============================================================
# 5:可见性规则 —— 工作机只见本机创建,个人机全见
# ============================================================
class TestVisibility(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self._tmp.name
        os.environ["MACHINE_ID"] = "work"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("MACHINE_ID", None)

    def _make_both_machines_data(self):
        # 工作机创建一条;切到个人机身份再创建一条(模拟个人机同步过来的)
        actions.add_task("工作机的学业任务", category="学业")
        actions.add_routine("工作机的日常")
        os.environ["MACHINE_ID"] = "personal"
        actions.add_task("个人机的学业任务", category="学业")
        actions.add_routine("个人机的日常")

    def test_work_machine_sees_only_own(self):
        self._make_both_machines_data()
        os.environ["MACHINE_ID"] = "work"  # 回到工作机视角
        tree = actions.list_task_tree()
        titles = [n["title"] for n in tree.get("学业", [])]
        self.assertEqual(titles, ["工作机的学业任务"])
        routines = [r["title"] for r in actions.list_routines()]
        self.assertEqual(routines, ["工作机的日常"])

    def test_personal_machine_sees_all(self):
        self._make_both_machines_data()
        # 保持 personal 视角
        tree = actions.list_task_tree()
        titles = sorted(n["title"] for n in tree.get("学业", []))
        self.assertEqual(titles, ["个人机的学业任务", "工作机的学业任务"])
        routines = sorted(r["title"] for r in actions.list_routines())
        self.assertEqual(routines, ["个人机的日常", "工作机的日常"])

    def test_dailylog_in_progress_respects_visibility(self):
        self._make_both_machines_data()
        # 个人机创建的任务在推进中
        os.environ["MACHINE_ID"] = "personal"
        pid = [t for t in actions.list_tasks() if t["meta"]["title"] == "个人机的学业任务"][0]["meta"]["id"]
        actions.toggle_focus(pid)
        # 工作机的日志:推进区不含个人机的任务
        os.environ["MACHINE_ID"] = "work"
        today = actions._today()
        log_w = actions.generate_daily_log(today)
        self.assertNotIn("个人机的学业任务", log_w["body"])
        # 个人机的日志:推进区两机的都有
        os.environ["MACHINE_ID"] = "personal"
        log_p = actions.generate_daily_log(today)
        self.assertIn("个人机的学业任务", log_p["body"])


# ============================================================
# 6:框架仓自动更新(sync_code)—— 仅快进,本地领先则跳过
# ============================================================
class TestCodeSync(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.remote = base / "code-remote.git"
        _git(base, "init", "--bare", "-b", "main", str(self.remote))
        # 用第二个 clone 当"上游推送者"
        self.upstream = base / "upstream"
        _git(base, "clone", str(self.remote), str(self.upstream))
        _git(self.upstream, "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "--allow-empty", "-m", "init")
        _git(self.upstream, "push", "origin", "main")
        # 本机 clone(模拟个人机的 system-code)
        self.local = base / "local-code"
        _git(base, "clone", str(self.remote), str(self.local))
        self._orig_root = sync._CODE_ROOT
        sync._CODE_ROOT = self.local  # 指向测试仓

    def tearDown(self):
        sync._CODE_ROOT = self._orig_root
        self._tmp.cleanup()

    def _upstream_push(self, filename: str, content: str) -> None:
        (self.upstream / filename).write_text(content, encoding="utf-8")
        _git(self.upstream, "add", "-A")
        _git(self.upstream, "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-m", f"add {filename}")
        _git(self.upstream, "push", "origin", "main")

    def test_fast_forward_update(self):
        self._upstream_push("new_feature.py", "# new\n")
        r = sync.sync_code()
        self.assertTrue(r["updated"], r)
        self.assertIn("new_feature.py", r["changed"])
        self.assertTrue((self.local / "new_feature.py").exists())

    def test_up_to_date(self):
        r = sync.sync_code()
        self.assertFalse(r["updated"])
        self.assertIsNone(r["error"])

    def test_local_ahead_skips(self):
        # 本机有未推送提交(开发机场景)→ 跳过,不硬 merge
        (self.local / "local_work.py").write_text("# mine\n", encoding="utf-8")
        _git(self.local, "add", "-A")
        _git(self.local, "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-m", "local wip")
        self._upstream_push("upstream_change.py", "# theirs\n")
        r = sync.sync_code()
        self.assertFalse(r["updated"])
        self.assertIn("领先", r["error"] or "")
        self.assertFalse((self.local / "upstream_change.py").exists())


# ============================================================
# 7:进度型日常任务(target_per_day>1)
# ============================================================
class TestRoutineProgress(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self._tmp.name
        os.environ["MACHINE_ID"] = "work"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("MACHINE_ID", None)

    def test_punch_progress_and_clamp(self):
        rid = actions.add_routine("示例练习", target_per_day=2)["meta"]["id"]
        actions.punch_routine(rid, +1)
        items = actions.list_routines()
        self.assertEqual((items[0]["today_count"], items[0]["done_today"]), (1, False))
        actions.punch_routine(rid, +1)
        items = actions.list_routines()
        self.assertEqual((items[0]["today_count"], items[0]["done_today"]), (2, True))
        # 超过目标被 clamp 在 2
        actions.punch_routine(rid, +1)
        self.assertEqual(actions.list_routines()[0]["today_count"], 2)

    def test_minus_and_zero_cleanup(self):
        rid = actions.add_routine("示例练习", target_per_day=2)["meta"]["id"]
        actions.punch_routine(rid, +1)
        actions.punch_routine(rid, -1)
        rec = Vault(self._tmp.name).read(rid)
        self.assertEqual(rec["meta"].get("done_log"), {})  # 归零清空
        self.assertFalse(actions.list_routines()[0]["done_today"])

    def test_toggle_cycle(self):
        rid = actions.add_routine("晨间准备", target_per_day=2)["meta"]["id"]
        actions.toggle_routine(rid)  # 0→1
        self.assertEqual(actions.list_routines()[0]["today_count"], 1)
        actions.toggle_routine(rid)  # 1→2 满
        self.assertTrue(actions.list_routines()[0]["done_today"])
        actions.toggle_routine(rid)  # 满→0 清零
        self.assertEqual(actions.list_routines()[0]["today_count"], 0)

    def test_legacy_single_punch_compatible(self):
        # 旧形态 done_log {日期: "work"} 正常识别为完成 1 次
        rid = actions.add_routine("健身")["meta"]["id"]
        today = actions._today()
        Vault(self._tmp.name).update(rid, {"done_log": {today: "work"}})
        items = actions.list_routines()
        self.assertTrue(items[0]["done_today"])
        self.assertEqual(items[0]["today_count"], 1)

    def test_dailylog_shows_progress(self):
        rid = actions.add_routine("示例练习", target_per_day=2)["meta"]["id"]
        actions.punch_routine(rid, +1)  # 本机 1 次
        today = actions._today()
        log = actions.generate_daily_log(today)
        self.assertIn("示例练习 1/2", log["body"])
        # 个人机也打一次 → 全天凑满,两边日志都显示 ✓
        os.environ["MACHINE_ID"] = "personal"
        actions.punch_routine(rid, +1)
        os.environ["MACHINE_ID"] = "work"
        log = actions.generate_daily_log(today, overwrite=True)
        self.assertIn("示例练习 ✓", log["body"])


# ============================================================
# 8:常驻任务(standing)—— 容器永不隐藏
# ============================================================
class TestStanding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WORK_VAULT_PATH"] = self._tmp.name
        os.environ["MACHINE_ID"] = "work"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("WORK_VAULT_PATH", None)
        os.environ.pop("MACHINE_ID", None)

    def test_add_and_set_standing(self):
        tid = actions.add_task("娱乐", standing=True)["meta"]["id"]
        rec = Vault(self._tmp.name).read(tid)
        self.assertTrue(rec["meta"]["standing"])
        # 取消常驻
        actions.set_standing(tid, False)
        rec = Vault(self._tmp.name).read(tid)
        self.assertFalse(rec["meta"]["standing"])

    def test_tree_node_carries_flag(self):
        tid = actions.add_task("系统日志")["meta"]["id"]
        actions.set_standing(tid, True)
        tree = actions.list_task_tree()
        node = tree["事业"][0] if "事业" in tree else None
        self.assertIsNotNone(node)
        self.assertTrue(node["standing"])
