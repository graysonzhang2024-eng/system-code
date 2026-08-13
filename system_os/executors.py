"""Agent 执行器注册表。

这里只保存稳定的系统级边界：执行器名、用户可见标签、允许管理的任务根，
以及可选的外挂工作区环境变量。业务提示词和真实路径不放进代码。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import get_value


@dataclass(frozen=True)
class AgentProfile:
    executor: str
    label: str
    root_id: str | None = None
    root_env: str | None = None
    workspace_env: str | None = None

    def resolved_root_id(self) -> str | None:
        """Return the configured authorization root without exposing it in code."""
        if not self.root_env:
            return self.root_id
        value = get_value(self.root_env).strip()
        return value or self.root_id


USER_EXECUTOR = "user"

# 第二个真实专项 Agent 出现后才收割公共骨架。root_id=None 表示不限定单一业务树；
# 有 root_id 的专项 Agent 必须同时通过 executor 和祖先链两层授权。
AGENT_PROFILES: dict[str, AgentProfile] = {
    "dev_agent": AgentProfile(
        executor="dev_agent",
        label="系统开发",
    ),
    "internship_agent": AgentProfile(
        executor="internship_agent",
        label="实习攻略",
        root_id="task-demo-career-root",
        root_env="INTERNSHIP_AGENT_ROOT_ID",
        workspace_env="INTERNSHIP_WORKSPACE_PATH",
    ),
}

TASK_EXECUTORS = {USER_EXECUTOR, *AGENT_PROFILES}


def get_agent_profile(executor: str) -> AgentProfile:
    """返回已注册的 Agent 配置；user/未知值都不能冒充专项 Agent。"""
    try:
        return AGENT_PROFILES[executor]
    except KeyError as exc:
        raise ValueError(f"未知 agent executor:{executor!r}") from exc


def executor_label(executor: str | None) -> str:
    """给 UI/日志使用的稳定中文标签。"""
    if not executor or executor == USER_EXECUTOR:
        return "用户"
    profile = AGENT_PROFILES.get(executor)
    return profile.label if profile else executor
