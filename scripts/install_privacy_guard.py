#!/usr/bin/env python3
"""Install and verify the repository-local privacy publication guard."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def set_config(repo: Path, key: str, value: str) -> None:
    git(repo, "config", "--local", key, value)


def install(repo: Path, machine: str, denylist: Path | None) -> None:
    repo = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    set_config(repo, "core.hooksPath", ".githooks")
    set_config(repo, "user.name", "Public Maintainer")
    set_config(repo, "user.email", "maintainer@users.noreply.github.com")

    fetch_url = git(repo, "remote", "get-url", "origin")
    if machine == "personal":
        if denylist is None or not denylist.expanduser().resolve().is_file():
            raise RuntimeError("personal machine requires an existing untracked denylist")
        denylist = denylist.expanduser().resolve()
        try:
            relative = denylist.relative_to(repo)
        except ValueError:
            relative = None
        if relative is not None and str(relative) in git(repo, "ls-files").splitlines():
            raise RuntimeError("denylist must not be tracked by the public repository")
        set_config(repo, "privacy.denylistFile", str(denylist))
        set_config(repo, "privacy.publicRemote", fetch_url)
        set_config(repo, "privacy.pushAllowed", "true")
        git(repo, "remote", "set-url", "--push", "origin", fetch_url)
    else:
        set_config(repo, "privacy.pushAllowed", "false")
        git(repo, "config", "--local", "--unset-all", "privacy.denylistFile") if _has(
            repo, "privacy.denylistFile"
        ) else None
        git(repo, "remote", "set-url", "--push", "origin", "disabled://system-code-read-only")


def _has(repo: Path, key: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "--get", key],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return result.returncode == 0


def check(repo: Path, machine: str) -> None:
    repo = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    problems: list[str] = []
    if git(repo, "config", "--get", "core.hooksPath") != ".githooks":
        problems.append("core.hooksPath is not .githooks")
    allowed = git(repo, "config", "--bool", "--get", "privacy.pushAllowed")
    if allowed != ("true" if machine == "personal" else "false"):
        problems.append("privacy.pushAllowed does not match machine role")
    push_url = git(repo, "remote", "get-url", "--push", "origin")
    if machine == "work" and push_url != "disabled://system-code-read-only":
        problems.append("work machine still has a usable system-code push URL")
    if machine == "personal":
        denylist = git(repo, "config", "--path", "--get", "privacy.denylistFile")
        if not denylist or not Path(denylist).is_file():
            problems.append("private denylist is missing")
    if problems:
        raise RuntimeError("; ".join(problems))
    print(f"privacy guard is installed for {machine}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--machine", choices=("personal", "work"), required=True)
    parser.add_argument("--denylist-file", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check:
            check(args.repo, args.machine)
        else:
            install(args.repo, args.machine, args.denylist_file)
            check(args.repo, args.machine)
    except (OSError, RuntimeError) as exc:
        print(f"privacy guard failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
