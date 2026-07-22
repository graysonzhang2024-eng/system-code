"""config.py —— 配置层:决定数据仓在哪、当前机器是谁。

【解决什么】
工具层要读写 vault,但"vault 在哪"不该写死在代码里:
- 开发/自测时 → 用仓内 fixtures/ 假数据
- 真实运行时 → 用 .env 里 WORK_VAULT_PATH 指向的真实 work-vault

这就是"A→B 翻转靠配置不靠改码":同一份代码,靠 .env 切换假/真数据。

【.env 怎么读】
不依赖第三方库(如 python-dotenv),自己解析十几行 → 少一个依赖。
读取顺序:真实环境变量 > 同目录 .env 文件 > 默认值。
"""

from __future__ import annotations

import os
from pathlib import Path

# 仓根目录(system-code/),用于定位 fixtures 和 .env
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> dict[str, str]:
    """读取 system-code/.env(若存在),返回键值字典。不覆盖已存在的真实环境变量。"""
    env: dict[str, str] = {}
    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


_DOTENV = _load_dotenv()


def _get(key: str, default: str = "") -> str:
    """取配置:真实环境变量优先,其次 .env 文件,最后默认值。"""
    return os.environ.get(key) or _DOTENV.get(key, default)


def work_vault_path() -> Path:
    """工作数据仓路径。未配置 WORK_VAULT_PATH 时,回退到 fixtures/work(开发用)。"""
    p = _get("WORK_VAULT_PATH")
    if p:
        return Path(p).expanduser()
    return _REPO_ROOT / "fixtures" / "work"


def personal_vault_path() -> Path:
    """生活数据仓路径。未配置时回退到 fixtures/work(仅占位,开发不碰真实私人数据)。"""
    p = _get("PERSONAL_VAULT_PATH")
    if p:
        return Path(p).expanduser()
    return _REPO_ROOT / "fixtures" / "work"


def is_using_fixtures() -> bool:
    """当前是否在用 fixtures 假数据(未配置真实路径)。管家可用它提示用户。"""
    return not _get("WORK_VAULT_PATH")
