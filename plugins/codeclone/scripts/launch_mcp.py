# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

POETRY_TIMEOUT_SECONDS = 5
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
TRANSPORT_ARGS = ("--transport", "stdio")
MAX_STDIN_BYTES = 65536
_SPAWN_ENV_EXACT_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TERM",
        "PWD",
        "OS",
        "COMSPEC",
        "PATHEXT",
    }
)
_SPAWN_ENV_PREFIXES = ("CODECLONE_", "PYTHON", "UV_", "VIRTUAL_ENV", "POETRY_")


@dataclass(frozen=True)
class LaunchTarget:
    command: str
    source: str
    workspace_root: Path | None


def _normalized_env_value(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def workspace_roots(
    *,
    env: Mapping[str, str],
    cwd: str | None = None,
    repo_root: Path = REPO_ROOT,
) -> tuple[Path, ...]:
    candidates = (
        _normalized_env_value(env.get("CODECLONE_WORKSPACE_ROOT")),
        _normalized_env_value(cwd if cwd is not None else os.getcwd()),
        _normalized_env_value(env.get("PWD")),
        str(repo_root),
    )
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is not None:
            resolved = Path(candidate).resolve()
            key = os.path.normcase(str(resolved))
            if key not in seen:
                seen.add(key)
                roots.append(resolved)
    return tuple(roots)


def workspace_local_launcher_candidates(root: Path) -> tuple[Path, ...]:
    if os.name == "nt":
        return (
            root / ".venv" / "Scripts" / "codeclone-mcp.exe",
            root / ".venv" / "Scripts" / "codeclone-mcp.cmd",
            root / "venv" / "Scripts" / "codeclone-mcp.exe",
            root / "venv" / "Scripts" / "codeclone-mcp.cmd",
        )
    return (
        root / ".venv" / "bin" / "codeclone-mcp",
        root / "venv" / "bin" / "codeclone-mcp",
    )


def launcher_within_workspace(candidate: Path, root: Path) -> bool:
    if not candidate.is_file():
        return False
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def minimal_child_env(
    env: Mapping[str, str],
    workspace_root: Path | None,
) -> dict[str, str]:
    child_env = {
        key: value
        for key, value in env.items()
        if key in _SPAWN_ENV_EXACT_KEYS or key.startswith(_SPAWN_ENV_PREFIXES)
    }
    if workspace_root is not None and not _normalized_env_value(
        child_env.get("CODECLONE_WORKSPACE_ROOT")
    ):
        child_env["CODECLONE_WORKSPACE_ROOT"] = str(workspace_root)
    return child_env


def resolve_workspace_local_launcher(
    roots: tuple[Path, ...],
) -> LaunchTarget | None:
    for root in roots:
        for candidate in workspace_local_launcher_candidates(root):
            if launcher_within_workspace(candidate, root):
                return LaunchTarget(
                    command=str(candidate.resolve()),
                    source="workspaceLocal",
                    workspace_root=root,
                )
    return None


def resolve_poetry_launcher(
    *,
    roots: tuple[Path, ...],
    env: Mapping[str, str],
    run_cmd: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> LaunchTarget | None:
    if which("poetry") is None:
        return None
    executable = "codeclone-mcp.exe" if os.name == "nt" else "codeclone-mcp"
    script_dir = "Scripts" if os.name == "nt" else "bin"
    for root in roots:
        candidate = resolve_poetry_env_root(root=root, env=env, run_cmd=run_cmd)
        if candidate is None:
            continue
        candidate = candidate / script_dir / executable
        if candidate.is_file():
            return LaunchTarget(
                command=str(candidate.resolve()),
                source="poetryEnv",
                workspace_root=root,
            )
    return None


def resolve_poetry_env_root(
    *,
    root: Path,
    env: Mapping[str, str],
    run_cmd: Callable[..., subprocess.CompletedProcess[str]],
) -> Path | None:
    if not (root / "pyproject.toml").is_file():
        return None
    probe_env = minimal_child_env(env, root)
    try:
        completed = run_cmd(
            ["poetry", "env", "info", "-p"],
            cwd=str(root),
            env=probe_env,
            capture_output=True,
            text=True,
            check=False,
            timeout=POETRY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    poetry_env_root = completed.stdout.strip()
    if completed.returncode != 0 or not poetry_env_root:
        return None
    return Path(poetry_env_root)


def resolve_path_launcher(
    *,
    roots: tuple[Path, ...],
    which: Callable[[str], str | None] = shutil.which,
) -> LaunchTarget | None:
    resolved = which("codeclone-mcp")
    if not resolved:
        return None
    return LaunchTarget(
        command=resolved,
        source="path",
        workspace_root=roots[0] if roots else None,
    )


def resolve_launch_target(
    *,
    env: Mapping[str, str],
    cwd: str | None = None,
    repo_root: Path = REPO_ROOT,
    run_cmd: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> LaunchTarget | None:
    roots = workspace_roots(env=env, cwd=cwd, repo_root=repo_root)
    return (
        resolve_workspace_local_launcher(roots)
        or resolve_poetry_launcher(roots=roots, env=env, run_cmd=run_cmd, which=which)
        or resolve_path_launcher(roots=roots, which=which)
    )


def build_setup_message() -> str:
    return (
        "CodeClone launcher not found. Expected a workspace .venv launcher, "
        "a Poetry environment launcher, or a PATH entry for codeclone-mcp."
    )


def exec_launch_target(target: LaunchTarget, env: Mapping[str, str]) -> None:
    command = target.command
    if os.path.isabs(command):
        command = str(Path(command).resolve())
    child_env = minimal_child_env(env, target.workspace_root)
    argv = [command, *TRANSPORT_ARGS]
    os.execvpe(command, argv, child_env)


def main() -> int:
    target = resolve_launch_target(env=os.environ)
    if target is None:
        sys.stderr.write(f"[codeclone] {build_setup_message()}\n")
        return 2
    workspace_root = (
        str(target.workspace_root) if target.workspace_root is not None else "<inherit>"
    )
    sys.stderr.write(
        "[codeclone] launcher "
        f"source={target.source} command={target.command} "
        f"workspace_root={workspace_root}\n"
    )
    try:
        exec_launch_target(target, os.environ)
    except OSError as exc:
        sys.stderr.write(f"[codeclone] {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
