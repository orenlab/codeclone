# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Shared hook I/O and Cursor contract helpers for CodeClone plugin hooks."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_SHELL_CHAIN_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")

MAX_STDIN_BYTES = 65536
_EMPTY_JSON = "{}"

_PYTHON_SUFFIXES = (".py", ".pyi")
_WRITE_TOOLS = frozenset({"Write", "StrReplace", "ApplyPatch"})
_SHELL_WRAPPER_EXECUTABLES = frozenset(
    {"sh", "bash", "zsh", "fish", "dash", "ksh", "cmd", "cmd.exe"}
)
_SAFE_GIT_SUBCOMMANDS = frozenset(
    {
        "branch",
        "describe",
        "diff",
        "log",
        "ls-files",
        "merge-base",
        "rev-parse",
        "show",
        "status",
        "symbolic-ref",
    }
)
_SAFE_GIT_CONFIG_FLAGS = frozenset({"--get", "--get-all", "--get-regexp", "--list"})

_HOOKS_CONFIG_REL = Path(".cursor") / "codeclone-hooks.json"
_ENFORCE_SCOPE_PYTHON = frozenset({"python", "python-only", "python_only"})
_ENFORCE_SCOPE_REPO = frozenset(
    {"repo", "repository", "all", "all-files", "all_files", "all-files-in-repo"}
)


@dataclass(frozen=True, slots=True)
class HookGateDecision:
    allowed: bool
    reason: str
    detail: str = ""


class WorkspaceIntentGateUnavailable(RuntimeError):
    """Raised when the hook cannot import or execute CodeClone's gate API."""


def normalize_enforce_scope(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in _ENFORCE_SCOPE_REPO:
        return "repo"
    return "python"


def resolve_enforce_scope(repo_root: Path) -> str:
    env_value = os.environ.get("CODECLONE_HOOKS_ENFORCE_SCOPE", "").strip()
    if env_value:
        return normalize_enforce_scope(env_value)
    config_path = repo_root / _HOOKS_CONFIG_REL
    if config_path.is_file():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "python"
        if isinstance(raw, dict):
            file_value = raw.get("enforce_scope")
            if isinstance(file_value, str) and file_value.strip():
                return normalize_enforce_scope(file_value)
    return "python"


def resolve_path_under_workspace(file_path: str, workspace_root: str) -> Path | None:
    if is_unsafe_path(file_path) or not workspace_root:
        return None
    root = Path(workspace_root).resolve()
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (ValueError, OSError):
        return None
    return resolved


def _strip_leading_shell_env_assignments(tokens: list[str]) -> list[str]:
    remaining = list(tokens)
    while remaining:
        token = remaining[0]
        if "=" in token and not token.startswith("=") and not token.startswith("-"):
            key = token.split("=", 1)[0]
            if key and (key[0].isalpha() or key.startswith("_")):
                remaining.pop(0)
                continue
        break
    return remaining


def _segment_invokes_git(segment: str) -> bool:
    segment = segment.strip()
    if not segment:
        return True
    try:
        tokens = shlex.split(segment, posix=os.name != "nt")
    except ValueError:
        return False
    tokens = _strip_leading_shell_env_assignments(tokens)
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    if executable in _SHELL_WRAPPER_EXECUTABLES:
        for index, token in enumerate(tokens[1:], start=1):
            if token in {"-c", "/c"}:
                if index + 1 >= len(tokens):
                    return False
                inner = " ".join(tokens[index + 1 :])
                return _segment_invokes_git(inner)
        return False
    if executable != "git" or len(tokens) < 2:
        return False
    subcommand = tokens[1].lower()
    if subcommand == "config":
        return len(tokens) >= 3 and tokens[2] in _SAFE_GIT_CONFIG_FLAGS
    if subcommand == "branch":
        return tokens[2:] in ([], ["--show-current"])
    return subcommand in _SAFE_GIT_SUBCOMMANDS


def is_git_shell_command(command: str) -> bool:
    """True when every chained shell segment invokes the git executable."""
    stripped = command.strip()
    if not stripped:
        return False
    segments = [part for part in _SHELL_CHAIN_SPLIT.split(stripped) if part.strip()]
    if not segments:
        return False
    return all(_segment_invokes_git(segment) for segment in segments)


def shell_command_from_hook(data: Mapping[str, object]) -> str:
    if str(data.get("tool_name", "")) != "Shell":
        return ""
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command")
    return command if isinstance(command, str) else ""


def should_gate_shell_command(*, command: str) -> bool:
    """Gate shell commands except read-only Git inspection (no intent)."""
    return bool(command.strip()) and not is_git_shell_command(command)


def should_gate_edit_path(
    *,
    target_path: str,
    workspace_root: str,
    enforce_scope: str,
) -> bool:
    if not target_path or not workspace_root:
        return False
    if enforce_scope == "repo":
        return resolve_path_under_workspace(target_path, workspace_root) is not None
    return is_python_source_path(target_path)


def read_bounded_stdin(max_bytes: int = MAX_STDIN_BYTES) -> str:
    payload = sys.stdin.buffer.read(max_bytes + 1)
    if len(payload) > max_bytes:
        return ""
    return payload.decode("utf-8", errors="replace")


def emit_hook_payload(payload: Mapping[str, object] | None = None) -> None:
    if payload:
        print(json.dumps(dict(payload)))
    else:
        print(_EMPTY_JSON)


def parse_hook_input(raw: str) -> dict[str, object] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def is_unsafe_path(file_path: str) -> bool:
    if not file_path or "\0" in file_path:
        return True
    parts = file_path.replace("\\", "/").split("/")
    return ".." in parts


def is_python_source_path(file_path: str) -> bool:
    if is_unsafe_path(file_path):
        return False
    lowered = file_path.lower()
    return any(lowered.endswith(suffix) for suffix in _PYTHON_SUFFIXES)


def edited_path_from_pre_tool_use(data: Mapping[str, object]) -> str:
    return edited_path_from_post_tool_use(data)


def edited_path_from_post_tool_use(data: Mapping[str, object]) -> str:
    tool_name = str(data.get("tool_name", ""))
    if tool_name not in _WRITE_TOOLS:
        return ""
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    for key in ("path", "file_path", "target_file"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def workspace_root_from_hook(data: Mapping[str, object]) -> str:
    roots = data.get("workspace_roots")
    if isinstance(roots, list) and roots:
        first = roots[0]
        if isinstance(first, str) and first:
            return str(Path(first).resolve())
    return ""


def python_edit_reminder_context(*, workspace_root: str) -> str:
    root_hint = workspace_root or "<absolute repository root>"
    return (
        "CodeClone: a Python source file was just edited. Before claiming the task "
        "is done, run the change-control pipeline when MCP is available: "
        f"`analyze_repository(root={root_hint!r})` (after-run if the finish profile "
        "requires it), then `finish_controlled_change` with the active `intent_id`. "
        "After `start_controlled_change` with `edit_allowed=true`, use "
        f"`get_relevant_memory(root={root_hint!r}, scope=... or intent_id=...)` — "
        "`root` is required."
    )


def transcript_path_from_hook(data: Mapping[str, object]) -> str:
    value = data.get("transcript_path")
    return value if isinstance(value, str) else ""


def evaluate_workspace_intent_gate(repo_root: Path) -> HookGateDecision:
    try:
        from codeclone.workspace_intent.gate import evaluate_workspace_edit_gate
    except Exception as exc:  # pragma: no cover - exercised via hook behavior
        raise WorkspaceIntentGateUnavailable(str(exc)) from exc
    try:
        decision = evaluate_workspace_edit_gate(repo_root)
    except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
        raise WorkspaceIntentGateUnavailable(str(exc)) from exc
    return HookGateDecision(
        allowed=bool(decision.allowed),
        reason=str(decision.reason),
        detail=_decision_detail(decision),
    )


def _decision_detail(decision: object) -> str:
    intent_id = getattr(decision, "intent_id", None)
    reason = getattr(decision, "reason", None)
    registry_backend = getattr(decision, "registry_backend", None)
    registry_path = getattr(decision, "registry_path", None)
    parts = [f"reason={reason}"]
    if intent_id:
        parts.append(f"intent_id={intent_id}")
    if registry_backend:
        parts.append(f"registry={registry_backend}:{registry_path}")
    return ", ".join(parts)


def change_control_denial_payload(
    *,
    workspace_root: str,
    target_path: str,
    enforce_scope: str = "python",
    blocked_kind: str = "file",
) -> dict[str, str]:
    root_hint = workspace_root or "<absolute repository root>"
    if blocked_kind == "shell":
        target_label = "shell commands other than read-only Git inspection"
        user_message = (
            "CodeClone blocked a shell command without an active "
            "workspace change intent."
        )
        detail = f"shell command: {target_path}"
    elif blocked_kind == "registry":
        target_label = "repository tool use"
        user_message = (
            "CodeClone blocked tool use because the hook cannot verify "
            "workspace change intent."
        )
        detail = target_path or "workspace intent registry unavailable"
    elif enforce_scope == "repo":
        target_label = "repository files"
        user_message = (
            "CodeClone blocked a repository write without an active "
            "workspace change intent."
        )
        detail = target_path
    else:
        target_label = "Python source"
        user_message = (
            "CodeClone blocked a Python write without an active "
            "workspace change intent."
        )
        detail = target_path
    agent_message = (
        "CodeClone change control: call MCP `start_controlled_change` before "
        f"{target_label} (`{detail}`). Without an authorized workspace intent, "
        "direct file writes inside the repository are blocked, including `.git/**`; "
        "only read-only Git inspection shell commands are allowed. Required sequence: "
        f"`analyze_repository(root={root_hint!r})` → "
        f"`start_controlled_change(root={root_hint!r}, scope={{allowed_files:[...]}}, "
        "intent=...)` → edit only inside scope → after-run analyze if needed → "
        f"`finish_controlled_change(intent_id=...)`. "
        "Enforcement scope: "
        f"{enforce_scope!r} (CODECLONE_HOOKS_ENFORCE_SCOPE or "
        ".cursor/codeclone-hooks.json)."
    )
    return {
        "permission": "deny",
        "user_message": user_message,
        "agent_message": agent_message,
    }


_MCP_WORKFLOW_OPEN = frozenset({"start", "declare"})
_MCP_WORKFLOW_CLOSE = frozenset({"finish", "clear"})


def _mcp_workflow_event_from_call_mcp_tool(
    tool_input: Mapping[str, object],
) -> str | None:
    tool_name = tool_input.get("toolName")
    if not isinstance(tool_name, str):
        return None
    if tool_name == "start_controlled_change":
        return "start"
    if tool_name == "finish_controlled_change":
        return "finish"
    if tool_name != "manage_change_intent":
        return None
    arguments = tool_input.get("arguments")
    if not isinstance(arguments, Mapping):
        return None
    action = arguments.get("action")
    if action == "declare":
        return "declare"
    if action == "clear":
        return "clear"
    return None


def _call_mcp_workflow_event_from_block(block: object) -> str | None:
    if not isinstance(block, Mapping):
        return None
    if block.get("type") != "tool_use" or block.get("name") != "CallMcpTool":
        return None
    tool_input = block.get("input")
    if not isinstance(tool_input, Mapping):
        return None
    return _mcp_workflow_event_from_call_mcp_tool(tool_input)


def _iter_call_mcp_workflow_events_from_message_content(
    content: object,
) -> list[str]:
    if not isinstance(content, list):
        return []
    events: list[str] = []
    for block in content:
        event = _call_mcp_workflow_event_from_block(block)
        if event is not None:
            events.append(event)
    return events


def _workflow_events_from_jsonl_line(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, Mapping):
        return []
    message = payload.get("message")
    if not isinstance(message, Mapping):
        return []
    return _iter_call_mcp_workflow_events_from_message_content(message.get("content"))


def _transcript_open_mcp_workflow_cycles(transcript: str) -> int:
    """Count unclosed MCP workflow cycles from JSONL ``CallMcpTool`` events only."""

    open_cycles = 0
    for line in transcript.splitlines():
        for event in _workflow_events_from_jsonl_line(line):
            if event in _MCP_WORKFLOW_OPEN:
                open_cycles += 1
            elif event in _MCP_WORKFLOW_CLOSE:
                open_cycles = max(0, open_cycles - 1)
    return open_cycles


def transcript_mcp_workflow_looks_unclosed(transcript: str) -> bool:
    """Fallback when registry is unavailable: parse JSONL tool_use events only."""

    return _transcript_open_mcp_workflow_cycles(transcript) > 0


def session_cleanup_followup_message(*, intent_ids: tuple[str, ...]) -> str:
    if intent_ids:
        joined = ", ".join(intent_ids)
        return (
            "CodeClone: workspace still has unclosed change-control intent(s): "
            f"{joined}. Before ending, run `finish_controlled_change` with the "
            "active `intent_id`, or "
            '`manage_change_intent(action="clear", intent_id=..., root=<abs>)` '
            "when abandoning work."
        )
    return (
        "CodeClone: this session may have started change control without a matching "
        "`finish_controlled_change`. Before ending, run "
        "`finish_controlled_change` with the active `intent_id`, or "
        '`manage_change_intent(action="list_workspace", root=<abs>)` to inspect '
        "stale intents."
    )


def _transcript_fallback_should_warn(
    transcript: str | None,
) -> tuple[bool, tuple[str, ...]]:
    if transcript is not None and transcript_mcp_workflow_looks_unclosed(transcript):
        return True, ()
    return False, ()


def session_cleanup_should_warn(
    *,
    repo_root: Path | None,
    transcript: str | None,
) -> tuple[bool, tuple[str, ...]]:
    """Return whether stop should warn and any registry intent ids."""

    if repo_root is None:
        return _transcript_fallback_should_warn(transcript)

    try:
        from codeclone.workspace_intent.gate import (
            WorkspaceIntentRegistryUnavailable,
            list_unclosed_workspace_intents_for_hook_cleanup,
        )
    except Exception:
        return _transcript_fallback_should_warn(transcript)

    try:
        unclosed = list_unclosed_workspace_intents_for_hook_cleanup(repo_root)
    except WorkspaceIntentRegistryUnavailable:
        return _transcript_fallback_should_warn(transcript)

    intent_ids = tuple(item.intent_id for item in unclosed)
    return bool(intent_ids), intent_ids
