#!/usr/bin/env python3
"""Bind private vaults to safe local transport policy."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os import sync


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True,
        text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def exact_root(root: Path) -> Path:
    root = root.expanduser().resolve(strict=True)
    top = Path(git(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if root != top:
        raise RuntimeError("vault path must equal the Git top-level directory")
    return root


def install_work(root: Path) -> None:
    root = exact_root(root)
    remote = git(root, "remote", "get-url", "origin")
    # Binding the observed remote is safe before visibility succeeds: it enables
    # local commits, while sync.py still refuses every network push until the
    # separate authenticated PRIVATE check passes.
    git(root, "config", "--local", "steward.expectedRemote", remote)
    verified, reason = sync._private_remote_verified(root, remote)
    if not verified:
        raise RuntimeError(
            f"remote bound for local commits; network push remains paused: {reason}"
        )
    print("work-vault is bound to an authenticated private remote")


def install_personal(root: Path) -> None:
    root = exact_root(root)
    remotes = git(root, "remote").splitlines()
    if "origin" in remotes:
        git(root, "remote", "set-url", "--push", "origin", "disabled://personal-vault-local-only")
    git(root, "config", "--local", "steward.networkSync", "false")
    print("personal-vault network push is disabled")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--work-vault", type=Path)
    group.add_argument("--personal-vault", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.work_vault:
            install_work(args.work_vault)
        else:
            install_personal(args.personal_vault)
    except (OSError, RuntimeError) as exc:
        print(f"vault guard failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
