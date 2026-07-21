"""machine.py —— 机器身份识别。

【解决什么】
domain(work/personal,决定数据存哪台机、隐私边界)不该靠人手标、也不靠猜,
而由"这条记录产生在哪台机器"这个客观事实自动决定。

【怎么认机器】按可靠性优先级:
  1. 环境变量 MACHINE_ID(在每台机的 .env 里配一次,推荐:可控、可移植)
  2. 主机名匹配(fallback:hostname 里含 work/personal 关键词)
  3. 都认不出 → 默认 work,并提示配置(不静默猜错)

配置方式(每台机一次性):
  工作机 .env:  MACHINE_ID=work
  个人机 .env:  MACHINE_ID=personal
"""

from __future__ import annotations

import os
import socket

VALID_MACHINES = {"work", "personal"}


def detect_machine() -> str:
    """返回当前机器身份:'work' 或 'personal'。

    读取顺序:环境变量 MACHINE_ID > 主机名启发式 > 默认 work。
    """
    # 1. 环境变量(最明确,你说了算)
    env_id = os.environ.get("MACHINE_ID", "").strip().lower()
    if env_id in VALID_MACHINES:
        return env_id

    # 2. 主机名启发式(fallback)
    hostname = socket.gethostname().lower()
    if "personal" in hostname or "home" in hostname:
        return "personal"
    if "work" in hostname or "company" in hostname:
        return "work"

    # 3. 认不出:默认 work(工作机是框架开发的默认环境),不静默猜错
    return "work"


def current_domain() -> str:
    """当前机器对应的默认 domain。work 机 → work 域,personal 机 → personal 域。"""
    return detect_machine()
