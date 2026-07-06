"""Verification plan construction and optional execution."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from review_kit.git_evidence import collect_paths
from review_kit.paths import path_matches

_SHELL_METACHAR_SEQUENCES = ("|", ";", "&&", "||", "$(", "`", ">", "<", "\n", "\r")


def _path_touched(path: str, patterns: list[str]) -> bool:
    return any(path_matches(path, pattern) for pattern in patterns)


def parse_safe_argv(command: str) -> list[str] | None:
    """Parse a verification command without shell interpretation."""
    stripped = command.strip()
    if not stripped:
        return None
    for sequence in _SHELL_METACHAR_SEQUENCES:
        if sequence in stripped:
            return None
    try:
        argv = shlex.split(stripped, posix=True)
    except ValueError:
        return None
    return argv or None


def command_is_approved(command: str, approved: Sequence[str]) -> bool:
    argv = parse_safe_argv(command)
    if argv is None:
        return False
    normalized = " ".join(argv)
    prefixes = sorted(
        (str(item).strip() for item in approved if str(item).strip()),
        key=len,
        reverse=True,
    )
    for prefix in prefixes:
        prefix_argv = parse_safe_argv(prefix)
        if prefix_argv is None:
            continue
        prefix_normalized = " ".join(prefix_argv)
        if normalized == prefix_normalized or normalized.startswith(
            f"{prefix_normalized} "
        ):
            return True
    return False


def build_verification_plan(
    files: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    mode: str,
) -> list[dict[str, str]]:
    paths = collect_paths(files)
    plan: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(command: str, reason: str, trigger: str) -> None:
        if command in seen:
            return
        seen.add(command)
        plan.append({"command": command, "reason": reason, "trigger": trigger})

    if any(path.endswith(".py") for path in paths):
        add(
            "uv run pytest -q tests/test_architecture.py",
            "architecture boundary guard",
            "python_change",
        )
    if "pyproject.toml" in paths or "uv.lock" in paths:
        add("uv lock --check", "lockfile consistency", "packaging_change")
    if mode == "release":
        release = policy.get("release_mode", {})
        mandatory = release.get("mandatory_verification_when_touched", {})
        _add_verification_map(add, paths, mandatory, "release mandatory for")

    surface_map = policy.get("surface_verification", {})
    _add_verification_map(add, paths, surface_map, "surface verification for")

    return plan


def _add_verification_map(
    add: Callable[[str, str, str], None],
    paths: list[str],
    command_map: object,
    reason_prefix: str,
) -> None:
    if not isinstance(command_map, dict):
        return
    for pattern, commands in command_map.items():
        if not isinstance(commands, list):
            continue
        if not any(_path_touched(path, [str(pattern)]) for path in paths):
            continue
        for command in commands:
            if isinstance(command, str):
                add(command, f"{reason_prefix} {pattern}", str(pattern))


def _verification_result(
    item: dict[str, str],
    *,
    status: str,
    exit_code: int | None,
    summary: str,
) -> dict[str, Any]:
    return {**item, "status": status, "exit_code": exit_code, "summary": summary}


def _resolve_command_argv(
    command: str,
    approved: Sequence[str],
) -> tuple[list[str] | None, str | None]:
    if approved and not command_is_approved(command, approved):
        return None, "command not in approved_read_only_commands"
    argv = parse_safe_argv(command)
    if argv is None:
        return None, "command contains unsupported shell syntax"
    return argv, None


def _execute_plan_item(
    item: dict[str, str],
    *,
    execute: bool,
    approved: Sequence[str],
) -> dict[str, Any]:
    if not execute:
        return _verification_result(item, status="planned", exit_code=None, summary="")

    command = item["command"]
    argv, rejection = _resolve_command_argv(command, approved)
    if rejection is not None or argv is None:
        return _verification_result(
            item,
            status="rejected",
            exit_code=None,
            summary=rejection or "command contains unsupported shell syntax",
        )

    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
    except OSError as exc:
        return _verification_result(
            item, status="error", exit_code=None, summary=str(exc)
        )

    summary = (completed.stdout or completed.stderr or "").strip().splitlines()
    tail = "\n".join(summary[-20:]) if summary else ""
    status = "passed" if completed.returncode == 0 else "failed"
    return _verification_result(
        item,
        status=status,
        exit_code=completed.returncode,
        summary=tail,
    )


def run_verification_plan(
    plan: list[dict[str, str]],
    *,
    execute: bool,
    approved_commands: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    approved = list(approved_commands or [])
    return [
        _execute_plan_item(item, execute=execute, approved=approved) for item in plan
    ]
