"""sync.py —— 双机并行同步层。

【解决什么】
两台机(工作机/个人机)并行读写同一个 work-vault git 仓。git 是传输层,
本模块把"用前 pull、用后 push"的人工纪律变成全自动:
  - 写入后:本地立即 commit(毫秒级,不阻塞 UI)+ 后台进程 fetch/merge/push
  - 拉取时:merge 冲突**不丢数据**——本机版保留为正本,
    对方版另存为 <原文件名>.conflict-<sha>,浮窗检测到会亮红条提醒人工合并
  - 无 .git / 无 origin(如 fixtures 开发、单机使用)→ 全部静默跳过

【防并发】
.git/steward-sync.lock 目录锁:同一时刻只跑一轮同步;锁被占时改置
.pending 标记,持有锁的进程收尾时看到标记会再跑一轮(不丢同步)。
锁超过 120 秒视为僵尸锁(进程被杀),自动破除。

【命令行】
  python3 -m system_os.sync now   # 同步一轮,打印 JSON 结果(浮窗调)
  python3 -m system_os.sync run   # 带锁跑(后台进程入口,由 push_detached 拉起)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .machine import detect_machine

# 框架仓根目录(system-os 包的上一级),后台进程以它为 cwd 才能 import system_os
_CODE_ROOT = Path(__file__).resolve().parent.parent

_LOCK_NAME = "steward-sync.lock"
_PENDING_NAME = "steward-sync.pending"
_LOG_NAME = "steward-sync.log"
_STALE_SECONDS = 120  # 锁超过这个年龄视为僵尸锁,自动破除


def machine_tag() -> str:
    """提交信息里的机器标识,如 'work' / 'personal'。"""
    return detect_machine()


def _vault_root() -> Path:
    return Path(config.work_vault_path())


def _enabled(root: Path) -> bool:
    """vault 是带 origin 的 git 仓才启用同步;否则(fixtures 等)静默跳过。"""
    if not (root / ".git").exists():
        return False
    r = _git(root, "remote")
    return r is not None and "origin" in r.stdout


def _git(root: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess | None:
    """跑一条 git 命令,失败/超时返回 None(同步层永远不向上抛错)。"""
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None


# ============================================================
# 第一步:本地 commit(快,写操作后立刻做)
# ============================================================
def commit_all(msg: str) -> bool:
    """把 vault 里的所有改动 commit。有改动并提交成功返回 True,否则 False。

    提交身份用内置的 steward-<机器> 署名:
    - 不依赖每台机配置 git user.name/email(个人机零配置可用)
    - 历史里一眼分清"系统自动提交"和"人的手动提交"
    """
    root = _vault_root()
    if not _enabled(root):
        return False
    _git(root, "add", "-A")
    # 暂存区为空 = 没改动,不制造空提交
    diff = _git(root, "diff", "--cached", "--quiet")
    if diff is not None and diff.returncode == 0:
        return False
    r = _git(root,
             "-c", f"user.name=steward-{machine_tag()}",
             "-c", f"user.email=steward-{machine_tag()}@local",
             "commit", "-m", msg)
    return r is not None and r.returncode == 0


# ============================================================
# 第二步:后台同步一轮(fetch → merge → push,冲突保双份)
# ============================================================
def sync_now() -> dict:
    """同步一轮。返回结果字典(也供浮窗 os_api 调用)。绝不抛异常。"""
    result = {"committed": False, "merged": False, "pushed": False,
              "conflicts": [], "error": None}
    root = _vault_root()
    if not _enabled(root):
        result["error"] = "not-a-git-repo"
        return result
    try:
        # 先把本地未提交的改动收进历史(比如后台进程跑时 UI 又勾了几下)
        result["committed"] = commit_all(f"auto({machine_tag()}): sync point")

        fetch = _git(root, "fetch", "origin", timeout=45)
        if fetch is None or fetch.returncode != 0:
            result["error"] = "fetch-failed(可能断网)"
            return result

        branch_r = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        branch = (branch_r.stdout.strip() if branch_r else "") or "main"

        # 本地是否落后远端(对方机推了新东西)?
        counts = _git(root, "rev-list", "--left-right", "--count",
                      f"HEAD...origin/{branch}")
        behind = 0
        if counts and counts.returncode == 0:
            parts = counts.stdout.split()
            if len(parts) == 2:
                behind = int(parts[1])

        if behind > 0:
            merge = _git(root,
                         "-c", f"user.name=steward-{machine_tag()}",
                         "-c", f"user.email=steward-{machine_tag()}@local",
                         "merge", "--no-edit", f"origin/{branch}")
            if merge is not None and merge.returncode != 0:
                if (root / ".git" / "MERGE_HEAD").exists():
                    # 真冲突:本机版留正本,对方版存 .conflict-<sha> 副本,完成 merge
                    result["conflicts"] = _resolve_conflicts_keep_both(root)
                else:
                    result["error"] = f"merge-failed: {(merge.stderr or '')[:200]}"
                    return result
            result["merged"] = True

        push = _git(root, "push", "origin", f"HEAD:{branch}", timeout=45)
        result["pushed"] = push is not None and push.returncode == 0
        if not result["pushed"]:
            result["error"] = "push-failed(可能断网,下轮补)"
    except Exception as e:  # 双保险:同步层任何意外都不能炸到调用方
        result["error"] = str(e)
    return result


def _resolve_conflicts_keep_both(root: Path) -> list[str]:
    """merge 冲突收尾:每个冲突文件保留本机版为正本,对方版存副本。

    副本名:<原路径>.conflict-<对方提交短sha>,会一起提交并推到远端,
    这样两台机都能看到冲突副本,浮窗红条在哪边都会亮。
    """
    sha_r = _git(root, "rev-parse", "--short", "MERGE_HEAD")
    sha = (sha_r.stdout.strip() if sha_r and sha_r.returncode == 0 else "") or "remote"

    files_r = _git(root, "diff", "--name-only", "--diff-filter=U")
    if files_r is None or files_r.returncode != 0:
        _git(root, "merge", "--abort")
        return []

    conflicts: list[str] = []
    for rel in files_r.stdout.split():
        rel = rel.strip()
        if not rel:
            continue
        ours = _git(root, "show", f":2:{rel}")    # :2 = 本机版(HEAD)
        theirs = _git(root, "show", f":3:{rel}")  # :3 = 对方版(MERGE_HEAD)
        target = root / rel
        if ours is not None and ours.returncode == 0:
            target.write_text(ours.stdout, encoding="utf-8")
        if theirs is not None and theirs.returncode == 0:
            (root / f"{rel}.conflict-{sha}").write_text(theirs.stdout, encoding="utf-8")
        _git(root, "add", "--", rel, f"{rel}.conflict-{sha}")
        conflicts.append(rel)

    _git(root,
         "-c", f"user.name=steward-{machine_tag()}",
         "-c", f"user.email=steward-{machine_tag()}@local",
         "commit", "--no-edit")
    return conflicts


# ============================================================
# 框架仓(system-code)自动更新
# ============================================================
def sync_code() -> dict:
    """拉取框架仓最新代码。只快进(--ff-only),绝不 merge/rebase。

    生效方式(利用架构特点,无需人工重启):
    - Python 改动:立即生效——浮窗每次调用都拉起新 python 进程
    - ui/src 渲染层改动:main.js 收到结果后 reload 窗口
    - main.js 改动:main.js 自己 relaunch 整个 app
    本地有领先提交(开发机场景)→ 跳过不硬来;断网 → 报错下轮再试。
    """
    result = {"updated": False, "changed": [], "behind": 0, "error": None}
    root = _CODE_ROOT
    if not (root / ".git").exists():
        result["error"] = "not-a-git-repo"
        return result
    try:
        fetch = _git(root, "fetch", "origin", timeout=45)
        if fetch is None or fetch.returncode != 0:
            result["error"] = "fetch-failed(可能断网)"
            return result
        branch_r = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        branch = (branch_r.stdout.strip() if branch_r else "") or "main"
        counts = _git(root, "rev-list", "--left-right", "--count",
                      f"HEAD...origin/{branch}")
        ahead = behind = 0
        if counts and counts.returncode == 0:
            parts = counts.stdout.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])
        result["behind"] = behind
        if behind == 0:
            return result
        if ahead > 0:
            result["error"] = f"本地领先 {ahead} 个提交(开发机?),跳过自动更新"
            return result
        pull = _git(root, "pull", "--ff-only", "origin", branch, timeout=60)
        if pull is None or pull.returncode != 0:
            result["error"] = "ff-only-failed(可能有本地未提交改动)"
            return result
        diff = _git(root, "diff", "--name-only", "ORIG_HEAD..HEAD")
        if diff and diff.returncode == 0:
            result["changed"] = [f for f in diff.stdout.split() if f.strip()]
        result["updated"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


# ============================================================
# 后台进程入口(带锁)
# ============================================================
def push_detached() -> None:
    """拉起一个后台进程跑同步(立即返回,不阻塞调用方)。

    工作机理:写操作(勾选任务等)只要毫秒级的本地 commit,网络部分
    全部交给这个 detached 子进程慢慢跑;失败了也有下一轮定时同步兜底。
    """
    root = _vault_root()
    if not _enabled(root):
        return
    log_path = root / ".git" / _LOG_NAME
    try:
        logf = open(log_path, "a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, "-m", "system_os.sync", "run"],
            cwd=str(_CODE_ROOT),
            stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True,   # 脱离父进程:父进程(浮窗等)退出它也能跑完
            env=os.environ.copy(),
        )
    except Exception:
        pass


def _run_locked() -> None:
    """带锁跑同步;锁被占则挂 .pending 标记,让持有锁的那轮收尾时补跑。"""
    root = _vault_root()
    gitdir = root / ".git"
    lock, pending = gitdir / _LOCK_NAME, gitdir / _PENDING_NAME

    # 破除僵尸锁(进程被 kill 留下的)
    if lock.exists():
        try:
            if time.time() - lock.stat().st_mtime > _STALE_SECONDS:
                lock.rmdir()
        except OSError:
            pass
    try:
        lock.mkdir()
    except FileExistsError:
        pending.touch()
        return
    try:
        while True:
            print(json.dumps(sync_now(), ensure_ascii=False), flush=True)
            if pending.exists():
                pending.unlink()
                continue  # 本轮期间又有新写入,再跑一轮
            break
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


# ============================================================
# 冲突查询(浮窗红条用)
# ============================================================
def list_conflicts() -> list[str]:
    """列出 vault 里所有冲突副本(相对路径),供浮窗显示人工合并提醒。"""
    root = _vault_root()
    if not root.exists():
        return []
    out = []
    for p in root.rglob("*.conflict-*"):
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        out.append(str(p.relative_to(root)))
    return sorted(out)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "now"
    if cmd == "run":
        _run_locked()
    else:
        print(json.dumps(sync_now(), ensure_ascii=False))


if __name__ == "__main__":
    main()
