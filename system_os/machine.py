"""machine.py —— 机器身份识别。

【解决什么】
domain(work/personal,决定数据存哪台机、隐私边界)不该靠人手标、也不靠猜,
而由"这条记录产生在哪台机器"这个客观事实自动决定。

【怎么认机器】按可靠性优先级:
  1. 进程环境变量 MACHINE_ID(适合临时覆盖)
  2. system-code/.env 中的 MACHINE_ID(每台机配一次,推荐:可控、可移植)
  3. 主机名匹配(fallback:hostname 里含 work/personal 关键词)
  4. 都认不出 → 默认 work

配置方式(每台机一次性):
  工作机 .env:  MACHINE_ID=work
  个人机 .env:  MACHINE_ID=personal
"""

from __future__ import annotations

import socket

from .config import get_choice

VALID_MACHINES = {"work", "personal"}


def detect_machine() -> str:
    """返回当前机器身份:'work' 或 'personal'。

    读取顺序:进程环境变量 MACHINE_ID > system-code/.env > 主机名启发式
    > 默认 work。空值或非法值会被跳过,继续尝试下一个来源。
    """
    # 1 + 2. 显式配置(进程环境变量优先于 .env)
    configured_id = get_choice("MACHINE_ID", VALID_MACHINES)
    if configured_id:
        return configured_id

    # 3. 主机名启发式(fallback)
    hostname = socket.gethostname().lower()
    if "personal" in hostname or "home" in hostname:
        return "personal"
    if "work" in hostname or "company" in hostname:
        return "work"

    # 4. 认不出:默认 work(兼容既有行为)
    return "work"


def current_domain() -> str:
    """当前机器对应的默认 domain。work 机 → work 域,personal 机 → personal 域。"""
    return detect_machine()


# 机器标识字母:用于双机并行时给新记录 id 加后缀(task-0101w / task-0101p),
# 从根上消灭两台机各自新建记录时的 id 撞号(git 同路径冲突)。
_LETTERS = {"work": "w", "personal": "p"}


def machine_letter() -> str:
    """当前机器的 id 后缀字母:'w'(工作机)或 'p'(个人机)。"""
    return _LETTERS[detect_machine()]
