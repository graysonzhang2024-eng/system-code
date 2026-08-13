"""专项 Agent 外挂工作区的安全路径与最小写入工具。"""

from __future__ import annotations

from pathlib import Path

from . import config
from .executors import get_agent_profile


def workspace_root(executor: str, *, require_exists: bool = True) -> Path:
    """读取执行器的外挂工作区根目录。

    路径只来自本机环境/.env，不进入仓库。未配置、执行器没有外挂工作区，或
    目录不存在时明确报错，不静默回退到当前目录。
    """
    profile = get_agent_profile(executor)
    if not profile.workspace_env:
        raise ValueError(f"{executor} 未配置外挂工作区")
    raw = config.get_value(profile.workspace_env)
    if not raw:
        raise ValueError(f"缺少配置:{profile.workspace_env}")
    root = Path(raw).expanduser().resolve()
    if require_exists and not root.is_dir():
        raise FileNotFoundError(f"外挂工作区不存在:{root}")
    return root


def resolve_workspace_path(executor: str, relative_path: str) -> Path:
    """把相对产物路径限制在对应外挂根内，阻止绝对路径和 ``..`` 越界。"""
    rel = Path(relative_path)
    if rel.is_absolute():
        raise ValueError("产物路径必须是外挂工作区内的相对路径")
    root = workspace_root(executor)
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("产物路径越过了外挂工作区边界")
    return target


def write_text_artifact(
    executor: str,
    relative_path: str,
    content: str,
    *,
    overwrite: bool = False,
) -> Path:
    """在授权外挂工作区写一个 UTF-8 文本产物。默认不覆盖已有文件。"""
    target = resolve_workspace_path(executor, relative_path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"产物已存在:{relative_path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
