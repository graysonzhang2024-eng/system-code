"""entity.py —— 所有记录共有的「基座」字段与校验。

【这个文件解决什么】
任务、规划、决策……每种记录都需要 id、创建时间、标签这些共有字段。
与其每种各写一遍(容易不一致),不如抽一个基座,让大家都继承它。
这就是 DRY 原则(Don't Repeat Yourself)。

【为什么用 dataclass】
dataclass 是 Python 描述"结构化数据"的标准方式:你只需列出字段名和类型,
它自动帮你生成构造、比较、打印等样板代码。可以理解成"给一类记录发的模板"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# --- 枚举取值(用常量集合表达"这个字段只能填这些值")---
# domain:这条记录属于哪一层数据边界(对应三层:work / personal)
DOMAINS = {"work", "personal"}
# source_machine:这条记录是哪台机器产生的(单写者原则,防跨机编辑冲突)
SOURCE_MACHINES = {"work", "personal"}


def now_iso() -> str:
    """返回当前时间的标准字符串(ISO 8601,带时区)。

    为什么用 ISO 字符串而不是时间对象:字符串能直接写进 markdown、人能读、
    跨机器/跨语言都认。例:2026-07-17T13:20:00+00:00
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ValidationError(Exception):
    """校验失败时抛出的错误。

    我们让校验失败"大声报错"而不是"悄悄放过",因为这个框架没有真实数据兜底,
    格式错了必须立刻暴露,而不是等到跑真实数据时才炸。
    """


@dataclass
class BaseEntity:
    """所有记录的基座。task / worklog / decision 等都在它之上扩展。

    字段说明:
      id             唯一编号,像身份证。必填。
      created_at     创建时间,管理员自动盖章。
      updated_at     最后修改时间,每次改动自动更新。
      tags           标签列表,方便归类检索。
      domain         work / personal —— 属于哪一层数据边界。
      source_machine work / personal —— 哪台机器产生的。
    """

    id: str
    domain: str = "work"
    source_machine: str = "work"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    tags: list[str] = field(default_factory=list)

    # --- 校验:字段值是否合法。不合法就抛 ValidationError ---
    def validate(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise ValidationError("id 必填且必须是字符串")
        if self.domain not in DOMAINS:
            raise ValidationError(
                f"domain 只能是 {sorted(DOMAINS)},收到:{self.domain!r}"
            )
        if self.source_machine not in SOURCE_MACHINES:
            raise ValidationError(
                f"source_machine 只能是 {sorted(SOURCE_MACHINES)},"
                f"收到:{self.source_machine!r}"
            )
        if not isinstance(self.tags, list):
            raise ValidationError("tags 必须是列表")


def validate_frontmatter(meta: dict[str, Any]) -> None:
    """对"从文件里读出来的 frontmatter 字典"做基座级校验。

    vault store 读文件时不知道它是 task 还是 decision,先用这个函数
    保证基座字段(id/domain/source_machine)合法;各类型专属字段留给
    后续 schema(步骤2/3)校验。
    """
    if "id" not in meta or not meta["id"]:
        raise ValidationError("frontmatter 缺少 id")
    if meta.get("domain", "work") not in DOMAINS:
        raise ValidationError(f"domain 非法:{meta.get('domain')!r}")
    if meta.get("source_machine", "work") not in SOURCE_MACHINES:
        raise ValidationError(f"source_machine 非法:{meta.get('source_machine')!r}")
