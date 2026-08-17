#!/usr/bin/env python3
"""Fail-closed privacy gate for a public Git repository.

The scanner checks tracked working-tree files, reachable commit metadata, and
every reachable historical blob. Project-specific terms belong in an untracked
denylist (one literal per line), never in this public source file.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_BLOB_BYTES = 8 * 1024 * 1024
ALLOWED_EMAIL_DOMAINS = {
    "example.com", "example.net", "example.org", "users.noreply.github.com",
}


@dataclass(frozen=True, order=True)
class Finding:
    source: str
    line: int
    column: int
    rule: str
    description: str


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        error = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(error or f"git {' '.join(args)} failed")
    return result.stdout


def _location(data: bytes, offset: int) -> tuple[int, int]:
    line = data.count(b"\n", 0, offset) + 1
    previous = data.rfind(b"\n", 0, offset)
    return line, offset - previous


def _generic_matches(source: str, data: bytes) -> list[Finding]:
    findings: list[Finding] = []

    patterns: list[tuple[str, re.Pattern[bytes], str]] = [
        (
            "HOME_PATH",
            re.compile(rb"(?i)(?:/Users|/home)/[A-Za-z0-9._-]+"),
            "absolute user-home path",
        ),
        (
            "WINDOWS_HOME_PATH",
            re.compile(rb"(?i)[A-Z]:[\\/]+Users[\\/]+[A-Za-z0-9._-]+"),
            "absolute Windows user-home path",
        ),
        (
            "PRIVATE_KEY",
            re.compile(b"-----BEGIN " + b"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            "private-key material",
        ),
        (
            "PROVIDER_TOKEN",
            re.compile(
                b"(?<![A-Za-z0-9])(?:sk" + b"-[A-Za-z0-9_-]{20,}|"
                b"gh" + b"[pousr]_[A-Za-z0-9]{20,})"
            ),
            "provider token-like value",
        ),
        (
            "URL_CREDENTIAL",
            re.compile(rb"(?i)https?://[^\s/:]+:[^\s/@]+@"),
            "credential embedded in URL",
        ),
        (
            "CREDENTIAL_VALUE",
            re.compile(
                rb"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*"
                rb"['\"]?(?!<|\$\{|example|placeholder)[A-Za-z0-9_./+=-]{20,}"
            ),
            "non-placeholder credential assignment",
        ),
    ]
    for rule, pattern, description in patterns:
        for match in pattern.finditer(data):
            line, column = _location(data, match.start())
            findings.append(Finding(source, line, column, rule, description))

    email_pattern = re.compile(
        rb"(?i)(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@"
        rb"([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![A-Za-z0-9.-])"
    )
    for match in email_pattern.finditer(data):
        domain = match.group(2).decode("ascii", "ignore").lower()
        if domain in ALLOWED_EMAIL_DOMAINS:
            continue
        line, column = _location(data, match.start())
        findings.append(Finding(source, line, column, "EMAIL", "non-example email address"))
    return findings


def _denylist_matches(source: str, data: bytes, terms: list[bytes]) -> list[Finding]:
    folded = data.lower()
    findings: list[Finding] = []
    for term in terms:
        start = 0
        needle = term.lower()
        while True:
            offset = folded.find(needle, start)
            if offset < 0:
                break
            line, column = _location(data, offset)
            findings.append(Finding(
                source, line, column, "PRIVATE_DENYLIST", "private denylist match"
            ))
            start = offset + max(1, len(needle))
    return findings


def scan_bytes(source: str, data: bytes, terms: list[bytes]) -> list[Finding]:
    return _generic_matches(source, data) + _denylist_matches(source, data, terms)


def _load_denylist(path: Path | None, required: bool) -> list[bytes]:
    if path is None:
        if required:
            raise RuntimeError("a private denylist is required but was not provided")
        return []
    if not path.is_file():
        raise RuntimeError("private denylist file does not exist")
    terms: list[bytes] = []
    for raw in path.read_bytes().splitlines():
        term = raw.strip()
        if not term or term.startswith(b"#"):
            continue
        if all(byte < 128 for byte in term) and len(term) < 4:
            raise RuntimeError("ASCII denylist terms must contain at least four bytes")
        terms.append(term)
    return terms


def _safe_source(path: str, terms: list[bytes]) -> str:
    raw = path.encode("utf-8", "surrogateescape").lower()
    return "<redacted-path>" if any(term.lower() in raw for term in terms) else path


def _scan_worktree(repo: Path, terms: list[bytes]) -> list[Finding]:
    tracked = _git(repo, "ls-files", "-z").split(b"\0")
    tracked = [item for item in tracked if item]
    tracked_set = {item.decode("utf-8", "surrogateescape") for item in tracked}
    findings: list[Finding] = []
    for raw_path in tracked:
        relative = raw_path.decode("utf-8", "surrogateescape")
        source = _safe_source(f"worktree:{relative}", terms)
        findings.extend(scan_bytes(source, raw_path, terms))
        path = repo / relative
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8", "surrogateescape")
        else:
            data = path.read_bytes()
        if len(data) > MAX_BLOB_BYTES:
            raise RuntimeError(f"tracked file exceeds scan limit: {source}")
        findings.extend(scan_bytes(source, data, terms))
    return findings


def _scan_index(repo: Path, terms: list[bytes]) -> list[Finding]:
    """Scan the exact staged snapshot without reading unstaged files."""
    entries = _git(repo, "ls-files", "--stage", "-z").split(b"\0")
    findings: list[Finding] = []
    for item in entries:
        if not item:
            continue
        meta, raw_path = item.split(b"\t", 1)
        mode, oid, stage = meta.split(b" ", 2)
        if stage != b"0":
            raise RuntimeError("index contains unresolved merge entries")
        relative = raw_path.decode("utf-8", "surrogateescape")
        source = _safe_source(f"index:{relative}", terms)
        findings.extend(scan_bytes(source, raw_path, terms))
        data = _git(repo, "cat-file", "blob", oid.decode("ascii"))
        if len(data) > MAX_BLOB_BYTES:
            raise RuntimeError(f"staged blob exceeds scan limit: {source}")
        findings.extend(scan_bytes(source, data, terms))
    return findings


def _scan_history(repo: Path, refs: list[str], terms: list[bytes]) -> list[Finding]:
    if not refs:
        return []
    commits = [item for item in _git(repo, "rev-list", *refs).splitlines() if item]
    findings: list[Finding] = []
    seen_blobs: set[bytes] = set()
    for raw_sha in commits:
        sha = raw_sha.decode("ascii")
        commit = _git(repo, "cat-file", "commit", sha)
        source = f"commit:{sha[:12]}"
        findings.extend(scan_bytes(source, commit, terms))
        for header in commit.splitlines():
            if not (header.startswith(b"author ") or header.startswith(b"committer ")):
                continue
            match = re.search(rb"<([^<>]+)>", header)
            if not match:
                raise RuntimeError(f"malformed commit identity: {source}")
            email = match.group(1).decode("utf-8", "replace").lower()
            if not email.endswith("@users.noreply.github.com"):
                findings.append(Finding(
                    source, 1, 1, "COMMIT_EMAIL_NOT_NOREPLY",
                    "public commit identity must use GitHub noreply email",
                ))

        tree = _git(repo, "ls-tree", "-r", "-z", sha)
        for item in tree.split(b"\0"):
            if not item:
                continue
            meta, raw_path = item.split(b"\t", 1)
            _mode, kind, oid = meta.split(b" ", 2)
            relative = raw_path.decode("utf-8", "surrogateescape")
            blob_source = _safe_source(f"history:{sha[:12]}:{relative}", terms)
            findings.extend(scan_bytes(blob_source, raw_path, terms))
            if kind != b"blob" or oid in seen_blobs:
                continue
            seen_blobs.add(oid)
            data = _git(repo, "cat-file", "blob", oid.decode("ascii"))
            if len(data) > MAX_BLOB_BYTES:
                raise RuntimeError(f"historical blob exceeds scan limit: {blob_source}")
            findings.extend(scan_bytes(blob_source, data, terms))
    return findings


def _identity_findings(repo: Path) -> list[Finding]:
    identity = _git(repo, "var", "GIT_AUTHOR_IDENT").decode("utf-8", "replace")
    match = re.search(r"<([^<>]+)>", identity)
    if match and match.group(1).lower().endswith("@users.noreply.github.com"):
        return []
    return [Finding(
        "config:user.email", 1, 1, "CONFIG_EMAIL_NOT_NOREPLY",
        "public repository identity must use GitHub noreply email",
    )]


def run(
    repo: Path,
    ref: str | list[str],
    denylist: Path | None,
    required: bool,
    *,
    staged: bool = False,
    check_identity: bool = False,
    history_only: bool = False,
) -> list[Finding]:
    repo = repo.resolve()
    _git(repo, "rev-parse", "--show-toplevel")
    terms = _load_denylist(denylist, required)
    if denylist is not None:
        try:
            relative = denylist.resolve().relative_to(repo)
        except ValueError:
            relative = None
        if relative is not None:
            tracked = {
                item.decode("utf-8", "surrogateescape")
                for item in _git(repo, "ls-files", "-z").split(b"\0") if item
            }
            if str(relative) in tracked:
                raise RuntimeError("private denylist must not be tracked")
    refs = [ref] if isinstance(ref, str) else list(ref)
    snapshot = [] if history_only else (
        _scan_index(repo, terms) if staged else _scan_worktree(repo, terms)
    )
    identity = _identity_findings(repo) if check_identity else []
    return sorted(set(snapshot + _scan_history(repo, refs, terms) + identity))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--ref", action="append", dest="refs")
    parser.add_argument("--denylist-file", type=Path)
    parser.add_argument("--require-denylist", action="store_true")
    parser.add_argument("--staged", action="store_true",
                        help="scan the Git index instead of the working tree")
    parser.add_argument("--check-identity", action="store_true",
                        help="require the active repository email to be GitHub noreply")
    parser.add_argument("--history-only", action="store_true",
                        help="scan only commits reachable from the supplied refs")
    args = parser.parse_args(argv)
    denylist = args.denylist_file
    if denylist is None and os.environ.get("SYSTEM_CODE_PRIVACY_DENYLIST_FILE"):
        denylist = Path(os.environ["SYSTEM_CODE_PRIVACY_DENYLIST_FILE"])
    try:
        findings = run(
            args.repo, args.refs if args.refs is not None else ["HEAD"],
            denylist, args.require_denylist,
            staged=args.staged, check_identity=args.check_identity,
            history_only=args.history_only,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"privacy scan failed: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(
            f"{finding.source}:{finding.line}:{finding.column} "
            f"[{finding.rule}] {finding.description}"
        )
    if findings:
        print(f"privacy scan found {len(findings)} issue(s)", file=sys.stderr)
        return 1
    print("privacy scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
