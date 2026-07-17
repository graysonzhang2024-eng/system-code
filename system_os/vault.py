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

    # --- 内部:id 与文件路径互转 ---
    def _path(self, entity_id: str) -> Path:
        # 一条记录 = 一个 <id>.md 文件。id 里若含 / 会被当子目录,这里禁止。
        if "/" in entity_id or "\\" in entity_id:
            raise ValidationError(f"id 不允许包含路径分隔符:{entity_id!r}")
        return self.root / f"{entity_id}.md"

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
        path = self._path(entity_id)
        if path.exists() and not overwrite:
            raise ValidationError(f"记录已存在:{entity_id}(如需覆盖请传 overwrite=True)")

        meta = dict(meta or {})
        meta.setdefault("id", entity_id)
        meta.setdefault("created_at", now_iso())
        meta["updated_at"] = now_iso()
        validate_frontmatter(meta)

        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(build_document(meta, body), encoding="utf-8")
        return {"meta": meta, "body": body}

    # --- Read ---
    def read(self, entity_id: str) -> dict[str, Any]:
        """读一条记录,返回 {"meta": 字典, "body": 正文}。不存在则报错。"""
        path = self._path(entity_id)
        if not path.exists():
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
        self._path(entity_id).write_text(
            build_document(meta, new_body), encoding="utf-8"
        )
        return {"meta": meta, "body": new_body}

    # --- Delete ---
    def delete(self, entity_id: str) -> None:
        """删一条记录。不存在则报错(避免"以为删了其实没有")。"""
        path = self._path(entity_id)
        if not path.exists():
            raise FileNotFoundError(f"记录不存在,无法删除:{entity_id}")
        path.unlink()

    # --- List ---
    def list(self, where: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """列出根目录下所有记录。where 传字段条件时,只返回全部匹配的记录。

        例:list(where={"status": "todo", "priority": "P0"})
        """
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.md")):
            meta, body = parse_document(path.read_text(encoding="utf-8"))
            if not meta:
                continue  # 跳过没有 frontmatter 的说明文件等
            if where and any(meta.get(k) != v for k, v in where.items()):
                continue
            yield {"meta": meta, "body": body}

    def exists(self, entity_id: str) -> bool:
        return self._path(entity_id).exists()
