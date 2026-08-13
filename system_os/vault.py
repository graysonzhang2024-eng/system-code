"""vault.py —— 仓库读写器(vault store),整个系统的「食材仓库管理员」。

【它负责什么】
把一条条记录(每条 = 一个 .md 文件)在"硬盘"和"程序"之间搬运,并保证格式正确。
之后所有 task / 规划 / 决策的读写,都经过这个管理员。

【一条记录长什么样】
    ---
    id: task-2026-0001      ← frontmatter:两行 --- 夹住的结构化区,给机器读(YAML 格式)
    status: todo
    ---
    正文写给人读的描述。   ← body:frontmatter 之后的自由文本

【它会做的五个动作(CRUD + 列表)】
    create  新建一条记录(写文件)
    read    读一条记录(id → 内容)
    update  改一条记录的字段
    delete  删一条记录
    list    列出全部(可按条件过滤)

【设计取舍】
- 不依赖第三方库(如 python-frontmatter),只用标准库 PyYAML 自己解析 →
  少一个依赖 = 更可移植 = 更低维护(呼应项目目标)。
- 数据根目录由外部传入(默认 fixtures/;真实运行时由 .env 指向真实 vault)→
  这就是"A→B 翻转靠配置不靠改码"的落点。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import yaml

from .entity import ValidationError, now_iso, validate_frontmatter


# frontmatter 与 body 的分隔线
_FENCE = "---"


# ============================================================
# 一、frontmatter 解析 / 拼装(纯文本 <-> 结构化)
# ============================================================

def parse_document(text: str) -> tuple[dict[str, Any], str]:
    """把一份 .md 文本拆成 (frontmatter 字典, 正文字符串)。

    规则:文件若以一行 '---' 开头,则到下一行 '---' 之间是 YAML frontmatter,
    其余为正文。没有 frontmatter 的文件返回 ({}, 全文)。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        # 没有 frontmatter,整篇都是正文
        return {}, text

    # 找第二个 '---' 作为结束
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            meta = yaml.safe_load(fm_text) if fm_text.strip() else {}
            if meta is None:
                meta = {}
            if not isinstance(meta, dict):
                raise ValidationError("frontmatter 必须是键值对(YAML 映射)")
            # 去掉正文开头多余的换行,保持整洁
            return meta, body.lstrip("\n")

    raise ValidationError("frontmatter 起始有 '---' 但缺少结束的 '---'")


def build_document(meta: dict[str, Any], body: str) -> str:
    """把 (frontmatter 字典, 正文) 拼回成一份完整 .md 文本。是 parse 的逆操作。"""
    # sort_keys=False:保持我们写入的字段顺序,人读更友好
    # allow_unicode=True:让中文原样输出,而不是被转成 \uXXXX
    fm_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = (body or "").strip()
    return f"{_FENCE}\n{fm_text}\n{_FENCE}\n\n{body}\n"


# ============================================================
# 二、Vault —— 管理员本体(CRUD)
# ============================================================

class Vault:
    """一个数据仓库的读写入口。

    用法:
        vault = Vault("fixtures/work")          # 指向数据根目录
        vault.create("task-1", {"status": "todo"}, "买咖啡")
        rec = vault.read("task-1")               # -> {"meta": {...}, "body": "..."}
        vault.update("task-1", {"status": "done"})
        for rec in vault.list(where={"status": "done"}): ...
        vault.delete("task-1")
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    # id 前缀 → 子目录 的映射。按记录类型分目录存放(形式 B)。
    _SUBDIRS = {
        "task": "task",
        "log": "worklog",
        "dailylog": "worklog",
        "plan": "planning",
        "dec": "decision",
        "rule": "rule",
        "routine": "routine",
        "knowledge": "knowledge",
        "knote": "knowledge-note",
    }

    def _subdir_for(self, entity_id: str) -> str:
        """按 id 前缀返回应存入的子目录名;无匹配前缀则存根目录("")。"""
        prefix = entity_id.split("-", 1)[0]
        return self._SUBDIRS.get(prefix, "")

    # --- 内部:id 与文件路径互转 ---
    def _path(self, entity_id: str) -> Path:
        """写入用的目标路径:按类型分子目录。"""
        if "/" in entity_id or "\\" in entity_id:
            raise ValidationError(f"id 不允许包含路径分隔符:{entity_id!r}")
        sub = self._subdir_for(entity_id)
        return (self.root / sub / f"{entity_id}.md") if sub else self.root / f"{entity_id}.md"

    def _find(self, entity_id: str) -> Path | None:
        """读取用的定位:先找分类子目录,再兼容根目录(旧数据/fixtures)。找不到返回 None。"""
        if "/" in entity_id or "\\" in entity_id:
            raise ValidationError(f"id 不允许包含路径分隔符:{entity_id!r}")
        candidates = [self._path(entity_id), self.root / f"{entity_id}.md"]
        for p in candidates:
            if p.exists():
                return p
        return None

    # --- Create ---
    def create(
        self,
        entity_id: str,
        meta: dict[str, Any] | None = None,
        body: str = "",
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """新建一条记录。默认不允许覆盖已存在的 id(防手滑)。"""
        if self._find(entity_id) is not None and not overwrite:
            raise ValidationError(f"记录已存在:{entity_id}(如需覆盖请传 overwrite=True)")
        path = self._path(entity_id)

        meta = dict(meta or {})
        meta.setdefault("id", entity_id)
        meta.setdefault("created_at", now_iso())
        meta["updated_at"] = now_iso()
        validate_frontmatter(meta)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_document(meta, body), encoding="utf-8")
        return {"meta": meta, "body": body}

    # --- Read ---
    def read(self, entity_id: str) -> dict[str, Any]:
        """读一条记录,返回 {"meta": 字典, "body": 正文}。不存在则报错。"""
        path = self._find(entity_id)
        if path is None:
            raise FileNotFoundError(f"记录不存在:{entity_id}")
        meta, body = parse_document(path.read_text(encoding="utf-8"))
        validate_frontmatter(meta)
        return {"meta": meta, "body": body}

    # --- Update ---
    def update(
        self,
        entity_id: str,
        meta_patch: dict[str, Any] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        """改一条记录。meta_patch 里的字段会合并进原 frontmatter;
        body 传 None 表示不改正文。updated_at 自动刷新。
        """
        rec = self.read(entity_id)
        meta = rec["meta"]
        if meta_patch:
            meta.update(meta_patch)
        meta["updated_at"] = now_iso()
        validate_frontmatter(meta)
        new_body = rec["body"] if body is None else body
        # 写回文件实际所在位置(可能在子目录,也可能是根目录的旧数据)
        target = self._find(entity_id) or self._path(entity_id)
        target.write_text(build_document(meta, new_body), encoding="utf-8")
        return {"meta": meta, "body": new_body}

    # --- Delete ---
    def delete(self, entity_id: str) -> None:
        """删一条记录。不存在则报错(避免"以为删了其实没有")。"""
        path = self._find(entity_id)
        if path is None:
            raise FileNotFoundError(f"记录不存在,无法删除:{entity_id}")
        path.unlink()

    # --- List ---
    def list(self, where: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """列出所有记录(递归扫根目录及分类子目录)。where 传字段条件时只返回匹配的。

        例:list(where={"status": "todo", "priority": "P0"})
        """
        if not self.root.exists():
            return
        # rglob 递归匹配所有层级的 .md;排除 .git 等隐藏目录
        for path in sorted(self.root.rglob("*.md")):
            if any(part.startswith(".") for part in path.relative_to(self.root).parts):
                continue
            meta, body = parse_document(path.read_text(encoding="utf-8"))
            if not meta:
                continue  # 跳过没有 frontmatter 的说明文件(README/CLAUDE.md 等)
            if where and any(meta.get(k) != v for k, v in where.items()):
                continue
            yield {"meta": meta, "body": body}

    def exists(self, entity_id: str) -> bool:
        return self._find(entity_id) is not None
