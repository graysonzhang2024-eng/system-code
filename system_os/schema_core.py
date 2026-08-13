"""schema_core.py —— 通用域 schema 校验(decision / rule)。

【为什么和 schema_work 分开】
decision/rule 是任何域都能用的通用实体(不只工作),放通用层。
工作域附加的字段(category/reversibility/evidence_refs)以「work 扩展块」形式
在这里做可选校验,但基座保持通用——体现"通用 vs 工作物理分层"。

【治理钩子】
低电状态禁止做不可逆(one_way_door)决策 —— 这条治理规则在 check_decision_guard() 落地。
"""

from __future__ import annotations

from typing import Any

from .entity import ValidationError, validate_frontmatter

# ============================================================
# decision 枚举
# ============================================================
DECISION_STATUS = {"open", "decided", "reviewed", "reversed"}
CONFIDENCE = {"low", "medium", "high"}
REVERSIBILITY = {"one_way_door", "two_way_door"}
ENERGY = {"low", "medium", "high", "drain"}

# rule 枚举
RULE_STATUS = {"candidate", "validated", "deprecated"}

# work 扩展块用到的 5 分类(与 schema_work.CATEGORY 一致;此处独立列出避免跨模块耦合)
CATEGORY = {"事业", "学业", "人际", "生活", "系统"}


# ============================================================
# decision 校验
# ============================================================
def validate_decision(meta: dict[str, Any]) -> None:
    """校验一条 decision 的 frontmatter(通用基座 + work 扩展块可选校验)。"""
    validate_frontmatter(meta)

    for f in ("title", "date", "status"):
        if not meta.get(f):
            raise ValidationError(f"decision 缺少必填字段:{f}")

    if meta["status"] not in DECISION_STATUS:
        raise ValidationError(
            f"status 非法:{meta['status']!r},应为 {sorted(DECISION_STATUS)}"
        )
    if "confidence" in meta and meta["confidence"] not in CONFIDENCE:
        raise ValidationError(f"confidence 非法:{meta['confidence']!r}")

    # --- work 扩展块(都可选,存在才校验)---
    if "reversibility" in meta and meta["reversibility"] not in REVERSIBILITY:
        raise ValidationError(f"reversibility 非法:{meta['reversibility']!r}")
    if "energy_context" in meta and meta["energy_context"] not in ENERGY:
        raise ValidationError(f"energy_context 非法:{meta['energy_context']!r}")
    if "category" in meta and meta["category"] not in CATEGORY:
        raise ValidationError(f"category 非法:{meta['category']!r}")

    for f in ("options", "related_rules", "planning_ref", "task_refs", "tags"):
        if f in meta and not isinstance(meta[f], list):
            raise ValidationError(f"{f} 必须是列表")


def check_decision_guard(meta: dict[str, Any]) -> None:
    """治理钩子:低电状态禁止拍板不可逆决策。

    当 energy_context 为 low/drain 且 reversibility=one_way_door 且已 decided 时,
    抛错提示"这是不可逆决策,当前精力过低,建议等清醒再定"。
    可逆决策(two_way_door)不受此限。
    """
    if meta.get("status") != "decided":
        return
    if meta.get("reversibility") != "one_way_door":
        return
    if meta.get("energy_context") in {"low", "drain"}:
        raise ValidationError(
            "低电状态(energy_context=low/drain)禁止拍板不可逆决策(one_way_door):"
            "建议推迟到精力恢复后再定"
        )


# ============================================================
# rule 校验
# ============================================================
def validate_rule(meta: dict[str, Any]) -> None:
    """校验一条 rule 的 frontmatter。"""
    validate_frontmatter(meta)

    for f in ("statement", "status"):
        if not meta.get(f):
            raise ValidationError(f"rule 缺少必填字段:{f}")

    if meta["status"] not in RULE_STATUS:
        raise ValidationError(
            f"status 非法:{meta['status']!r},应为 {sorted(RULE_STATUS)}"
        )
    if "confidence" in meta and meta["confidence"] not in CONFIDENCE:
        raise ValidationError(f"confidence 非法:{meta['confidence']!r}")
    if "category" in meta and meta["category"] not in CATEGORY:
        raise ValidationError(f"category 非法:{meta['category']!r}")

    for f in ("failure_modes", "evidence_refs", "tags"):
        if f in meta and not isinstance(meta[f], list):
            raise ValidationError(f"{f} 必须是列表")
