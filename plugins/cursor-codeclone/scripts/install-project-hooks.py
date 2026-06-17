#!/usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Install CodeClone project hooks (.cursor/hooks.json) for the Hooks UI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_VALID_ENFORCE_SCOPES = frozenset({"python", "repo"})


def _repo_root(plugin_root: Path) -> Path | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(plugin_root.parent.parent),
                "rev-parse",
                "--show-toplevel",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(result.stdout.strip())


def _hook_commands(target_root: Path, plugin_root: Path) -> tuple[str, str, str]:
    monorepo_hook = (
        target_root / "plugins" / "cursor-codeclone" / "hooks" / "run_hook.py"
    )
    if monorepo_hook.is_file():
        launcher = "plugins/cursor-codeclone/hooks/run_hook.py"
    else:
        launcher = str((plugin_root / "hooks" / "run_hook.py").as_posix())
    python = sys.executable
    pre = f'"{python}" {launcher} pre-tool-use-gate'
    post = f'"{python}" {launcher} post-tool-use'
    stop = f'"{python}" {launcher} session-cleanup'
    return pre, post, stop


def _write_hooks_config(hooks_dir: Path, enforce_scope: str) -> Path:
    config_path = hooks_dir / "codeclone-hooks.json"
    config_path.write_text(
        json.dumps({"enforce_scope": enforce_scope}, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path


def main(argv: list[str] | None = None) -> int:
    plugin_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target_root",
        nargs="?",
        help="Repository root (default: git toplevel from plugin path)",
    )
    parser.add_argument(
        "--enforce-scope",
        choices=sorted(_VALID_ENFORCE_SCOPES),
        default="python",
        help=(
            "preToolUse gate: python (.py/.pyi only) or repo "
            "(all files under workspace root)"
        ),
    )
    args = parser.parse_args(list(argv or sys.argv[1:]))

    if args.target_root:
        target_root = Path(args.target_root).resolve()
    else:
        target_root = _repo_root(plugin_root) or Path.cwd()

    enforce_scope = args.enforce_scope
    if enforce_scope not in _VALID_ENFORCE_SCOPES:
        print(f"Invalid enforce_scope: {enforce_scope}", file=sys.stderr)
        return 2

    pre_cmd, post_cmd, stop_cmd = _hook_commands(target_root, plugin_root)
    hooks_dir = target_root / ".cursor"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    config_path = _write_hooks_config(hooks_dir, enforce_scope)
    hooks_json = hooks_dir / "hooks.json"
    payload = {
        "version": 1,
        "hooks": {
            "preToolUse": [
                {
                    "command": pre_cmd,
                    "type": "command",
                    "timeout": 5,
                    "matcher": "Write|StrReplace|ApplyPatch|Shell",
                    "failClosed": True,
                }
            ],
            "postToolUse": [
                {
                    "command": post_cmd,
                    "type": "command",
                    "timeout": 5,
                    "matcher": "Write|StrReplace|ApplyPatch",
                }
            ],
            "stop": [
                {
                    "command": stop_cmd,
                    "type": "command",
                    "timeout": 5,
                    "loop_limit": 1,
                }
            ],
        },
    }
    hooks_json.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {hooks_json}")
    print(f"Wrote {config_path} (enforce_scope={enforce_scope!r})")
    print("Reload the workspace or restart Cursor. Trust the workspace if prompted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
