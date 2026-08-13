"""知识库实体校验：宏观学习条目与其下的具体笔记。"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .entity import ValidationError, validate_frontmatter


KNOWLEDGE_KINDS = {"paper", "podcast", "book", "course", "article", "video", "other"}
KNOWLEDGE_STATUSES = {"want", "learning", "learned", "archived"}
KNOWLEDGE_PRIORITIES = {"P0", "P1", "P2", "P3"}
KNOWLEDGE_CATEGORIES = {"事业", "学业", "人际", "生活", "系统"}
NOTE_TYPES = {"summary", "insight", "question", "connection", "action", "quote"}


def _validate_date(meta: dict[str, Any], field: str) -> None:
    value = meta.get(field)
    if not value:
        return
    try:
        _dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} 必须是 YYYY-MM-DD 日期")


def validate_knowledge(meta: dict[str, Any]) -> None:
    validate_frontmatter(meta)
    for field in ("title", "kind", "status", "priority", "category"):
        if not meta.get(field):
            raise ValidationError(f"knowledge 缺少必填字段:{field}")
    if meta["kind"] not in KNOWLEDGE_KINDS:
        raise ValidationError(f"kind 非法:{meta['kind']!r}")
    if meta["status"] not in KNOWLEDGE_STATUSES:
        raise ValidationError(f"status 非法:{meta['status']!r}")
    if meta["priority"] not in KNOWLEDGE_PRIORITIES:
        raise ValidationError(f"priority 非法:{meta['priority']!r}")
    if meta["category"] not in KNOWLEDGE_CATEGORIES:
        raise ValidationError(f"category 非法:{meta['category']!r}")
    for field in ("published_on", "learned_on"):
        _validate_date(meta, field)
    if "duration_minutes" in meta:
        value = meta["duration_minutes"]
        if not isinstance(value, (int, float)) or value < 0:
            raise ValidationError("duration_minutes 必须是非负数字")
    if "rating" in meta:
        value = meta["rating"]
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise ValidationError("rating 必须是 1 到 5 的整数")
    if "tags" in meta and not isinstance(meta["tags"], list):
        raise ValidationError("tags 必须是列表")


def validate_knowledge_note(meta: dict[str, Any]) -> None:
    validate_frontmatter(meta)
    for field in ("knowledge_ref", "note_type", "captured_on"):
        if not meta.get(field):
            raise ValidationError(f"knowledge note 缺少必填字段:{field}")
    if not str(meta["knowledge_ref"]).startswith("knowledge-"):
        raise ValidationError("knowledge_ref 必须指向 knowledge 条目")
    if meta["note_type"] not in NOTE_TYPES:
        raise ValidationError(f"note_type 非法:{meta['note_type']!r}")
    _validate_date(meta, "captured_on")
    if "tags" in meta and not isinstance(meta["tags"], list):
        raise ValidationError("tags 必须是列表")
