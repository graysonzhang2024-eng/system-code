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
import functools
import re
from typing import Any

from . import config
from . import sync
from .entity import ValidationError
from .executors import AGENT_PROFILES, USER_EXECUTOR, executor_label, get_agent_profile
from .machine import current_domain, machine_letter
from .schema_knowledge import validate_knowledge, validate_knowledge_note
from .schema_core import validate_decision, validate_rule
from .schema_work import (
    check_transition,
    validate_planning,
    validate_task,
    validate_worklog,
)
from .routed_vault import RoutedVault
from .vault import Vault


# ============================================================
# 内部工具
# ============================================================
def _work_vault() -> RoutedVault:
    return RoutedVault()


_BEIJING = _dt.timezone(_dt.timedelta(hours=8))


def _bj_now() -> _dt.datetime:
    """当前北京时间。"""
    return _dt.datetime.now(_BEIJING)


def _today() -> str:
    """今天日期 YYYY-MM-DD(北京时间)。用于给记录盖当天日期。"""
    return _bj_now().date().isoformat()


def _date_of(iso_ts: str) -> str:
    """把一个 ISO 时间戳(带时区,通常 UTC)转成北京时间的日期 YYYY-MM-DD。"""
    if not iso_ts:
        return ""
    try:
        dt = _dt.datetime.fromisoformat(iso_ts)
    except ValueError:
        return iso_ts[:10]  # 兜底:直接取前10位
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_BEIJING).date().isoformat()


def _next_id(vault: Vault, prefix: str) -> str:
    """生成下一个顺序 id,带机器后缀,如 task-0001w / task-0001p。

    后缀(机器标识字母 w/p)是双机并行写的防撞设计:两台机各自新建记录时,
    编号可能相同(都数到 94),但 w/p 后缀让最终 id 不同,git 合并不撞路径。
    扫描现有记录取最大编号时,兼容老的纯数字 id(task-0093)和新的带后缀 id。
    """
    max_n = 0
    for rec in vault.list():
        rid = rec["meta"].get("id", "")
        if rid.startswith(prefix + "-"):
            tail = rid.rsplit("-", 1)[-1]
            m = re.fullmatch(r"(\d+)[wp]?", tail)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f"{prefix}-{max_n + 1:04d}{machine_letter()}"


# ============================================================
# 写入即同步(双机并行)
# ============================================================
def _sync_after(msg: str) -> None:
    """写操作后的自动同步:本地 commit + 触发后台 push。

    绝不向调用方抛错——同步失败(断网等)不影响写操作本身,
    数据已在本地,下一轮同步会补上。
    """
    try:
        if sync.commit_all(f"auto({sync.machine_tag()}): {msg}"):
            sync.push_detached()
        sync.commit_personal(f"auto({sync.machine_tag()}): {msg}")
    except Exception:
        pass


def _synced(func):
    """装饰器:让 actions 里的变更函数在完成后自动同步一次。

    一个逻辑操作(如勾父任务连带 N 个后代)只 commit 一次,不会产生提交碎片。
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        hint = str(args[0])[:40] if args else ""
        _sync_after(f"{func.__name__} {hint}".strip())
        return result
    return wrapper


# ============================================================
# 可见性规则(展示层隐私)
# ============================================================
def _visible(m: dict[str, Any]) -> bool:
    """这条记录在当前机器上可不可见。

    规则(用户 2026-08-03 拍板):
    - 工作机:只看本机创建的(source_machine=work)。个人机创建的任务——
      哪怕分类是学业/事业/系统——也不显示。
    - 个人机:全部可见(它是唯一的聚合端,人际/生活也只有它看得见)。

    注意:这是"显示层"隐身(防误触/防旁人目光),不是数据隔离——
    文件两台机都有(git 同步全量)。老数据没有 source_machine 时按 work 处理
    (双机功能出现前的所有记录都是在工作机创建的)。
    """
    if current_domain() == "personal":
        return True
    return (m.get("source_machine") or "work") == "work"


def _require_user_managed_task(meta: dict[str, Any], action: str) -> None:
    """防止普通勾选/专注 API 绕过 Agent 的批准与验收闭环。"""
    executor = meta.get("executor", USER_EXECUTOR)
    if executor != USER_EXECUTOR:
        raise ValidationError(
            f"{meta.get('id')} 由 {executor_label(executor)}管理，不能直接{action};请走 Agent 审核流程"
        )


# ============================================================
# 日常任务(routine)—— 每天一样、打卡制、自动刷新
# ============================================================
def _normalize_done_log(log: Any) -> dict[str, dict[str, int]]:
    """把 done_log 统一成 {日期: {机器: 次数}}。

    兼容两种历史形态:
    - 旧版单次打卡:{日期: "work"} → {日期: {"work": 1}}
    - 新版进度打卡:{日期: {"work": 1, "personal": 1}} → 原样
    """
    out: dict[str, dict[str, int]] = {}
    for date, val in (log or {}).items():
        if isinstance(val, str):
            out[date] = {val: 1}
        elif isinstance(val, dict):
            out[date] = {k: int(v) for k, v in val.items()}
    return out


@_synced
def add_routine(
    title: str,
    *,
    category: str = "生活",
    period: str = "daily",
    target_per_day: int = 1,
    body: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """新建一条日常任务。每天都一样:勾选=给今天打卡,新的一天自动恢复未勾。

    存在的意义:①提醒每天(广义:周期性)要做的事;②打卡历史留在记录里,
    每日日志据此总结——界面天天刷新,但日志里有迹可循。
    target_per_day:每天要打卡几次(默认1)。>1 即进度型,如示例练习一天两次(0/2→2/2)。
    period 目前只实现 daily;结构上留 weekly/custom 扩展口。
    """
    vault = _work_vault()
    meta: dict[str, Any] = {
        "id": _next_id(vault, "routine"),
        "title": title,
        "kind": "routine",
        "period": period,
        "target_per_day": int(target_per_day),
        "category": category,
        "done_log": {},  # {日期: {机器: 次数}} —— 进度打卡
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    meta.update(extra)
    return vault.create(meta["id"], meta, body)


@_synced
def punch_routine(routine_id: str, delta: int = 1) -> dict[str, Any]:
    """给今天的打卡 +1 / -1(delta),次数 clamp 在 [0, target_per_day]。

    次数记在当前机器名下(哪台机打的算哪台的,日志分机归属用)。
    归零时清掉当天记录(保持数据干净)。
    """
    vault = _work_vault()
    rec = vault.read(routine_id)
    m = rec["meta"]
    target = int(m.get("target_per_day") or 1)
    log = _normalize_done_log(m.get("done_log"))
    today = _today()
    day = dict(log.get(today, {}))
    new = max(0, min(target, day.get(current_domain(), 0) + delta))
    if new == 0:
        day.pop(current_domain(), None)
    else:
        day[current_domain()] = new
    if day:
        log[today] = day
    else:
        log.pop(today, None)
    return vault.update(routine_id, {"done_log": log})


@_synced
def toggle_routine(routine_id: str) -> dict[str, Any]:
    """点一下的循环语义:没满 +1;满了(达到当日目标)清零。

    单击任务(target=1)就是原来的 勾→取消 手感;
    进度任务(target>1)是 0→1→…→满→0。精确减 1 用 punch_routine(id, -1)。
    """
    rec = _work_vault().read(routine_id)
    m = rec["meta"]
    target = int(m.get("target_per_day") or 1)
    today_total = sum(_normalize_done_log(m.get("done_log")).get(_today(), {}).values())
    if today_total >= target:
        # 满了 → 清零(撤销全天)
        log = _normalize_done_log(m.get("done_log"))
        log.pop(_today(), None)
        return _work_vault().update(routine_id, {"done_log": log})
    return punch_routine(routine_id, +1)


def list_routines() -> list[dict[str, Any]]:
    """所有日常任务 + 今日进度(北京时间),供浮窗渲染。"""
    today = _today()
    out: list[dict[str, Any]] = []
    for rec in _work_vault().list():
        m = rec["meta"]
        rid = str(m.get("id", ""))
        if not rid.startswith("routine-"):
            continue
        if not _visible(m):
            continue
        log = _normalize_done_log(m.get("done_log"))
        target = int(m.get("target_per_day") or 1)
        today_count = sum(log.get(today, {}).values())
        out.append({
            "id": rid,
            "title": m.get("title", ""),
            "category": m.get("category", "生活"),
            "target": target,
            "today_count": today_count,
            "done_today": today_count >= target,
            # 累计"达标天数"(打满目标的天数)
            "total_days": sum(1 for day in log.values() if sum(day.values()) >= target),
        })
    out.sort(key=lambda r: r["id"])
    return out


# ============================================================
# 任务(task)
# ============================================================
@_synced
def add_task(
    title: str,
    *,
    priority: str = "P2",
    category: str = "事业",
    energy_cost: str = "medium",
    due: str | None = None,
    scheduled: str | None = None,
    depends_on: list[str] | None = None,
    standing: bool = False,
    body: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """新建一条任务。返回创建的记录。

    agent 场景:用户说"要做 X" → 调本函数。
    自动:生成 id、填 domain(按机器身份)、status=todo、跑校验。
    standing=True 即常驻任务:容器/分区性质,永不因完成或过期而从浮窗隐藏。
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
    if standing:
        meta["standing"] = True
    meta.update(extra)

    executor = meta.get("executor", USER_EXECUTOR)
    if executor != USER_EXECUTOR:
        root_id = _resolved_agent_root(executor)
        if root_id:
            meta_by_id = {
                str(rec["meta"].get("id", "")): rec["meta"]
                for rec in vault.list()
                if str(rec["meta"].get("id", "")).startswith("task-")
            }
            meta_by_id[meta["id"]] = meta
            if not _task_in_root(meta["id"], root_id, meta_by_id):
                raise ValidationError(
                    f"{executor} 新任务必须位于 {root_id} 子树内"
                )

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
            # 且遵守可见性规则(工作机不见个人机创建的任务)
            if str(r["meta"].get("id", "")).startswith("task-") and _visible(r["meta"])]
    # 按优先级排序(P0 最前),同级按 id
    recs.sort(key=lambda r: (r["meta"].get("priority", "P9"), r["meta"].get("id", "")))
    return recs


@_synced
def start_task(task_id: str) -> dict[str, Any]:
    """把任务标为进行中。会检查依赖:depends_on 未全 done 时拒绝(状态机规则)。

    agent 场景:用户说"我开始做 X 了"。
    """
    vault = _work_vault()
    rec = vault.read(task_id)
    _require_user_managed_task(rec["meta"], "直接开始")
    # 收集依赖任务的当前状态,交给状态机校验
    dep_status = {}
    for dep in rec["meta"].get("depends_on", []) or []:
        if vault.exists(dep):
            dep_status[dep] = vault.read(dep)["meta"].get("status")
    check_transition(rec["meta"], "in_progress", dep_status)
    return vault.update(task_id, {"status": "in_progress", "today_date": _today()})


@_synced
def block_task(task_id: str, reason: str) -> dict[str, Any]:
    """把任务标为阻塞,必须给原因(状态机规则)。

    agent 场景:用户说"X 卡住了,因为……"。
    """
    vault = _work_vault()
    _require_user_managed_task(vault.read(task_id)["meta"], "直接阻塞")
    meta_patch = {"status": "blocked", "blocked_reason": reason}
    merged = {**vault.read(task_id)["meta"], **meta_patch}
    validate_task(merged)  # 会强制 blocked 必带 reason
    return vault.update(task_id, meta_patch)


@_synced
def unblock_task(task_id: str) -> dict[str, Any]:
    """解除普通用户任务的阻塞并退回 todo；Agent 任务仍须走专用闭环。"""
    vault = _work_vault()
    rec = vault.read(task_id)
    _require_user_managed_task(rec["meta"], "直接解除阻塞")
    if rec["meta"].get("status") != "blocked":
        raise ValidationError(f"{task_id} 当前不是 blocked")
    patch = {"status": "todo", "blocked_reason": ""}
    validate_task({**rec["meta"], **patch})
    return vault.update(task_id, patch)


def _complete_task_record(
    vault: Vault,
    task_id: str,
    *,
    summary: str | None = None,
    what_done: str = "",
    time_spent: float | None = None,
    energy_actual: str | None = None,
    task_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """内部原子步骤：生成 worklog 并完成任务；调用方负责身份授权与同步。"""
    task = vault.read(task_id)
    tmeta = task["meta"]

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

    patch = dict(task_patch or {})
    patch.update({
        "status": "done", "outcome_ref": log_id, "done_machine": current_domain()})
    return vault.update(task_id, patch)


@_synced
def complete_task(
    task_id: str,
    *,
    summary: str | None = None,
    what_done: str = "",
    time_spent: float | None = None,
    energy_actual: str | None = None,
    _agent_accept: bool = False,
) -> dict[str, Any]:
    """完成普通任务并自动生成 worklog；Agent 任务默认拒绝直接完成。"""
    vault = _work_vault()
    tmeta = vault.read(task_id)["meta"]
    if not _agent_accept:
        _require_user_managed_task(tmeta, "直接完成")
    return _complete_task_record(
        vault,
        task_id,
        summary=summary,
        what_done=what_done,
        time_spent=time_spent,
        energy_actual=energy_actual,
    )


@_synced
def take_over_agent_task(
    task_id: str,
    *,
    confirmed_by_user: bool = False,
    summary: str | None = None,
    what_done: str = "",
) -> dict[str, Any]:
    """用户从 Agent 中途接管并确认完成任务。

    这是浮窗明确确认后的专用入口，不开放给 Agent 自行调用。它保留原执行器来源，
    将任务交回 user 并生成 worklog；普通 toggle/complete 仍不能绕过 Agent 闭环。
    """
    if not confirmed_by_user:
        raise ValidationError("用户接管 Agent 任务前必须明确确认")
    vault = _work_vault()
    meta = vault.read(task_id)["meta"]
    executor = meta.get("executor", USER_EXECUTOR)
    if executor == USER_EXECUTOR:
        raise ValidationError(f"{task_id} 不是 Agent 任务，无需接管")
    if meta.get("status") in {"done", "cancelled"}:
        raise ValidationError(f"{task_id} 已结束，不能重复接管完成")
    label = executor_label(executor)
    detail = what_done.strip() or f"用户从{label}中途接管，并在浮窗中手动确认完成。"
    return _complete_task_record(
        vault,
        task_id,
        summary=summary or f"用户接管完成：{meta.get('title', task_id)}",
        what_done=detail,
        task_patch={
            "executor": USER_EXECUTOR,
            "taken_over_from": executor,
            "completion_actor": USER_EXECUTOR,
        },
    )


@_synced
def record_completed_task(
    title: str,
    *,
    priority: str = "P2",
    category: str = "事业",
    energy_cost: str = "medium",
    summary: str | None = None,
    what_done: str = "",
    time_spent: float | None = None,
    energy_actual: str | None = None,
    body: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """补录一件计划外但已经完成的事，同时建立 done task 和关联 worklog。

    agent 场景：用户说“我刚临时做完 X”或在汇总时提到此前没建任务的完成事项。
    调用前应先查现有任务/日志，避免把已记录事项重复补录。本动作只服务用户事项，
    不能借此绕过专项 Agent 的批准与验收闭环。
    """
    vault = _work_vault()
    requested_executor = extra.get("executor", USER_EXECUTOR)
    if requested_executor != USER_EXECUTOR:
        raise ValidationError(
            "计划外完成事项只能补录为用户任务，Agent 任务必须走批准与验收闭环"
        )
    task_id = _next_id(vault, "task")
    log_id = _next_id(vault, "log")

    task_meta: dict[str, Any] = {
        "id": task_id,
        "title": title,
        "status": "done",
        "priority": priority,
        "category": category,
        "energy_cost": energy_cost,
        "domain": current_domain(),
        "source_machine": current_domain(),
        "executor": USER_EXECUTOR,
        "outcome_ref": log_id,
        "done_machine": current_domain(),
    }
    task_meta.update(extra)
    # 身份、完成状态与关联记录由本动作负责，调用方不能用 extra 改写这些安全字段。
    task_meta.update({
        "id": task_id,
        "title": title,
        "status": "done",
        "executor": USER_EXECUTOR,
        "outcome_ref": log_id,
        "done_machine": current_domain(),
        "domain": current_domain(),
        "source_machine": current_domain(),
    })

    log_meta: dict[str, Any] = {
        "id": log_id,
        "task_ref": task_id,
        "date": _today(),
        "summary": summary or title,
        "category": category,
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    if time_spent is not None:
        log_meta["time_spent"] = time_spent
    if energy_actual:
        log_meta["energy_actual"] = energy_actual

    # 两份记录都先校验，再落盘；装饰器在整个动作结束后只同步一次。
    validate_task(task_meta)
    validate_worklog(log_meta)
    task = vault.create(task_id, task_meta, body)
    vault.create(log_id, log_meta, what_done)
    return task


# ============================================================
# 工作日志(worklog)—— 纯事实/过程记录可直接记；已完成行动用 record_completed_task
# ============================================================
@_synced
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
        elif rid.startswith("task-") and _visible(m):
            if m.get("status") == "done" and _date_of(m.get("updated_at", "")) == day:
                done_today.append(rec)
            if _date_of(m.get("created_at", "")) == day:
                created_today.append(rec)
    return {
        "date": day,
        "created_tasks": created_today,
        "done_tasks": done_today,
        "worklogs": logs_today,
    }


# ============================================================
# 子任务树 & 前端交互 API(供浮窗 UI 使用)
# ============================================================
@_synced
def add_subtask(parent_id: str, title: str, **kw: Any) -> dict[str, Any]:
    """在某任务下加子任务。子任务也是一条 task,靠 parent 字段挂到父任务。

    继承父任务的 category(同类),其余字段可覆盖。
    规则:加子任务后,父任务(及祖先)若为 done 或 in_progress,自动拉回 todo——
    done 是因为又有新活;in_progress 是因为有了子任务就不是叶子,自动移出专注区。
    """
    vault = _work_vault()
    parent = vault.read(parent_id)["meta"]
    kw.setdefault("category", parent.get("category", "事业"))
    kw.setdefault("executor", parent.get("executor", USER_EXECUTOR))
    kw["parent"] = parent_id
    rec = add_task(title, **kw)
    _normalize_ancestors(vault, parent_id)
    return rec


def _normalize_ancestors(vault: "Vault", task_id: str | None) -> None:
    """规整 task_id 及其所有祖先的状态(沿 parent 链向上):

    - done 的祖先 → 拉回 todo(又有新活要干,不该算已完成)
    - in_progress 的祖先 → 拉回 todo(有了子任务就不是叶子,自动移出专注区)
    父任务的完成/推进应由子任务决定,这里保证状态一致。
    """
    seen: set[str] = set()
    while task_id and task_id not in seen:
        seen.add(task_id)
        try:
            meta = vault.read(task_id)["meta"]
        except FileNotFoundError:
            return
        if meta.get("status") in ("done", "in_progress"):
            vault.update(task_id, {"status": "todo", "outcome_ref": None})
        task_id = meta.get("parent")


@_synced
def toggle_done(task_id: str) -> dict[str, Any]:
    """切换任务完成状态(done <-> todo)。浮窗勾选框调用它。

    父子联动:勾父任务完成 → 所有后代子任务一起标完成;
    取消父任务 → 所有后代一起退回未完成。避免"父已完成但进度不满"的矛盾。
    注:轻量操作,不走严格状态机。
    标 done 时盖 done_machine(哪台机完成的),供每日日志分机归属。
    """
    vault = _work_vault()
    current = vault.read(task_id)["meta"]
    _require_user_managed_task(current, "勾选完成")
    cur = current.get("status")
    new_status = "todo" if cur == "done" else "done"
    # 本任务 + 所有后代(递归)一起改
    affected_ids = [task_id] + _descendant_ids(vault, task_id)
    for tid in affected_ids:
        meta = vault.read(tid)["meta"]
        # 已经处于目标状态的 Agent 后代无需改写，不应继续阻塞父任务完成。
        if meta.get("status") == new_status:
            continue
        _require_user_managed_task(meta, "随父任务勾选完成")
    for tid in affected_ids:
        if vault.read(tid)["meta"].get("status") == new_status:
            continue
        patch: dict[str, Any] = {"status": new_status}
        patch["done_machine"] = current_domain() if new_status == "done" else None
        vault.update(tid, patch)
    return vault.read(task_id)


def _descendant_ids(vault: "Vault", task_id: str) -> list[str]:
    """返回 task_id 所有后代的 id(递归,所有层级)。"""
    # 建 parent -> [children] 索引
    children: dict[str, list[str]] = {}
    for rec in vault.list():
        m = rec["meta"]
        tid = str(m.get("id", ""))
        if not tid.startswith("task-"):
            continue
        p = m.get("parent")
        if p:
            children.setdefault(p, []).append(tid)
    out: list[str] = []
    stack = list(children.get(task_id, []))
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children.get(cur, []))
    return out


@_synced
def toggle_focus(task_id: str) -> dict[str, Any]:
    """兼容入口：todo → 专注，专注 → 今日待办。

    新浮窗使用 set_task_layer 做显式三层流转；旧客户端继续调用本函数也不会
    把退出专注的任务直接丢回总待办。
    已完成(done)的任务不响应(专注区不含已完成)。
    """
    vault = _work_vault()
    current = vault.read(task_id)["meta"]
    _require_user_managed_task(current, "切换专注")
    cur = current.get("status")
    if cur == "done":
        return vault.read(task_id)  # 已完成不改
    if cur not in {"todo", "in_progress"}:
        raise ValidationError(f"{task_id} 当前状态为 {cur}，不能切换专注")
    if cur == "in_progress":
        return vault.update(task_id, {"status": "todo", "today_date": _today()})
    dep_status = {
        dep: vault.read(dep)["meta"].get("status")
        for dep in current.get("depends_on", []) or [] if vault.exists(dep)
    }
    check_transition(current, "in_progress", dep_status)
    return vault.update(task_id, {"status": "in_progress", "today_date": _today()})


@_synced
def set_task_layer(task_id: str, layer: str) -> dict[str, Any]:
    """把用户叶子任务显式放入 backlog / today / focus 三层之一。

    today_date 是按北京时间写入的缓存标记，次日无需批量改文件便会自然失效。
    focus 仍由 status=in_progress 表达；保留 today_date 使其可一键退回今日待办。
    Agent 任务及父任务不进入这套用户工作记忆层。
    """
    if layer not in {"backlog", "today", "focus"}:
        raise ValidationError(f"任务层级非法:{layer!r}")
    vault = _work_vault()
    rec = vault.read(task_id)
    current = rec["meta"]
    _require_user_managed_task(current, "调整任务层级")
    status = current.get("status")
    if status not in {"todo", "in_progress"}:
        raise ValidationError(f"{task_id} 当前状态为 {status}，不能调整任务层级")
    has_children = any(
        r["meta"].get("parent") == task_id
        for r in vault.list()
        if str(r["meta"].get("id", "")).startswith("task-")
        and r["meta"].get("status") != "cancelled"
    )
    if has_children:
        raise ValidationError("今日待办和专注中只接收可直接执行的叶子任务")

    patch: dict[str, Any]
    if layer == "backlog":
        patch = {"status": "todo", "today_date": ""}
    elif layer == "today":
        patch = {"status": "todo", "today_date": _today()}
    else:
        dep_status = {
            dep: vault.read(dep)["meta"].get("status")
            for dep in current.get("depends_on", []) or [] if vault.exists(dep)
        }
        check_transition(current, "in_progress", dep_status)
        patch = {"status": "in_progress", "today_date": _today()}
    validate_task({**current, **patch})
    return vault.update(task_id, patch)


@_synced
def set_standing(task_id: str, standing: bool = True) -> dict[str, Any]:
    """设置/取消常驻任务。常驻=容器性质:子任务全完成、任务过期也不从浮窗隐藏,
    始终显示在原分类位置(如『娱乐』『系统日志』这种固定分区)。
    standing=False 退回普通任务。"""
    return _work_vault().update(task_id, {"standing": bool(standing)})


def list_task_tree(*, include_done: bool = True) -> dict[str, list[dict[str, Any]]]:
    """把 work-vault 的所有 task 组装成 {分类: [任务树]} 供浮窗渲染。

    - 扁平的 task(靠 parent 字段)在这里被组装成父子树。
    - 每个节点:{id, title, done, category, sensitive, priority, children: [...]}。
    - 顶层按分类(category)分组。
    返回结构直接对应前端 renderer 需要的形状。
    """
    vault = _work_vault()
    nodes: dict[str, dict[str, Any]] = {}
    # 1. 收集所有 task,转成节点
    for rec in vault.list():
        m = rec["meta"]
        tid = str(m.get("id", ""))
        if not tid.startswith("task-"):
            continue
        if not _visible(m):  # 工作机不见个人机创建的任务(父被滤则子连带成孤儿隐藏)
            continue
        if not include_done and m.get("status") == "done":
            continue
        # cancelled(已取消)的任务不进待办界面(文件仍保留)
        if m.get("status") == "cancelled":
            continue
        nodes[tid] = {
            "id": tid,
            "title": m.get("title", ""),
            "done": m.get("status") == "done",
            "status": m.get("status"),
            "category": m.get("category", "事业"),
            "priority": m.get("priority", "P2"),
            "sensitive": bool(m.get("sensitive", False)),
            "standing": bool(m.get("standing", False)),  # 常驻容器:不折叠、不隐藏
            "executor": m.get("executor", USER_EXECUTOR),
            "agent_label": executor_label(m.get("executor", USER_EXECUTOR)),
            "parent": m.get("parent"),
            "depends_on": m.get("depends_on") or [],
            # 今日待办按北京时间自然日生效；过期值保留历史但前端不会展示。
            "today_date": m.get("today_date") or "",
            # 完成日期(北京时间),供浮窗过滤"今天/昨天/更早完成";未完成为 ""
            "done_date": _date_of(m.get("updated_at", "")) if m.get("status") == "done" else "",
            "children": [],
        }
    # 2. 按 parent 组装成树
    #    有 parent 的:父在则挂父下;父不在(被取消/过滤)则连带隐藏该孤儿,不提为顶层。
    #    无 parent 的:作为顶层。
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        p = node.get("parent")
        if p:
            if p in nodes:
                nodes[p]["children"].append(node)
            # else: 父不在(被 cancelled 等),孤儿不显示
        else:
            roots.append(node)
    # 3. 顶层按分类分组
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for node in roots:
        by_cat.setdefault(node["category"], []).append(node)
    # 每组按优先级排序
    for cat in by_cat:
        by_cat[cat].sort(key=lambda n: (n.get("priority", "P9"), n.get("id", "")))
    return by_cat



# ============================================================
# 每日任务日志(自动统计) + 补偿 —— 分机生成
# ============================================================
def _owns_done(m: dict[str, Any]) -> bool:
    """这条"完成"归不归本机:done_machine(在哪台机勾的)优先,
    缺省回落 source_machine(老数据没有 done_machine 时的合理猜测)。"""
    return (m.get("done_machine") or m.get("source_machine")) == current_domain()


def _owns_created(m: dict[str, Any]) -> bool:
    """这条"新增"归不归本机:看 source_machine(在哪台机创建的)。"""
    return (m.get("source_machine") or current_domain()) == current_domain()


def _dailylog_id(date: str) -> str:
    """每日日志 id 带机器后缀:dailylog-2026-08-03-w / -p。

    双机各生成各的日志(完成/新增本就归属不同机器),互不覆盖,git 不撞。
    跨机整合视图是后续单独的功能(用户决定逻辑)。
    """
    return f"dailylog-{date}-{machine_letter()}"


@_synced
def generate_daily_log(date: str, *, overwrite: bool = False) -> dict[str, Any] | None:
    """为某一天(北京时间 YYYY-MM-DD)生成本机的任务日志,存入 worklog/。

    定位(用户 2026-08-04 拍板):日志 = 当天待办树的干净快照——完成了什么、
    新加了什么、还剩什么。不是 system log,不堆技术细节。
    版式:
      完成(用户任务按分类分组,各 Agent 按执行器标签单独成组列最后)
      随手记录(当日直记的 worklog,可省)
      日常打卡(有打卡才出现;进度显示 ✓ 或 1/2)
      新增待办(当日完成的标 🆕 不再重复列)
      收工快照(仍在推进明细 + 各分类剩余数)
    幂等:同一天本机已有日志且 overwrite=False 时跳过(返回 None)。
    """
    vault = _work_vault()
    log_id = _dailylog_id(date)
    if vault.exists(log_id) and not overwrite:
        return None

    # —— 收集 ——
    all_tasks: dict[str, dict[str, Any]] = {}   # 可见 task,供父标题/层级查找
    done: list[dict[str, Any]] = []             # 本机当日完成
    created_ids: set[str] = set()               # 本机当日新增
    created_pending: list[dict[str, Any]] = []  # 本机当日新增且未完成
    in_prog: list[dict[str, Any]] = []          # 可见的仍在推进
    remain_by_cat: dict[str, int] = {}          # 各分类剩余(未完成/未取消)
    punched: list[str] = []
    jottings: list[str] = []

    for rec in vault.list():
        m = rec["meta"]
        rid = str(m.get("id", ""))
        # 日常任务:本机当日有打卡才收录(没有则整节省略)
        if rid.startswith("routine-"):
            day = _normalize_done_log(m.get("done_log")).get(date, {})
            if _visible(m) and day.get(current_domain(), 0) > 0:
                target = int(m.get("target_per_day") or 1)
                total = sum(day.values())
                mark = "✓" if total >= target else f"{total}/{target}"
                punched.append(f"{m.get('title', '')} {mark}")
            continue
        # 直记 worklog(不挂任务的"做过的事")按书写机归属;挂任务的由完成节覆盖
        if rid.startswith("log-"):
            if m.get("date") == date and not m.get("task_ref") \
                    and m.get("source_machine") == current_domain():
                jottings.append(m.get("summary", ""))
            continue
        if not rid.startswith("task-") or not _visible(m):
            continue

        all_tasks[rid] = m
        st = m.get("status")
        is_done_today = st == "done" and _date_of(m.get("updated_at", "")) == date
        if is_done_today and _owns_done(m):
            done.append(m)
        if _date_of(m.get("created_at", "")) == date and _owns_created(m):
            created_ids.add(rid)
            if not is_done_today:
                created_pending.append(m)
        if st == "in_progress":
            in_prog.append(m)
        if st not in ("done", "cancelled"):
            cat = m.get("category", "事业")
            executor = m.get("executor", USER_EXECUTOR)
            key = executor_label(executor) if executor != USER_EXECUTOR else cat
            remain_by_cat[key] = remain_by_cat.get(key, 0) + 1

    # —— 完成节:分组 + 父子缩进 ——
    def render_done_group(items: list[dict[str, Any]], lines: list[str]) -> None:
        ids = {m["id"] for m in items}
        kids: dict[str, list[dict[str, Any]]] = {}
        for m in items:
            if m.get("parent") in ids:
                kids.setdefault(m["parent"], []).append(m)

        def has_done_ancestor(m: dict[str, Any]) -> bool:
            p = m.get("parent")
            while p:
                if p in ids:
                    return True
                p = all_tasks.get(p, {}).get("parent")
            return False

        def render(m: dict[str, Any], depth: int) -> None:
            title = m.get("title", "")
            p = m.get("parent")
            # 父不在本组(父未完成)→ 带父标题前缀,保留来龙去脉
            if p and p in all_tasks and p not in ids:
                title = f"{all_tasks[p].get('title', '')} / {title}"
            mark = " 🆕" if m["id"] in created_ids else ""
            lines.append("  " * depth + f"- {title}{mark}")
            for c in sorted(kids.get(m["id"], []), key=lambda x: x.get("title", "")):
                render(c, depth + 1)

        for root in sorted((m for m in items if not has_done_ancestor(m)),
                           key=lambda x: x.get("title", "")):
            render(root, 0)

    agent_done: dict[str, list[dict[str, Any]]] = {}
    usr_done: list[dict[str, Any]] = []
    for m in done:
        executor = m.get("executor", USER_EXECUTOR)
        if executor == USER_EXECUTOR:
            usr_done.append(m)
        else:
            agent_done.setdefault(executor, []).append(m)
    # 用户任务按分类分组(固定顺序),Agent 组列最后
    CAT_ORDER = ["事业", "学业", "人际", "生活", "系统"]
    usr_by_cat: dict[str, list[dict[str, Any]]] = {}
    for m in usr_done:
        usr_by_cat.setdefault(m.get("category", "事业"), []).append(m)

    # —— 组装正文 ——
    lines = [f"# 任务日志 {date}({current_domain()}机)", ""]
    n_done = len(done)
    lines.append(f"## 完成 ({n_done})")
    if not done:
        lines.append("- (无)")
    for cat in CAT_ORDER:
        group = usr_by_cat.get(cat)
        if group:
            lines.append(f"### {cat} ({len(group)})")
            render_done_group(group, lines)
    for executor in AGENT_PROFILES:
        group = agent_done.get(executor)
        if group:
            label = executor_label(executor)
            lines.append(f"### {label} ({len(group)})")
            render_done_group(group, lines)

    if jottings:
        lines += ["", f"## 随手记录 ({len(jottings)})"]
        lines += [f"- {s}" for s in jottings]

    if punched:
        lines += ["", f"## 日常打卡 ({len(punched)})"]
        lines += [f"- {t}" for t in punched]

    lines += ["", f"## 新增待办 ({len(created_ids)})"]
    if not created_ids:
        lines.append("- (无)")
    else:
        for m in sorted(created_pending, key=lambda x: x.get("id", "")):
            executor = m.get("executor", USER_EXECUTOR)
            tag = executor_label(executor) if executor != USER_EXECUTOR else m.get("category", "事业")
            lines.append(f"- [{tag}] {m.get('title', '')}")
        n_done_new = len(created_ids) - len(created_pending)
        if n_done_new:
            lines.append(f"- (另有 {n_done_new} 条当日已完成,见完成节 🆕)")

    lines += ["", f"## 收工快照"]
    lines.append(f"### 仍在推进 ({len(in_prog)})")
    lines += [
        f"- [{executor_label(m.get('executor')) if m.get('executor', USER_EXECUTOR) != USER_EXECUTOR else m.get('category','事业')}] {m.get('title','')}"
        for m in in_prog
    ] or ["- (无)"]
    if remain_by_cat:
        order = CAT_ORDER + [p.label for p in AGENT_PROFILES.values()]
        parts = [f"{k} {remain_by_cat[k]}" for k in order if k in remain_by_cat]
        lines.append(f"### 剩余待办:{' · '.join(parts)}")

    body = "\n".join(lines)

    meta = {
        "id": log_id,
        "date": date,
        "summary": f"{date} {current_domain()}机任务日志:完成{len(done)}·新增{len(created_ids)}·推进{len(in_prog)}",
        "category": "系统",
        "domain": current_domain(),
        "source_machine": current_domain(),
        "kind": "daily",  # 标记为每日任务日志,区别于普通 worklog
    }
    return vault.create(log_id, meta, body, overwrite=overwrite)


@_synced
def catch_up_logs(*, days_back: int = 30) -> list[str]:
    """补偿式生成:检查过去 days_back 天里所有"本机有活动但缺本机日志"的日期,补齐。

    只补"昨天及更早"的日期(今天还没过完,不生成今天的)。
    只关心本机的活动(本机创建/本机完成),别机的日志别机自己生成。
    返回本次新生成的日期列表。用于浮窗启动/管家启动时调用,兼容关机跨天。
    """
    vault = _work_vault()
    today = _bj_now().date()
    # 收集本机活动过的日期:本机创建/本机完成的任务 + 本机打卡的日常任务
    active_dates: set[str] = set()
    for rec in vault.list():
        m = rec["meta"]
        rid = str(m.get("id", ""))
        if rid.startswith("routine-"):
            for d, day in _normalize_done_log(m.get("done_log")).items():
                if day.get(current_domain(), 0) > 0:
                    active_dates.add(d)
            continue
        if not rid.startswith("task-"):
            continue
        if _owns_created(m):
            d = _date_of(m.get("created_at") or "")
            if d:
                active_dates.add(d)
        if m.get("status") == "done" and _owns_done(m):
            d = _date_of(m.get("updated_at") or "")
            if d:
                active_dates.add(d)

    generated: list[str] = []
    for i in range(1, days_back + 1):  # 从昨天往前
        d = (today - _dt.timedelta(days=i)).isoformat()
        if d in active_dates and not vault.exists(_dailylog_id(d)):
            if generate_daily_log(d):
                generated.append(d)
    return generated


# ============================================================
# 知识库(knowledge item + knowledge note)
# ============================================================
@_synced
def add_knowledge(
    title: str,
    *,
    kind: str = "other",
    status: str = "want",
    priority: str = "P2",
    category: str = "学业",
    creator: str = "",
    source_url: str = "",
    published_on: str | None = None,
    learned_on: str | None = None,
    duration_minutes: int | float | None = None,
    rating: int | None = None,
    tags: list[str] | None = None,
    body: str = "",
) -> dict[str, Any]:
    """记录一个想学或已经学过的内容；正文保存条目概述。"""
    vault = _work_vault()
    meta: dict[str, Any] = {
        "id": _next_id(vault, "knowledge"),
        "title": title.strip(),
        "kind": kind,
        "status": status,
        "priority": priority,
        "category": category,
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    if creator.strip():
        meta["creator"] = creator.strip()
    if source_url.strip():
        meta["source_url"] = source_url.strip()
    if published_on:
        meta["published_on"] = published_on
    if learned_on:
        meta["learned_on"] = learned_on
    elif status == "learned":
        meta["learned_on"] = _today()
    if duration_minutes is not None:
        meta["duration_minutes"] = duration_minutes
    if rating is not None:
        meta["rating"] = rating
    if tags:
        meta["tags"] = tags
    validate_knowledge(meta)
    return vault.create(meta["id"], meta, body)


@_synced
def update_knowledge(
    knowledge_id: str,
    *,
    status: str | None = None,
    priority: str | None = None,
    rating: int | None = None,
    learned_on: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """更新学习状态、优先级、评分或概述；供 Agent 与知识库窗口共用。"""
    vault = _work_vault()
    rec = vault.read(knowledge_id)
    if not str(rec["meta"].get("id", "")).startswith("knowledge-"):
        raise ValidationError(f"不是 knowledge 条目:{knowledge_id}")
    patch: dict[str, Any] = {}
    if status is not None:
        patch["status"] = status
        if status == "learned" and not (learned_on or rec["meta"].get("learned_on")):
            patch["learned_on"] = _today()
    if priority is not None:
        patch["priority"] = priority
    if rating is not None:
        patch["rating"] = rating
    if learned_on is not None:
        patch["learned_on"] = learned_on
    merged = {**rec["meta"], **patch}
    validate_knowledge(merged)
    return vault.update(knowledge_id, patch, body=body)


@_synced
def add_knowledge_note(
    knowledge_id: str,
    content: str,
    *,
    note_type: str = "insight",
    title: str = "",
    captured_on: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """给具体学习条目追加一条笔记、思考、疑问或行动。"""
    content = content.strip()
    if not content:
        raise ValidationError("知识笔记内容不能为空")
    vault = _work_vault()
    if not vault.exists(knowledge_id):
        raise ValidationError(f"知识条目不存在:{knowledge_id}")
    item = vault.read(knowledge_id)
    if not str(item["meta"].get("id", "")).startswith("knowledge-"):
        raise ValidationError(f"knowledge_ref 非法:{knowledge_id}")
    meta: dict[str, Any] = {
        "id": _next_id(vault, "knote"),
        "knowledge_ref": knowledge_id,
        "note_type": note_type,
        "captured_on": captured_on or _today(),
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    if title.strip():
        meta["title"] = title.strip()
    if tags:
        meta["tags"] = tags
    validate_knowledge_note(meta)
    return vault.create(meta["id"], meta, content)


def list_knowledge(
    *,
    status: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """返回可见知识条目及其笔记，供对话查询与知识库窗口展示。"""
    vault = _work_vault()
    notes_by_item: dict[str, list[dict[str, Any]]] = {}
    items: list[dict[str, Any]] = []
    for rec in vault.list():
        meta = rec["meta"]
        rid = str(meta.get("id", ""))
        if not _visible(meta):
            continue
        if rid.startswith("knote-"):
            validate_knowledge_note(meta)
            notes_by_item.setdefault(meta["knowledge_ref"], []).append({
                **meta, "body": rec.get("body", "")})
        elif rid.startswith("knowledge-"):
            validate_knowledge(meta)
            if status and meta.get("status") != status:
                continue
            if kind and meta.get("kind") != kind:
                continue
            items.append({**meta, "body": rec.get("body", "")})
    for values in notes_by_item.values():
        values.sort(key=lambda n: (n.get("captured_on", ""), n.get("id", "")), reverse=True)
    for item in items:
        item["notes"] = notes_by_item.get(item["id"], [])

    status_order = {"learning": 0, "want": 1, "learned": 2, "archived": 3}
    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        learned_ord = 0
        if item.get("learned_on"):
            try:
                learned_ord = -_dt.date.fromisoformat(item["learned_on"]).toordinal()
            except ValueError:
                pass
        return (
            status_order.get(item.get("status"), 9),
            learned_ord if item.get("status") == "learned" else 0,
            item.get("priority", "P9"),
            item.get("id", ""),
        )
    items.sort(key=sort_key)
    return items


# ============================================================
# 规则(rule)—— 沉淀经验/约定,跨对话生效
# ============================================================
@_synced
def add_rule(
    statement: str,
    *,
    trigger: str = "",
    rationale: str = "",
    category: str = "系统",
    status: str = "candidate",
    confidence: str = "medium",
    failure_modes: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    tags: list[str] | None = None,
    body: str = "",
) -> dict[str, Any]:
    """新建一条规则。规范化取代手写 markdown。

    自动:生成 id(rule-YYYY-NNNN)、填 domain/时间戳、跑 schema 校验。
    status 默认 candidate(候选);经验证后可改 validated。
    """
    vault = _work_vault()
    meta: dict[str, Any] = {
        "id": _next_id(vault, "rule"),
        "statement": statement,
        "status": status,
        "category": category,
        "confidence": confidence,
        "domain": current_domain(),
        "source_machine": current_domain(),
    }
    if trigger:
        meta["trigger"] = trigger
    if rationale:
        meta["rationale"] = rationale
    if failure_modes:
        meta["failure_modes"] = failure_modes
    if evidence_refs:
        meta["evidence_refs"] = evidence_refs
    if tags:
        meta["tags"] = tags

    validate_rule(meta)  # 存前校验,格式不对直接报错
    return vault.create(meta["id"], meta, body)


def list_rules(*, status: str | None = None) -> list[dict[str, Any]]:
    """列出所有规则(可按 status 过滤)。供管家分类/决策前查阅、复盘时回顾。"""
    out = []
    for rec in _work_vault().list():
        rid = str(rec["meta"].get("id", ""))
        if not rid.startswith("rule-"):
            continue
        if status and rec["meta"].get("status") != status:
            continue
        out.append(rec)
    out.sort(key=lambda r: r["meta"].get("id", ""))
    return out


# ============================================================
# 通用 Agent 协作流程(执行器 + 任务根双重授权)
# ============================================================
_PENDING_AGENT_STATUSES = ("pending_review", "pending_decision", "pending_start")
_AGENT_QUEUE_STATUSES = (*_PENDING_AGENT_STATUSES, "in_progress")


def _resolved_agent_root(executor: str, root_id: str | None = None) -> str | None:
    """解析执行器的有效根；专项 Agent 不能用参数改写注册表中的安全边界。"""
    profile = get_agent_profile(executor)
    configured_root = profile.resolved_root_id()
    if configured_root:
        if root_id and root_id != configured_root:
            raise ValidationError(
                f"{executor} 只允许任务根 {configured_root},不能改为 {root_id}"
            )
        return configured_root
    return root_id


def _task_in_root(
    task_id: str,
    root_id: str | None,
    meta_by_id: dict[str, dict[str, Any]],
) -> bool:
    if not root_id:
        return True
    current: str | None = task_id
    seen: set[str] = set()
    while current and current not in seen:
        if current == root_id:
            return True
        seen.add(current)
        current = meta_by_id.get(current, {}).get("parent")
    return False


def _authorize_agent_task(
    vault: Vault,
    task_id: str,
    executor: str,
    *,
    root_id: str | None = None,
    allow_unassigned: bool = False,
) -> dict[str, Any]:
    """校验执行器身份和祖先范围，返回任务记录。"""
    root_id = _resolved_agent_root(executor, root_id)
    rec = vault.read(task_id)
    meta = rec["meta"]
    if not str(meta.get("id", "")).startswith("task-"):
        raise ValidationError(f"Agent 流程只接受 task:{task_id}")

    assigned = meta.get("executor", USER_EXECUTOR)
    allowed_assignees = {executor}
    if allow_unassigned:
        allowed_assignees.add(USER_EXECUTOR)
    if assigned not in allowed_assignees:
        raise ValidationError(
            f"{task_id} 已分配给 {assigned},不能由 {executor} 操作"
        )

    meta_by_id = {
        str(r["meta"].get("id", "")): r["meta"]
        for r in vault.list()
        if str(r["meta"].get("id", "")).startswith("task-")
    }
    if not _task_in_root(task_id, root_id, meta_by_id):
        raise ValidationError(
            f"{executor} 无权操作 {task_id};允许范围是 {root_id} 子树"
        )
    return rec


def _require_status(meta: dict[str, Any], expected: str) -> None:
    if meta.get("status") != expected:
        raise ValidationError(
            f"{meta.get('id')} 当前状态为 {meta.get('status')},要求 {expected}"
        )


def _agent_update(vault: Vault, task_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    merged = {**vault.read(task_id)["meta"], **patch}
    validate_task(merged)
    return vault.update(task_id, patch)


@_synced
def propose_agent_task(
    task_id: str,
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    """Agent 提议领取一个 todo；专项 Agent 必须同时落在授权根子树内。"""
    vault = _work_vault()
    rec = _authorize_agent_task(
        vault, task_id, executor, root_id=root_id, allow_unassigned=True)
    _require_status(rec["meta"], "todo")
    return _agent_update(vault, task_id, {
        "status": "pending_start", "executor": executor})


@_synced
def approve_agent_task(
    task_id: str,
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    """用户批准 Agent 开始；依赖未完成时仍拒绝进入 in_progress。"""
    vault = _work_vault()
    rec = _authorize_agent_task(vault, task_id, executor, root_id=root_id)
    _require_status(rec["meta"], "pending_start")
    dep_status = {}
    for dep in rec["meta"].get("depends_on", []) or []:
        if vault.exists(dep):
            dep_status[dep] = vault.read(dep)["meta"].get("status")
    check_transition(rec["meta"], "in_progress", dep_status)
    return _agent_update(vault, task_id, {
        "status": "in_progress", "executor": executor})


@_synced
def request_agent_decision(
    task_id: str,
    question: str,
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    vault = _work_vault()
    rec = _authorize_agent_task(vault, task_id, executor, root_id=root_id)
    _require_status(rec["meta"], "in_progress")
    if not question.strip():
        raise ValidationError("待决策问题不能为空")
    return _agent_update(vault, task_id, {
        "status": "pending_decision", "executor": executor,
        "decision_needed": question.strip(),
    })


@_synced
def submit_agent_review(
    task_id: str,
    note: str = "",
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    vault = _work_vault()
    rec = _authorize_agent_task(vault, task_id, executor, root_id=root_id)
    _require_status(rec["meta"], "in_progress")
    patch: dict[str, Any] = {"status": "pending_review", "executor": executor}
    if note:
        patch["review_note"] = note
    return _agent_update(vault, task_id, patch)


def accept_agent_task(
    task_id: str,
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    vault = _work_vault()
    rec = _authorize_agent_task(vault, task_id, executor, root_id=root_id)
    _require_status(rec["meta"], "pending_review")
    return complete_task(
        task_id,
        summary=f"{executor_label(executor)}验收通过",
        _agent_accept=True,
    )


def list_agent_queue(
    executor: str,
    *,
    root_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """返回某 Agent 的待处理与执行中任务；按 executor 和授权根双重过滤。"""
    root_id = _resolved_agent_root(executor, root_id)
    buckets: dict[str, list[dict[str, Any]]] = {
        status: [] for status in _AGENT_QUEUE_STATUSES}
    all_recs = list(_work_vault().list())
    meta_by_id = {
        str(r["meta"].get("id", "")): r["meta"]
        for r in all_recs
        if str(r["meta"].get("id", "")).startswith("task-")
    }
    kids: dict[str, list[dict[str, Any]]] = {}
    for meta in meta_by_id.values():
        parent = meta.get("parent")
        if parent and _visible(meta):
            kids.setdefault(parent, []).append(meta)

    for rec in all_recs:
        meta = rec["meta"]
        task_id = str(meta.get("id", ""))
        status = meta.get("status")
        if not task_id.startswith("task-") or not _visible(meta):
            continue
        if meta.get("executor", USER_EXECUTOR) != executor or status not in buckets:
            continue
        if not _task_in_root(task_id, root_id, meta_by_id):
            continue
        children = kids.get(task_id, [])
        done = sum(1 for child in children if child.get("status") == "done")
        buckets[status].append({
            "id": task_id,
            "title": meta.get("title", ""),
            "status": status,
            "priority": meta.get("priority", "P2"),
            "executor": executor,
            "agent_label": executor_label(executor),
            "note": meta.get("review_note") or meta.get("decision_needed") or "",
            "detail": (rec.get("body") or "").strip(),
            "progress": f"{done}/{len(children)}" if children else "",
        })
    for values in buckets.values():
        values.sort(key=lambda item: (item["priority"], item["id"]))
    return buckets


def list_review_queue() -> dict[str, list[dict[str, Any]]]:
    """用户验收窗口的全 Agent 汇总队列，不包含各 Agent 的 in_progress 工作集。"""
    out = {status: [] for status in _PENDING_AGENT_STATUSES}
    for executor in AGENT_PROFILES:
        queue = list_agent_queue(executor)
        for status in out:
            out[status].extend(queue[status])
    for values in out.values():
        values.sort(key=lambda item: (item["priority"], item["id"]))
    return out


@_synced
def reject_agent_review(
    task_id: str,
    reason: str = "",
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    vault = _work_vault()
    rec = _authorize_agent_task(vault, task_id, executor, root_id=root_id)
    _require_status(rec["meta"], "pending_review")
    patch: dict[str, Any] = {"status": "in_progress"}
    if reason:
        patch["review_note"] = "打回:" + reason
    return _agent_update(vault, task_id, patch)


@_synced
def reject_agent_start(
    task_id: str,
    reason: str = "",
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    vault = _work_vault()
    rec = _authorize_agent_task(vault, task_id, executor, root_id=root_id)
    _require_status(rec["meta"], "pending_start")
    patch: dict[str, Any] = {"status": "todo", "executor": USER_EXECUTOR}
    if reason:
        patch["review_note"] = "拒绝提议:" + reason
    return _agent_update(vault, task_id, patch)


@_synced
def answer_agent_decision(
    task_id: str,
    answer: str,
    *,
    executor: str,
    root_id: str | None = None,
) -> dict[str, Any]:
    vault = _work_vault()
    rec = _authorize_agent_task(vault, task_id, executor, root_id=root_id)
    _require_status(rec["meta"], "pending_decision")
    if not answer.strip():
        raise ValidationError("决策答复不能为空")
    return _agent_update(vault, task_id, {
        "status": "in_progress", "decision_answer": answer.strip(),
    })


# —— dev_agent 兼容包装：现有手册、UI 命令和外部调用无需迁移 ——
def propose_task(task_id: str) -> dict[str, Any]:
    return propose_agent_task(task_id, executor="dev_agent")


def approve_task(task_id: str) -> dict[str, Any]:
    return approve_agent_task(task_id, executor="dev_agent")


def request_decision(task_id: str, question: str) -> dict[str, Any]:
    return request_agent_decision(task_id, question, executor="dev_agent")


def submit_for_review(task_id: str, note: str = "") -> dict[str, Any]:
    return submit_agent_review(task_id, note, executor="dev_agent")


def accept_task(task_id: str) -> dict[str, Any]:
    return accept_agent_task(task_id, executor="dev_agent")


def list_dev_queue() -> dict[str, list[dict[str, Any]]]:
    queue = list_agent_queue("dev_agent")
    return {status: queue[status] for status in _PENDING_AGENT_STATUSES}


def reject_review(task_id: str, reason: str = "") -> dict[str, Any]:
    return reject_agent_review(task_id, reason, executor="dev_agent")


def reject_start(task_id: str, reason: str = "") -> dict[str, Any]:
    return reject_agent_start(task_id, reason, executor="dev_agent")


def answer_decision(task_id: str, answer: str) -> dict[str, Any]:
    return answer_agent_decision(task_id, answer, executor="dev_agent")
