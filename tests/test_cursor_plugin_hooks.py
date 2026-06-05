# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Tests for Cursor plugin hook scripts.

Covers the stdin → stdout contract via subprocess invocation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codeclone.config.intent_registry import DEFAULT_INTENT_REGISTRY_DB_PATH
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_store import (
    clear_workspace_intent_store_cache,
)
from tests.test_workspace_intents import _record
from tests.workspace_intent_gate_helpers import (
    bind_hook_own_agent_env,
    codex_foreign_record,
    cursor_vscode_record,
    write_workspace_record,
)

_PID_ALIVE = "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "cursor-codeclone" / "hooks"
_RUN_HOOK = _HOOKS_DIR / "run_hook.py"
_PRE_TOOL_USE = _HOOKS_DIR / "pre_tool_use_change_control.py"
_POST_TOOL_USE = _HOOKS_DIR / "post-tool-use-python-edit.py"
_SESSION_CHECK = _HOOKS_DIR / "session-cleanup-check.py"
_EMPTY: dict[str, object] = {}


def _run_hook(
    script: Path,
    stdin_data: str,
    *,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    cmd = [sys.executable, str(script)]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, (
        f"Hook exited with {result.returncode}: {result.stderr}"
    )
    return json.loads(result.stdout.strip())  # type: ignore[no-any-return]


def _run_session_hook(
    *,
    transcript_path: Path | None = None,
    home_dir: Path | None = None,
    workspace_roots: list[str] | None = None,
) -> dict[str, object]:
    stdin_payload: dict[str, object] = {}
    if transcript_path is not None:
        stdin_payload["transcript_path"] = str(transcript_path)
    if workspace_roots is not None:
        stdin_payload["workspace_roots"] = workspace_roots
    env = os.environ.copy()
    if home_dir is not None:
        env["HOME"] = str(home_dir)
        env["USERPROFILE"] = str(home_dir)
    result = subprocess.run(
        [sys.executable, str(_SESSION_CHECK)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, (
        f"Hook exited with {result.returncode}: {result.stderr}"
    )
    return json.loads(result.stdout.strip())  # type: ignore[no-any-return]


def _run_session_hook_with_home(
    transcript_path: Path, home_dir: Path, *, workspace_roots: list[str] | None = None
) -> dict[str, object]:
    return _run_session_hook(
        transcript_path=transcript_path,
        home_dir=home_dir,
        workspace_roots=workspace_roots,
    )


def _call_mcp_tool_jsonl_line(
    *,
    tool_name: str,
    arguments: dict[str, object] | None = None,
) -> str:
    payload = {
        "role": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "CallMcpTool",
                    "input": {
                        "server": "project-0-codeclone-codeclone",
                        "toolName": tool_name,
                        "arguments": arguments or {},
                    },
                }
            ],
        },
    }
    return json.dumps(payload, sort_keys=True)


# pre_tool_use_change_control.py


def _write_intent(tmp_path: Path, *, status: str = "active") -> None:
    assert workspace_intents.write_workspace_intent(
        root=tmp_path,
        record=_record(status=status),
    )


def _hooks_config(tmp_path: Path, *, enforce_scope: str) -> None:
    cfg = tmp_path / ".cursor" / "codeclone-hooks.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        json.dumps({"enforce_scope": enforce_scope}),
        encoding="utf-8",
    )


def test_pre_tool_use_denies_python_write_without_intent(tmp_path: Path) -> None:
    root = str(tmp_path.resolve())
    out = _run_hook(
        _PRE_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/module.py"},
                "workspace_roots": [root],
            }
        ),
    )
    assert out.get("permission") == "deny"


def test_pre_tool_use_python_scope_allows_markdown_without_intent(
    tmp_path: Path,
) -> None:
    root = str(tmp_path.resolve())
    assert (
        _run_hook(
            _PRE_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "Write",
                    "tool_input": {"path": f"{root}/README.md"},
                    "workspace_roots": [root],
                }
            ),
        )
        == _EMPTY
    )


def test_pre_tool_use_repo_scope_denies_markdown_without_intent(
    tmp_path: Path,
) -> None:
    _hooks_config(tmp_path, enforce_scope="repo")
    root = str(tmp_path.resolve())
    out = _run_hook(
        _PRE_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/README.md"},
                "workspace_roots": [root],
            }
        ),
    )
    assert out.get("permission") == "deny"
    assert "repository" in str(out.get("user_message", "")).lower()


def test_pre_tool_use_repo_scope_denies_git_internal_write_without_intent(
    tmp_path: Path,
) -> None:
    _hooks_config(tmp_path, enforce_scope="repo")
    root = str(tmp_path.resolve())
    out = _run_hook(
        _PRE_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/.git/codeclone-active-intent.json"},
                "workspace_roots": [root],
            }
        ),
    )
    assert out.get("permission") == "deny"
    assert ".git/**" in str(out.get("agent_message", ""))


def test_pre_tool_use_repo_scope_env_overrides_config(tmp_path: Path) -> None:
    _hooks_config(tmp_path, enforce_scope="python")
    root = str(tmp_path.resolve())
    env = os.environ.copy()
    env["CODECLONE_HOOKS_ENFORCE_SCOPE"] = "repo"
    out = _run_hook(
        _PRE_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/notes.txt"},
                "workspace_roots": [root],
            }
        ),
        env=env,
    )
    assert out.get("permission") == "deny"


def test_pre_tool_use_repo_scope_ignores_path_outside_workspace(
    tmp_path: Path,
) -> None:
    _hooks_config(tmp_path, enforce_scope="repo")
    root = str(tmp_path.resolve())
    assert (
        _run_hook(
            _PRE_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "Write",
                    "tool_input": {"path": "/etc/passwd"},
                    "workspace_roots": [root],
                }
            ),
        )
        == _EMPTY
    )


def test_pre_tool_use_allows_python_write_with_active_intent(tmp_path: Path) -> None:
    _write_intent(tmp_path)
    root = str(tmp_path.resolve())
    assert (
        _run_hook(
            _PRE_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "StrReplace",
                    "tool_input": {"file_path": f"{root}/pkg/mod.py"},
                    "workspace_roots": [root],
                }
            ),
        )
        == _EMPTY
    )


def test_pre_tool_use_allows_python_write_with_sqlite_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    clear_workspace_intent_store_cache()
    _write_intent(tmp_path)
    root = str(tmp_path.resolve())
    assert (
        _run_hook(
            _PRE_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "Write",
                    "tool_input": {"path": f"{root}/pkg/mod.py"},
                    "workspace_roots": [root],
                }
            ),
        )
        == _EMPTY
    )


def test_pre_tool_use_denies_python_write_with_queued_intent(tmp_path: Path) -> None:
    _write_intent(tmp_path, status="queued")
    root = str(tmp_path.resolve())
    out = _run_hook(
        _PRE_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/pkg/mod.py"},
                "workspace_roots": [root],
            }
        ),
    )
    assert out.get("permission") == "deny"


def test_pre_tool_use_allows_read_only_git_shell_without_intent(
    tmp_path: Path,
) -> None:
    root = str(tmp_path.resolve())
    assert (
        _run_hook(
            _PRE_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "Shell",
                    "tool_input": {"command": "git status && git diff -- README.md"},
                    "workspace_roots": [root],
                }
            ),
        )
        == _EMPTY
    )


def test_pre_tool_use_denies_git_apply_without_intent(tmp_path: Path) -> None:
    root = str(tmp_path.resolve())
    out = _run_hook(
        _PRE_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Shell",
                "tool_input": {"command": "git apply /tmp/patch.diff"},
                "workspace_roots": [root],
            }
        ),
    )
    assert out.get("permission") == "deny"


def test_pre_tool_use_ignore_bypass_env(tmp_path: Path) -> None:
    """CODECLONE_HOOKS_ENFORCE_CHANGE_CONTROL must not disable the gate."""
    root = str(tmp_path.resolve())
    env = os.environ.copy()
    env["CODECLONE_HOOKS_ENFORCE_CHANGE_CONTROL"] = "0"
    out = _run_hook(
        _PRE_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/module.py"},
                "workspace_roots": [root],
            }
        ),
        env=env,
    )
    assert out.get("permission") == "deny"


def test_run_hook_dispatches_pre_tool_use_gate(tmp_path: Path) -> None:
    root = str(tmp_path.resolve())
    out = _run_hook(
        _RUN_HOOK,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/x.py"},
                "workspace_roots": [root],
            }
        ),
        extra_args=["pre-tool-use-gate"],
    )
    assert out.get("permission") == "deny"


# ═══════════════════════════════════════════════════════════════════
# post-tool-use-python-edit.py
# ═══════════════════════════════════════════════════════════════════


def test_post_tool_use_write_python_injects_additional_context() -> None:
    root = str(_REPO_ROOT.resolve())
    out = _run_hook(
        _POST_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/codeclone/main.py"},
                "workspace_roots": [root],
            }
        ),
    )
    assert "additional_context" in out
    ctx = out["additional_context"]
    assert isinstance(ctx, str)
    assert "analyze_repository" in ctx
    assert "get_relevant_memory" in ctx
    assert root in ctx


def test_post_tool_use_strreplace_python_file_path_key() -> None:
    out = _run_hook(
        _POST_TOOL_USE,
        json.dumps(
            {
                "tool_name": "StrReplace",
                "tool_input": {"file_path": "src/pkg/module.py"},
            }
        ),
    )
    assert "additional_context" in out


def test_post_tool_use_non_write_tool_is_silent() -> None:
    assert (
        _run_hook(
            _POST_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "Read",
                    "tool_input": {"path": "src/main.py"},
                }
            ),
        )
        == _EMPTY
    )


def test_post_tool_use_markdown_write_is_silent() -> None:
    assert (
        _run_hook(
            _POST_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "Write",
                    "tool_input": {"path": "README.md"},
                }
            ),
        )
        == _EMPTY
    )


def test_post_tool_use_pyi_stub_triggers_reminder() -> None:
    assert "additional_context" in _run_hook(
        _POST_TOOL_USE,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": "types.pyi"},
            }
        ),
    )


def test_post_tool_use_traversal_rejected() -> None:
    assert (
        _run_hook(
            _POST_TOOL_USE,
            json.dumps(
                {
                    "tool_name": "Write",
                    "tool_input": {"path": "../../etc/passwd.py"},
                }
            ),
        )
        == _EMPTY
    )


def test_post_tool_use_invalid_json_is_silent() -> None:
    assert _run_hook(_POST_TOOL_USE, "not json") == _EMPTY


def test_run_hook_dispatches_post_tool_use() -> None:
    root = str(_REPO_ROOT.resolve())
    out = _run_hook(
        _RUN_HOOK,
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"path": f"{root}/codeclone/main.py"},
                "workspace_roots": [root],
            }
        ),
        extra_args=["post-tool-use"],
    )
    assert "additional_context" in out


def _assert_hook_commands_avoid_python3(payload: dict[str, object]) -> None:
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    for entries in hooks.values():
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            cmd = str(entry["command"])
            first = cmd.split()[0].strip('"')
            assert first not in {"python3", "python3.exe"}, cmd
            assert "run_hook.py" in cmd


def test_plugin_hooks_json_use_python_launcher_not_python3() -> None:
    """Plugin manifest hooks.json — not repo .cursor/hooks.json (local, gitignored)."""
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    _assert_hook_commands_avoid_python3(hooks_json)


def test_install_project_hooks_writes_launcher_commands(tmp_path: Path) -> None:
    """Project hooks are generated by install-project-hooks.py, not committed."""
    install_script = (
        _REPO_ROOT
        / "plugins"
        / "cursor-codeclone"
        / "scripts"
        / ("install-project-hooks.py")
    )
    result = subprocess.run(
        [sys.executable, str(install_script), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    project_hooks = json.loads(
        (tmp_path / ".cursor" / "hooks.json").read_text(encoding="utf-8")
    )
    _assert_hook_commands_avoid_python3(project_hooks)
    pre_cmd = project_hooks["hooks"]["preToolUse"][0]["command"]
    assert "pre-tool-use-gate" in pre_cmd
    assert "run_hook.py" in pre_cmd


def test_hooks_no_bash_scripts_remain() -> None:
    sh_files = list(_HOOKS_DIR.glob("*.sh"))
    assert sh_files == [], f"Stale bash scripts found: {sh_files}"


# ═══════════════════════════════════════════════════════════════════
# session-cleanup-check.py
# ═══════════════════════════════════════════════════════════════════


def test_session_registry_own_active_intent_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = str(tmp_path.resolve())
    record = cursor_vscode_record()
    write_workspace_record(tmp_path, record)
    bind_hook_own_agent_env(monkeypatch, record)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    out = _run_session_hook_with_home(
        transcript,
        tmp_path,
        workspace_roots=[root],
    )
    assert "followup_message" in out
    msg = out["followup_message"]
    assert isinstance(msg, str)
    assert record.intent_id in msg
    assert "finish_controlled_change" in msg


def test_session_registry_foreign_active_intent_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = str(tmp_path.resolve())
    monkeypatch.setattr(_PID_ALIVE, lambda pid: True)
    write_workspace_record(tmp_path, codex_foreign_record())
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "start_controlled_change " * 20 + "\n",
        encoding="utf-8",
    )
    out = _run_session_hook_with_home(
        transcript,
        tmp_path,
        workspace_roots=[root],
    )
    assert "followup_message" not in out


def test_session_registry_empty_ignores_noisy_transcript(tmp_path: Path) -> None:
    root = str(tmp_path.resolve())
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "start_controlled_change " * 50 + "\nfinish_controlled_change\n",
        encoding="utf-8",
    )
    out = _run_session_hook_with_home(
        transcript,
        tmp_path,
        workspace_roots=[root],
    )
    assert "followup_message" not in out


def test_session_registry_queued_intent_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = str(tmp_path.resolve())
    record = cursor_vscode_record(status="queued")
    write_workspace_record(tmp_path, record)
    bind_hook_own_agent_env(monkeypatch, record)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    out = _run_session_hook_with_home(
        transcript,
        tmp_path,
        workspace_roots=[root],
    )
    assert "followup_message" in out


def test_session_transcript_fallback_warns_on_unclosed_mcp_tool(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        _call_mcp_tool_jsonl_line(tool_name="start_controlled_change") + "\n",
        encoding="utf-8",
    )
    out = _run_session_hook_with_home(transcript, tmp_path)
    assert "followup_message" in out


def test_session_transcript_fallback_silent_when_balanced(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        _call_mcp_tool_jsonl_line(tool_name="start_controlled_change")
        + "\n"
        + _call_mcp_tool_jsonl_line(tool_name="finish_controlled_change")
        + "\n",
        encoding="utf-8",
    )
    out = _run_session_hook_with_home(transcript, tmp_path)
    assert "followup_message" not in out


def test_session_plaintext_substrings_do_not_trigger_warning(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "tool start_controlled_change intent_id=intent-abc\n"
        "tool finish_controlled_change intent_cleared=false\n"
        "tool start_controlled_change intent_id=intent-def\n",
        encoding="utf-8",
    )
    out = _run_session_hook_with_home(transcript, tmp_path)
    assert "followup_message" not in out


@pytest.mark.parametrize(
    "content",
    [
        "action declare scope=foo\naction clear intent=foo\n",
        "just some random log content\n",
        "",
    ],
)
def test_session_no_warning_when_intents_not_unclosed(
    tmp_path: Path, content: str
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(content, encoding="utf-8")
    out = _run_session_hook_with_home(transcript, tmp_path)
    assert "followup_message" not in out


def test_session_transcript_fallback_manage_change_intent_declare_warns(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        _call_mcp_tool_jsonl_line(
            tool_name="manage_change_intent",
            arguments={"action": "declare"},
        )
        + "\n",
        encoding="utf-8",
    )
    out = _run_session_hook_with_home(transcript, tmp_path)
    assert "followup_message" in out


def test_session_empty_stdin_is_silent() -> None:
    assert "followup_message" not in _run_hook(_SESSION_CHECK, "")


def test_session_path_outside_home_rejected(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("start_controlled_change\n", encoding="utf-8")
    out = _run_hook(
        _SESSION_CHECK,
        json.dumps({"transcript_path": str(transcript)}),
    )
    home = Path.home().resolve()
    try:
        transcript.resolve().relative_to(home)
    except ValueError:
        assert "followup_message" not in out


# ═══════════════════════════════════════════════════════════════════
# hooks.json contract
# ═══════════════════════════════════════════════════════════════════


def test_hooks_json_valid() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    assert hooks_json["version"] == 1
    assert "preToolUse" in hooks_json["hooks"]
    assert "postToolUse" in hooks_json["hooks"]
    assert "stop" in hooks_json["hooks"]
    assert "afterFileEdit" not in hooks_json["hooks"]


def test_hooks_reference_python_scripts() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    for event, entries in hooks_json["hooks"].items():
        for entry in entries:
            cmd = entry["command"]
            assert "python" in cmd, f"{event} hook must use python: {cmd}"
            assert ".py" in cmd, f"{event} hook must reference .py script: {cmd}"


def test_hooks_post_tool_use_has_write_matcher() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    entry = hooks_json["hooks"]["postToolUse"][0]
    assert "Write" in entry["matcher"]


def test_hooks_referenced_scripts_exist() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    for event, entries in hooks_json["hooks"].items():
        for entry in entries:
            assert (_HOOKS_DIR / "run_hook.py").is_file(), (
                f"{event}: missing run_hook.py"
            )
            for token in entry["command"].replace('"', " ").split():
                if token.endswith(".py") and "run_hook" not in token:
                    script_name = Path(token).name
                    assert (_HOOKS_DIR / script_name).is_file(), (
                        f"{event}: missing script {script_name}"
                    )


def test_post_tool_use_hook_rejects_oversized_stdin() -> None:
    oversized = json.dumps(
        {
            "tool_name": "Write",
            "tool_input": {"path": "src/module.py"},
        }
    ) + (" " * 70000)
    assert _run_hook(_POST_TOOL_USE, oversized) == _EMPTY


def test_hooks_pre_tool_use_fail_closed() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    entry = hooks_json["hooks"]["preToolUse"][0]
    assert entry.get("failClosed") is True
    assert "Write" in entry["matcher"]
