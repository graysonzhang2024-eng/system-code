"""os_api.py —— 前端浮窗与 Python actions 之间的「桥」。

【为什么需要它】
Electron 浮窗(JS)不能直接调 Python 函数。最简单可靠的通道:
浮窗用命令行方式执行 `python3 os_api.py <命令> <JSON参数>`,本脚本调 actions,
把结果以 JSON 打印到 stdout,浮窗解析即可。

【用法】
    python3 -m system_os.os_api tree            # 返回 {分类: [任务树]}
    python3 -m system_os.os_api toggle '{"id":"task-0001"}'
    python3 -m system_os.os_api add '{"title":"写周报","category":"事业","priority":"P1"}'
    python3 -m system_os.os_api add_done '{"title":"临时修复问题","category":"事业"}'
    python3 -m system_os.os_api add_sub '{"parent":"task-0001","title":"列提纲"}'

【输出约定】
成功:{"ok": true, "data": ...}
失败:{"ok": false, "error": "..."}
"""

from __future__ import annotations

import json
import sys

from . import actions
from . import sync


def _run(cmd: str, arg: dict) -> dict:
    if cmd == "tree":
        return {"ok": True, "data": actions.list_task_tree(
            include_done=arg.get("include_done", True))}
    if cmd == "toggle":
        rec = actions.toggle_done(arg["id"])
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "focus":
        rec = actions.toggle_focus(arg["id"])
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "set_layer":
        rec = actions.set_task_layer(arg["id"], arg["layer"])
        return {"ok": True, "data": {
            "id": arg["id"], "status": rec["meta"]["status"],
            "layer": arg["layer"], "today_date": rec["meta"].get("today_date", ""),
        }}
    if cmd == "agent_takeover_complete":
        rec = actions.take_over_agent_task(
            arg["id"], confirmed_by_user=bool(arg.get("confirmed_by_user", False)),
            summary=arg.get("summary"),
            what_done=arg.get("what_done", ""))
        return {"ok": True, "data": {
            "id": arg["id"], "status": rec["meta"]["status"],
            "taken_over_from": rec["meta"].get("taken_over_from"),
        }}
    if cmd == "unblock":
        rec = actions.unblock_task(arg["id"])
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "set_standing":
        # 常驻任务开关(容器性质,永不隐藏)
        rec = actions.set_standing(arg["id"], bool(arg.get("standing", True)))
        return {"ok": True, "data": {"id": arg["id"], "standing": rec["meta"].get("standing", False)}}
    if cmd == "catchup":
        # 补偿式生成遗漏的每日任务日志(浮窗/管家启动时调,兼容关机跨天)
        gen = actions.catch_up_logs()
        return {"ok": True, "data": {"generated": gen}}
    if cmd == "add":
        extra = {}
        if arg.get("sensitive"):
            extra["sensitive"] = True
        rec = actions.add_task(
            arg["title"],
            priority=arg.get("priority", "P2"),
            category=arg.get("category", "事业"),
            energy_cost=arg.get("energy_cost", "medium"),
            **extra,
        )
        return {"ok": True, "data": {"id": rec["meta"]["id"]}}
    if cmd == "add_done":
        rec = actions.record_completed_task(
            arg["title"],
            priority=arg.get("priority", "P2"),
            category=arg.get("category", "事业"),
            energy_cost=arg.get("energy_cost", "medium"),
            summary=arg.get("summary"),
            what_done=arg.get("what_done", ""),
            time_spent=arg.get("time_spent"),
            energy_actual=arg.get("energy_actual"),
            body=arg.get("body", ""),
        )
        return {"ok": True, "data": {
            "id": rec["meta"]["id"],
            "status": rec["meta"]["status"],
            "outcome_ref": rec["meta"]["outcome_ref"],
        }}
    if cmd == "add_sub":
        extra = {}
        if arg.get("sensitive"):
            extra["sensitive"] = True
        rec = actions.add_subtask(arg["parent"], arg["title"], **extra)
        return {"ok": True, "data": {"id": rec["meta"]["id"]}}
    if cmd == "add_rule":
        rec = actions.add_rule(
            arg["statement"],
            trigger=arg.get("trigger", ""),
            rationale=arg.get("rationale", ""),
            category=arg.get("category", "系统"),
            status=arg.get("status", "candidate"),
            confidence=arg.get("confidence", "medium"),
            failure_modes=arg.get("failure_modes"),
            evidence_refs=arg.get("evidence_refs"),
            tags=arg.get("tags"),
            body=arg.get("body", ""),
        )
        return {"ok": True, "data": {"id": rec["meta"]["id"]}}
    if cmd == "list_rules":
        recs = actions.list_rules(status=arg.get("status"))
        return {"ok": True, "data": [
            {"id": r["meta"]["id"], "statement": r["meta"].get("statement", ""),
             "status": r["meta"].get("status"), "category": r["meta"].get("category")}
            for r in recs
        ]}
    # —— 知识库：学习队列 + 条目笔记 ——
    if cmd == "knowledge_list":
        items = actions.list_knowledge(status=arg.get("status"), kind=arg.get("kind"))
        learned = [item for item in items if item.get("status") == "learned"]
        stats = {
            "total": len(items),
            "want": sum(item.get("status") == "want" for item in items),
            "learning": sum(item.get("status") == "learning" for item in items),
            "learned": len(learned),
            "papers": sum(item.get("kind") == "paper" for item in learned),
            "podcasts": sum(item.get("kind") == "podcast" for item in learned),
            "minutes": sum(float(item.get("duration_minutes") or 0) for item in learned),
        }
        return {"ok": True, "data": {"items": items, "stats": stats}}
    if cmd == "knowledge_update":
        rec = actions.update_knowledge(
            arg["id"], status=arg.get("status"), priority=arg.get("priority"),
            rating=arg.get("rating"), learned_on=arg.get("learned_on"),
            body=arg.get("body"),
        )
        return {"ok": True, "data": {
            "id": arg["id"], "status": rec["meta"]["status"],
            "priority": rec["meta"]["priority"],
        }}
    if cmd == "knowledge_add_note":
        rec = actions.add_knowledge_note(
            arg["id"], arg.get("content", ""),
            note_type=arg.get("note_type", "insight"),
            title=arg.get("title", ""),
        )
        return {"ok": True, "data": {"id": rec["meta"]["id"]}}
    # —— 开发 agent 协作流程 ——
    if cmd == "propose":
        rec = actions.propose_task(arg["id"])
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "approve":
        rec = actions.approve_task(arg["id"])
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "request_decision":
        rec = actions.request_decision(arg["id"], arg.get("question", ""))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "submit_review":
        rec = actions.submit_for_review(arg["id"], arg.get("note", ""))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "accept":
        rec = actions.accept_task(arg["id"])
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "dev_queue":
        return {"ok": True, "data": actions.list_dev_queue()}
    if cmd == "review_queue":
        # 用户验收窗口:汇总所有已注册 Agent,但不混入各自的执行中工作集
        return {"ok": True, "data": actions.list_review_queue()}
    if cmd == "agent_queue":
        return {"ok": True, "data": actions.list_agent_queue(
            arg["executor"], root_id=arg.get("root_id"))}
    if cmd == "agent_propose":
        rec = actions.propose_agent_task(
            arg["id"], executor=arg["executor"], root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "agent_approve":
        rec = actions.approve_agent_task(
            arg["id"], executor=arg["executor"], root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "agent_request_decision":
        rec = actions.request_agent_decision(
            arg["id"], arg.get("question", ""), executor=arg["executor"],
            root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "agent_submit_review":
        rec = actions.submit_agent_review(
            arg["id"], arg.get("note", ""), executor=arg["executor"],
            root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "agent_accept":
        rec = actions.accept_agent_task(
            arg["id"], executor=arg["executor"], root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "agent_reject_review":
        rec = actions.reject_agent_review(
            arg["id"], arg.get("reason", ""), executor=arg["executor"],
            root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "agent_reject_start":
        rec = actions.reject_agent_start(
            arg["id"], arg.get("reason", ""), executor=arg["executor"],
            root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "agent_answer_decision":
        rec = actions.answer_agent_decision(
            arg["id"], arg.get("answer", ""), executor=arg["executor"],
            root_id=arg.get("root_id"))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "reject_review":
        rec = actions.reject_review(arg["id"], arg.get("reason", ""))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "reject_start":
        rec = actions.reject_start(arg["id"], arg.get("reason", ""))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    if cmd == "answer_decision":
        rec = actions.answer_decision(arg["id"], arg.get("answer", ""))
        return {"ok": True, "data": {"id": arg["id"], "status": rec["meta"]["status"]}}
    # —— 日常任务(routine)——
    if cmd == "routines":
        return {"ok": True, "data": actions.list_routines()}
    if cmd == "routine_toggle":
        actions.toggle_routine(arg["id"])
        return {"ok": True, "data": {"id": arg["id"]}}
    if cmd == "routine_punch":
        # 精确加减一次打卡(− 按钮用),delta 默认 -1
        actions.punch_routine(arg["id"], int(arg.get("delta", -1)))
        return {"ok": True, "data": {"id": arg["id"]}}
    if cmd == "add_routine":
        rec = actions.add_routine(
            arg["title"],
            category=arg.get("category", "生活"),
            period=arg.get("period", "daily"),
        )
        return {"ok": True, "data": {"id": rec["meta"]["id"]}}
    # —— 双机同步 ——
    if cmd == "sync":
        # 浮窗启动/定时调用:commit 本地改动 + fetch/merge/push 一轮
        return {"ok": True, "data": sync.sync_now()}
    if cmd == "code_sync":
        # 框架仓自动更新(仅快进);updated/changed 供前端决定是否 reload
        return {"ok": True, "data": sync.sync_code()}
    if cmd == "list_conflicts":
        # 冲突副本列表(非空 → 浮窗亮红条提醒人工合并)
        return {"ok": True, "data": sync.list_conflicts()}
    return {"ok": False, "error": f"未知命令:{cmd}"}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tree"
    arg = {}
    if len(sys.argv) > 2:
        try:
            arg = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"参数不是合法JSON:{e}"}))
            return
    try:
        result = _run(cmd, arg)
    except Exception as e:  # 桥要稳:任何错误都转成 JSON,不让前端拿到崩溃
        result = {"ok": False, "error": str(e)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
