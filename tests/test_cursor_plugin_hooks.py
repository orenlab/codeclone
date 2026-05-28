# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Tests for Cursor plugin hook scripts.

Covers the full stdin → stdout contract via subprocess invocation.

Security invariants under test:
- Path traversal via ``../`` sequences is rejected.
- Null bytes in paths are rejected.
- Paths outside ``$HOME`` / ``%USERPROFILE%`` are rejected.
- Non-regular files (directories, symlinks to outside HOME) are rejected.
- Malformed / missing JSON produces empty ``{}``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "cursor-codeclone" / "hooks"
_POST_EDIT = _HOOKS_DIR / "post-edit-reminder.py"
_SESSION_CHECK = _HOOKS_DIR / "session-cleanup-check.py"
_EMPTY: dict[str, object] = {}


# ── helpers ──────────────────────────────────────────────────────────


def _run_hook(script: Path, stdin_data: str) -> dict[str, object]:
    """Invoke a hook script as a subprocess and return parsed JSON output."""
    result = subprocess.run(
        [sys.executable, str(script)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"Hook exited with {result.returncode}: {result.stderr}"
    )
    return json.loads(result.stdout.strip())  # type: ignore[no-any-return]


def _run_session_hook_with_home(
    transcript_path: Path, home_dir: Path
) -> dict[str, object]:
    """Run session-cleanup-check with a custom HOME directory."""
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["USERPROFILE"] = str(home_dir)  # Windows equivalent
    result = subprocess.run(
        [sys.executable, str(_SESSION_CHECK)],
        input=json.dumps({"transcript_path": str(transcript_path)}),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, (
        f"Hook exited with {result.returncode}: {result.stderr}"
    )
    return json.loads(result.stdout.strip())  # type: ignore[no-any-return]


def _has_followup(output: dict[str, object]) -> bool:
    return "followup_message" in output


# ═══════════════════════════════════════════════════════════════════
# post-edit-reminder.py — functional
# ═══════════════════════════════════════════════════════════════════


def test_post_edit_python_file_triggers_reminder() -> None:
    out = _run_hook(_POST_EDIT, json.dumps({"path": "src/main.py"}))
    assert _has_followup(out)
    msg = out["followup_message"]
    assert isinstance(msg, str) and "analyze_repository" in msg


def test_post_edit_non_python_file_is_silent() -> None:
    assert _run_hook(_POST_EDIT, json.dumps({"path": "README.md"})) == _EMPTY


def test_post_edit_nested_python_path() -> None:
    assert _has_followup(_run_hook(_POST_EDIT, json.dumps({"path": "a/b/c/deep.py"})))


def test_post_edit_py_extension_case_sensitive() -> None:
    assert not _has_followup(_run_hook(_POST_EDIT, json.dumps({"path": "Main.PY"})))


def test_post_edit_pyi_stub_is_not_py() -> None:
    assert not _has_followup(_run_hook(_POST_EDIT, json.dumps({"path": "types.pyi"})))


# ── post-edit-reminder: input validation ──


def test_post_edit_empty_path_is_silent() -> None:
    assert not _has_followup(_run_hook(_POST_EDIT, json.dumps({"path": ""})))


def test_post_edit_missing_path_key_is_silent() -> None:
    assert not _has_followup(_run_hook(_POST_EDIT, json.dumps({"file": "x.py"})))


def test_post_edit_invalid_json_is_silent() -> None:
    assert not _has_followup(_run_hook(_POST_EDIT, "not json at all"))


def test_post_edit_empty_stdin_is_silent() -> None:
    assert not _has_followup(_run_hook(_POST_EDIT, ""))


# ── post-edit-reminder: security ──


def test_post_edit_traversal_rejected() -> None:
    assert not _has_followup(
        _run_hook(_POST_EDIT, json.dumps({"path": "../../etc/passwd.py"}))
    )


def test_post_edit_traversal_mid_path_rejected() -> None:
    assert not _has_followup(
        _run_hook(_POST_EDIT, json.dumps({"path": "src/../../../etc/shadow.py"}))
    )


def test_post_edit_null_byte_rejected() -> None:
    assert not _has_followup(
        _run_hook(_POST_EDIT, json.dumps({"path": "safe.py\x00/etc/passwd"}))
    )


# ═══════════════════════════════════════════════════════════════════
# session-cleanup-check.py — functional
# ═══════════════════════════════════════════════════════════════════


def test_session_unclosed_intent_warns(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "action declare scope=foo\naction clear intent=foo\naction declare scope=bar\n"
    )
    out = _run_session_hook_with_home(transcript, tmp_path)
    assert _has_followup(out)
    msg = out["followup_message"]
    assert isinstance(msg, str) and "not have been cleared" in msg


@pytest.mark.parametrize(
    "content, scenario",
    [
        ("action declare scope=foo\naction clear intent=foo\n", "balanced"),
        (
            "action declare scope=a\naction clear id=a\naction clear id=b\n",
            "more_clears",
        ),
        ("just some random log content\n", "no_intents"),
        ("", "empty_file"),
    ],
    ids=["balanced", "more_clears", "no_intents", "empty_file"],
)
def test_session_no_warning_when_intents_not_unclosed(
    tmp_path: Path,
    content: str,
    scenario: str,
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(content)
    out = _run_session_hook_with_home(transcript, tmp_path)
    assert not _has_followup(out), f"Unexpected warning for scenario: {scenario}"


# ── session-cleanup-check: input validation ──


def test_session_empty_stdin_is_silent() -> None:
    assert not _has_followup(_run_hook(_SESSION_CHECK, ""))


def test_session_invalid_json_is_silent() -> None:
    assert not _has_followup(_run_hook(_SESSION_CHECK, "{{bad json"))


def test_session_missing_transcript_key_is_silent() -> None:
    assert not _has_followup(_run_hook(_SESSION_CHECK, json.dumps({"other": "value"})))


def test_session_empty_transcript_path_is_silent() -> None:
    assert not _has_followup(
        _run_hook(_SESSION_CHECK, json.dumps({"transcript_path": ""}))
    )


# ── session-cleanup-check: security ──


def test_session_nonexistent_path_is_silent() -> None:
    assert not _has_followup(
        _run_hook(
            _SESSION_CHECK,
            json.dumps({"transcript_path": "/nonexistent/path/transcript.jsonl"}),
        )
    )


def test_session_path_outside_home_rejected(tmp_path: Path) -> None:
    """File exists but is outside $HOME → must be rejected."""
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("action declare\n")
    out = _run_hook(
        _SESSION_CHECK,
        json.dumps({"transcript_path": str(transcript)}),
    )
    # If tmp_path happens to be under HOME, skip this assertion
    home = Path.home().resolve()
    try:
        transcript.resolve().relative_to(home)
    except ValueError:
        assert not _has_followup(out)


def test_session_null_byte_in_path_rejected() -> None:
    assert not _has_followup(
        _run_hook(
            _SESSION_CHECK,
            json.dumps({"transcript_path": "/tmp/safe\x00/etc/passwd"}),
        )
    )


def test_session_directory_path_rejected(tmp_path: Path) -> None:
    """Existing directory (not a regular file) → must be rejected."""
    assert not _has_followup(_run_session_hook_with_home(tmp_path, tmp_path))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_session_symlink_outside_home_rejected(tmp_path: Path) -> None:
    """Symlink inside 'home' pointing outside → must be rejected after resolve."""
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "transcript.jsonl"
    target.write_text("action declare\n")

    link = fake_home / "transcript.jsonl"
    link.symlink_to(target)

    assert not _has_followup(_run_session_hook_with_home(link, fake_home))


# ═══════════════════════════════════════════════════════════════════
# hooks.json contract
# ═══════════════════════════════════════════════════════════════════


def test_hooks_json_valid() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    assert hooks_json["version"] == 1
    assert "afterFileEdit" in hooks_json["hooks"]
    assert "stop" in hooks_json["hooks"]


def test_hooks_reference_python_not_bash() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    for event, entries in hooks_json["hooks"].items():
        for entry in entries:
            cmd = entry["command"]
            assert "python" in cmd, f"{event} hook still uses bash: {cmd}"
            assert ".py" in cmd, f"{event} hook references .sh not .py: {cmd}"


def test_hooks_referenced_scripts_exist() -> None:
    hooks_json = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    for event, entries in hooks_json["hooks"].items():
        for entry in entries:
            for token in entry["command"].split():
                if token.endswith(".py"):
                    script_name = Path(token).name
                    assert (_HOOKS_DIR / script_name).is_file(), (
                        f"{event}: referenced script {script_name} does not exist"
                    )


def test_hooks_no_bash_scripts_remain() -> None:
    sh_files = list(_HOOKS_DIR.glob("*.sh"))
    assert sh_files == [], f"Stale bash scripts found: {sh_files}"
