"""actions.py —— 高层工具层(agent 的"手")。

【它是什么】
在底层 vault store(CRUD)之上,包一层"贴近人话意图"的操作。
系统 agent(Claude/Cursor/OpenClaw)读手册后,就调用这里的函数来干活。

【和底层的区别】
- vault.py:通用增删改查,不懂"任务""优先级"。
- actions.py:懂业务——add_task 会自动生成 id、填时间戳、按机器身份填 domain、
  跑 schema 校验、状态流转检查。agent 调它比直接拼 frontmatter 省事且不易错。

【谁调用它】
不是用户手敲,是 agent 替用户调。用户只说"帮我记个任务:明天写周报",
agent 理解后调 add_task(title="明天写周报", ...)。

【数据存哪】
由 config 决定:默认 fixtures(开发),.env 配了 WORK_VAULT_PATH 就用真实仓。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from . import config
from .machine import current_domain
from .schema_core import validate_decision, validate_rule
from .schema_work import (
    check_transition,
    validate_planning,
    validate_task,
    validate_worklog,
)
from .vault import Vault


# ============================================================
# 内部工具
# ============================================================
def _work_vault() -> Vault:
    return Vault(config.work_vault_path())


def _today() -> str:
    """今天日期 YYYY-MM-DD。注:此处用于给记录盖当天日期。"""
    return _dt.date.today().isoformat()


def _next_id(vault: Vault, prefix: str) -> str:
    """生成下一个顺序 id,如 task-0001。扫描现有同前缀记录取最大编号+1。"""
    max_n = 0
    for rec in vault.list():
        rid = rec["meta"].get("id", "")
        if rid.startswith(prefix + "-"):
            tail = rid.rsplit("-", 1)[-1]
            if tail.isdigit():
                max_n = max(max_n, int(tail))
    return f"{prefix}-{max_n + 1:04d}"


# ============================================================
# 任务(task)
# ============================================================
def add_task(
    title: str,
    *,
    priority: str = "P2",
    category: str = "事业",
    energy_cost: str = "medium",
    due: str | None = None,
    scheduled: str | None = None,
    depends_on: list[str] | None = None,
    body: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """新建一条任务。返回创建的记录。

    agent 场景:用户说"要做 X" → 调本函数。
    自动:生成 id、填 domain(按机器身份)、status=todo、跑校验。
    """
    vault = _work_vault()
    meta: dict[str, Any] = {
        "id": _next_id(vault, "task"),
        "title": title,
        "status": "todo",
        "priority": priority,
        "category": category,
        "energy_cost": energy_cost,
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    if due:
        meta["due"] = due
    if scheduled:
        meta["scheduled"] = scheduled
    if depends_on:
        meta["depends_on"] = depends_on
    meta.update(extra)

    validate_task(meta)  # 存前校验,不合法直接报错
    return vault.create(meta["id"], meta, body)


def list_tasks(
    *,
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
) -> list[dict[str, Any]]:
    """列出任务,可按状态/分类/优先级过滤。返回记录列表(已排序:P0在前)。

    agent 场景:用户问"我有哪些待办""这周事业类的任务"。
    """
    where: dict[str, Any] = {}
    if status:
        where["status"] = status
    if category:
        where["category"] = category
    if priority:
        where["priority"] = priority
    recs = [r for r in _work_vault().list(where=where or None)
            # 只挑真正的 task(排除 worklog/planning 等混在同目录的情况)
            if str(r["meta"].get("id", "")).startswith("task-")]
    # 按优先级排序(P0 最前),同级按 id
    recs.sort(key=lambda r: (r["meta"].get("priority", "P9"), r["meta"].get("id", "")))
    return recs


def start_task(task_id: str) -> dict[str, Any]:
    """把任务标为进行中。会检查依赖:depends_on 未全 done 时拒绝(状态机规则)。

    agent 场景:用户说"我开始做 X 了"。
    """
    vault = _work_vault()
    rec = vault.read(task_id)
    # 收集依赖任务的当前状态,交给状态机校验
    dep_status = {}
    for dep in rec["meta"].get("depends_on", []) or []:
        if vault.exists(dep):
            dep_status[dep] = vault.read(dep)["meta"].get("status")
    check_transition(rec["meta"], "in_progress", dep_status)
    return vault.update(task_id, {"status": "in_progress"})


def block_task(task_id: str, reason: str) -> dict[str, Any]:
    """把任务标为阻塞,必须给原因(状态机规则)。

    agent 场景:用户说"X 卡住了,因为……"。
    """
    vault = _work_vault()
    meta_patch = {"status": "blocked", "blocked_reason": reason}
    merged = {**vault.read(task_id)["meta"], **meta_patch}
    validate_task(merged)  # 会强制 blocked 必带 reason
    return vault.update(task_id, meta_patch)


def complete_task(
    task_id: str,
    *,
    summary: str | None = None,
    what_done: str = "",
    time_spent: float | None = None,
    energy_actual: str | None = None,
) -> dict[str, Any]:
    """完成任务:标 done,并自动生成一条 worklog(做过的事),用 outcome_ref 挂钩。

    agent 场景:用户说"X 做完了"。
    这体现 task→worklog 的流转:要做的事完成后,沉淀成做过的事。
    """
    vault = _work_vault()
    task = vault.read(task_id)
    tmeta = task["meta"]

    # 生成配套 worklog
    log_id = _next_id(vault, "log")
    log_meta = {
        "id": log_id,
        "task_ref": task_id,
        "date": _today(),
        "summary": summary or tmeta.get("title", "完成任务"),
        "category": tmeta.get("category", "事业"),
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    if time_spent is not None:
        log_meta["time_spent"] = time_spent
    if energy_actual:
        log_meta["energy_actual"] = energy_actual
    validate_worklog(log_meta)
    vault.create(log_id, log_meta, what_done)

    # 任务标完成,回填 outcome_ref
    return vault.update(task_id, {"status": "done", "outcome_ref": log_id})


# ============================================================
# 工作日志(worklog)—— 无对应任务的临时工作也能直接记
# ============================================================
def add_worklog(
    summary: str,
    *,
    category: str = "事业",
    what_done: str = "",
    task_ref: str | None = None,
    time_spent: float | None = None,
    energy_actual: str | None = None,
    rule_candidates: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """直接记一条工作日志(不一定对应某个任务)。

    agent 场景:用户说"记一下:今天临时帮同事调了个 bug"。
    """
    vault = _work_vault()
    meta: dict[str, Any] = {
        "id": _next_id(vault, "log"),
        "date": _today(),
        "summary": summary,
        "category": category,
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    if task_ref:
        meta["task_ref"] = task_ref
    if time_spent is not None:
        meta["time_spent"] = time_spent
    if energy_actual:
        meta["energy_actual"] = energy_actual
    if rule_candidates:
        meta["rule_candidates"] = rule_candidates
    meta.update(extra)

    validate_worklog(meta)
    return vault.create(meta["id"], meta, what_done)


# ============================================================
# 每日回顾(聚合视图)—— 用户明确要的活
# ============================================================
def daily_review(date: str | None = None) -> dict[str, Any]:
    """聚合某天的动态:当天新建/完成的任务 + 当天的 worklog。

    agent 场景:用户说"今天回顾一下"。
    返回结构化数据,由 agent 组织成人话/表格呈现(底层分格存、上层聚合看)。
    """
    day = date or _today()
    vault = _work_vault()
    done_today, created_today, logs_today = [], [], []
    for rec in vault.list():
        m = rec["meta"]
        rid = str(m.get("id", ""))
        if rid.startswith("log-") and m.get("date") == day:
            logs_today.append(rec)
        elif rid.startswith("task-"):
            if m.get("status") == "done" and str(m.get("updated_at", "")).startswith(day):
                done_today.append(rec)
            if str(m.get("created_at", "")).startswith(day):
                created_today.append(rec)
    return {
        "date": day,
        "created_tasks": created_today,
        "done_tasks": done_today,
        "worklogs": logs_today,
    }
