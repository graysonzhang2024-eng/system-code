#!/usr/bin/env python3
"""Generate a local launchd plist without storing personal paths in Git."""

from __future__ import annotations

import argparse
import os
import plistlib
import tempfile
from pathlib import Path


def resolve_electron_binary(ui_dir: Path) -> Path:
    """Resolve Electron's native executable from its installed path manifest."""
    ui_dir = ui_dir.resolve()
    package_json = ui_dir / "package.json"
    if not package_json.is_file():
        raise ValueError(f"UI directory has no package.json: {ui_dir}")

    electron_root = ui_dir / "node_modules" / "electron"
    manifest = electron_root / "path.txt"
    if not manifest.is_file():
        raise ValueError("Electron is not installed; run npm install in the ui directory")

    relative = manifest.read_text(encoding="utf-8").strip()
    if not relative:
        raise ValueError("Electron path manifest is empty")
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise ValueError("Electron path manifest must contain a relative path")

    dist_root = (electron_root / "dist").resolve()
    binary = (dist_root / relative_path).resolve()
    try:
        binary.relative_to(dist_root)
    except ValueError as exc:
        raise ValueError("Electron path manifest escapes the dist directory") from exc
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f"Electron native executable is unavailable: {binary}")
    return binary


def build_plist(template: Path, ui_dir: Path, log_dir: Path) -> bytes:
    """Render and validate a launchd plist, returning canonical XML bytes."""
    ui_dir = ui_dir.resolve()
    log_dir = log_dir.resolve()
    electron_binary = resolve_electron_binary(ui_dir)

    replacements = {
        "__ELECTRON_BIN__": str(electron_binary),
        "__UI_DIR__": str(ui_dir),
        "__LOG_DIR__": str(log_dir),
    }
    try:
        parsed = plistlib.loads(template.read_bytes())
    except Exception as exc:
        raise ValueError(f"launchd plist template is invalid: {exc}") from exc

    def replace(value):
        if isinstance(value, str):
            for placeholder, replacement in replacements.items():
                value = value.replace(placeholder, replacement)
            if "__" in value:
                raise ValueError("launchd plist template has an unresolved placeholder")
            return value
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    parsed = replace(parsed)

    arguments = parsed.get("ProgramArguments")
    if arguments != [str(electron_binary), str(ui_dir)]:
        raise ValueError("ProgramArguments must launch Electron with the UI directory")
    return plistlib.dumps(parsed, fmt=plistlib.FMT_XML, sort_keys=False)


def write_plist(template: Path, destination: Path, ui_dir: Path, log_dir: Path) -> None:
    """Atomically write the generated plist to its machine-local destination."""
    payload = build_plist(template, ui_dir, log_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--ui-dir", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        write_plist(args.template, args.destination, args.ui_dir, args.log_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"autostart configuration failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
