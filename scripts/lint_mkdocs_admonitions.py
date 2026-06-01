#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Validate and fix MkDocs Material admonition / details indentation in docs/."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS_ROOT = _REPO_ROOT / "docs"

_ADMON_START = re.compile(r"^(!!!|\?\?\?)[ \t]")
_BLOCK_START = re.compile(r"^(!!!|\?\?\?|=== )")
_HEADING = re.compile(r"^#{1,6} ")
_FENCE = re.compile(r"^```")


def _is_admonition_hard_boundary(line: str) -> bool:
    if not line.strip():
        return False
    if _BLOCK_START.match(line):
        return True
    if _HEADING.match(line):
        return True
    if line.strip() == "---":
        return True
    return bool(_FENCE.match(line))


def _fix_admonition_block(lines: list[str], start: int) -> tuple[list[str], int, int]:
    """Return (replacement_lines, index_after_block, fixes_applied)."""
    opener = lines[start]
    body: list[str] = []
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if _is_admonition_hard_boundary(line):
            break
        body.append(line)
        index += 1
    fixes = 0
    fixed_body: list[str] = []
    for line in body:
        if not line.strip():
            fixed_body.append(line)
            continue
        if line.startswith("    "):
            fixed_body.append(line)
            continue
        fixes += 1
        fixed_body.append(f"    {line}")
    return [opener, *fixed_body], index, fixes


def fix_markdown(text: str) -> tuple[str, int]:
    """Return fixed text and number of lines re-indented."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return text, 0
    out: list[str] = []
    fixes = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if _ADMON_START.match(line):
            block, next_index, block_fixes = _fix_admonition_block(lines, index)
            fixes += block_fixes
            out.extend(block)
            index = next_index
            continue
        out.append(line)
        index += 1
    return "".join(out), fixes


def validate_markdown(text: str, path: Path) -> list[str]:
    """Return human-readable violations."""
    _, fixes = fix_markdown(text)
    if fixes == 0:
        return []
    return [
        f"{path}: {fixes} admonition/detail body line(s) missing 4-space indent",
    ]


def iter_doc_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and "README-pypi" not in path.name
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Rewrite files that need indentation fixes.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Markdown files or directories (default: docs/).",
    )
    args = parser.parse_args(argv)
    targets: list[Path] = list(args.paths) or [_DOCS_ROOT]
    files: list[Path] = []
    for target in targets:
        target = target.resolve()
        if target.is_dir():
            files.extend(iter_doc_files(target))
        elif target.suffix == ".md":
            files.append(target)
    violations: list[str] = []
    fixed_files = 0
    for path in files:
        original = path.read_text(encoding="utf-8")
        file_violations = validate_markdown(original, path.relative_to(_REPO_ROOT))
        if not file_violations:
            continue
        violations.extend(file_violations)
        if args.fix:
            updated, _ = fix_markdown(original)
            if updated != original:
                path.write_text(updated, encoding="utf-8")
                fixed_files += 1
    if violations and not args.fix:
        print("\n".join(violations), file=sys.stderr)
        print(
            f"\n{len(violations)} file(s) with broken admonition indentation. "
            "Run with --fix to repair.",
            file=sys.stderr,
        )
        return 1
    if args.fix:
        print(f"Fixed admonition indentation in {fixed_files} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
