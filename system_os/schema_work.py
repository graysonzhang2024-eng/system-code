"""schema_work.py —— 工作域 schema 的校验规则(task / worklog)。

【它和 entity.py 的分工】
- entity.py:所有记录共有的基座字段校验(id/domain/source_machine)。
- schema_work.py:工作域专属校验——task 的字段枚举、状态机规则;worklog 的字段。

【为什么单独一个文件】
"通用 vs 工作语义物理分层"(架构纪律):基座留在 entity,工作味的字段(category 5分类、
energy_cost、状态机)集中在这里。将来出现生活域,不会被工作规则污染。

【状态机在这里落地】
task.schema.md 里画的状态机规则(blocked 必带原因、依赖未清不开工),
在这里变成会真正执行的校验代码。
"""

from __future__ import annotations

from typing import Any

from .entity import ValidationError, validate_frontmatter

# ============================================================
# 枚举取值(与 schema 文档保持一致)
# ============================================================
TASK_STATUS = {"todo", "in_progress", "blocked", "done", "cancelled"}
PRIORITY = {"P0", "P1", "P2", "P3"}
# 5 人生分类(语义轴,task 与 worklog 共用)
CATEGORY = {"事业", "学业", "人际", "生活", "系统"}
ENERGY = {"low", "medium", "high", "drain"}

# planning 枚举
PLANNING_TYPE = {"objective", "milestone", "roadmap_item", "theme"}
PLANNING_HORIZON = {"now", "quarter", "year", "someday"}
PLANNING_STATUS = {"proposed", "active", "achieved", "dropped", "deferred"}


# ============================================================
# task 校验
# ============================================================
def validate_task(meta: dict[str, Any]) -> None:
    """校验一条 task 的 frontmatter。不合法抛 ValidationError。"""
    validate_frontmatter(meta)  # 先过基座校验

    # --- 必填字段存在性 ---
    for f in ("title", "status", "priority", "category", "energy_cost"):
        if not meta.get(f):
            raise ValidationError(f"task 缺少必填字段:{f}")

    # --- 枚举取值合法性 ---
    if meta["status"] not in TASK_STATUS:
        raise ValidationError(f"status 非法:{meta['status']!r},应为 {sorted(TASK_STATUS)}")
    if meta["priority"] not in PRIORITY:
        raise ValidationError(f"priority 非法:{meta['priority']!r},应为 {sorted(PRIORITY)}")
    if meta["category"] not in CATEGORY:
        raise ValidationError(f"category 非法:{meta['category']!r},应为 {sorted(CATEGORY)}")
    if meta["energy_cost"] not in ENERGY:
        raise ValidationError(f"energy_cost 非法:{meta['energy_cost']!r},应为 {sorted(ENERGY)}")

    # --- 条件字段:blocked 必须带原因 ---
    if meta["status"] == "blocked" and not meta.get("blocked_reason"):
        raise ValidationError("status=blocked 时必须填 blocked_reason(卡住必须写清为什么)")

    # --- 列表型字段类型检查 ---
    for f in ("depends_on", "planning_ref", "decision_refs", "rule_refs", "tags"):
        if f in meta and not isinstance(meta[f], list):
            raise ValidationError(f"{f} 必须是列表")


def check_transition(
    current: dict[str, Any],
    new_status: str,
    dep_status_map: dict[str, str] | None = None,
) -> None:
    """校验一次状态流转是否合法。

    参数:
      current        任务当前的 frontmatter
      new_status     想要切到的新状态
      dep_status_map {依赖任务id: 该任务status},用于判断依赖是否都 done

    规则:
      - 新状态必须是合法枚举
      - 进入 in_progress:所有 depends_on 必须已 done(依赖未清不开工)
      - 进入 blocked:调用方需保证会带上 blocked_reason(由 validate_task 兜底)
      - cancelled/done 是终态,可从任意非终态进入
    """
    if new_status not in TASK_STATUS:
        raise ValidationError(f"目标状态非法:{new_status!r}")

    if new_status == "in_progress":
        deps = current.get("depends_on") or []
        if deps:
            dep_status_map = dep_status_map or {}
            unfinished = [
                d for d in deps if dep_status_map.get(d) != "done"
            ]
            if unfinished:
                raise ValidationError(
                    f"依赖未完成,不能进入 in_progress:{unfinished}"
                )


# ============================================================
# worklog 校验
# ============================================================
def validate_worklog(meta: dict[str, Any]) -> None:
    """校验一条 worklog 的 frontmatter。"""
    validate_frontmatter(meta)

    for f in ("date", "summary", "category"):
        if not meta.get(f):
            raise ValidationError(f"worklog 缺少必填字段:{f}")

    if meta["category"] not in CATEGORY:
        raise ValidationError(f"category 非法:{meta['category']!r}")

    if "energy_actual" in meta and meta["energy_actual"] not in ENERGY:
        raise ValidationError(f"energy_actual 非法:{meta['energy_actual']!r}")

    for f in ("artifacts", "rule_candidates", "tags"):
        if f in meta and not isinstance(meta[f], list):
            raise ValidationError(f"{f} 必须是列表")


# ============================================================
# planning 校验
# ============================================================
def validate_planning(meta: dict[str, Any]) -> None:
    """校验一条 planning 的 frontmatter。"""
    validate_frontmatter(meta)

    for f in ("title", "type", "horizon", "category", "status"):
        if not meta.get(f):
            raise ValidationError(f"planning 缺少必填字段:{f}")

    if meta["type"] not in PLANNING_TYPE:
        raise ValidationError(f"type 非法:{meta['type']!r},应为 {sorted(PLANNING_TYPE)}")
    if meta["horizon"] not in PLANNING_HORIZON:
        raise ValidationError(
            f"horizon 非法:{meta['horizon']!r},应为 {sorted(PLANNING_HORIZON)}"
        )
    if meta["category"] not in CATEGORY:
        raise ValidationError(f"category 非法:{meta['category']!r}")
    if meta["status"] not in PLANNING_STATUS:
        raise ValidationError(
            f"status 非法:{meta['status']!r},应为 {sorted(PLANNING_STATUS)}"
        )

    for f in ("task_refs", "decision_refs", "tags"):
        if f in meta and not isinstance(meta[f], list):
            raise ValidationError(f"{f} 必须是列表")
