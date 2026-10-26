from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
TRANSPORT_ARGS = ("--transport", "stdio")
CONFIGURED_COMMAND_ENV = "CODECLONE_MCP_COMMAND"


@dataclass(frozen=True)
class LaunchTarget:
    command: str
    source: str
    workspace_root: Path | None


class LauncherConfigError(ValueError):
    """The user's configured launcher cannot be used as given."""


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


def launcher_executable_name(os_name: str = os.name) -> str:
    return "codeclone-mcp.exe" if os_name == "nt" else "codeclone-mcp"


def trusted_path_launcher(env: Mapping[str, str]) -> Path | None:
    """The first ``codeclone-mcp`` in an absolute ``PATH`` directory.

    Opening a repository is not consent to run programs from it, so the
    workspace is never searched: an empty or relative ``PATH`` entry (which
    the operating system would resolve against the workspace as the current
    directory) is skipped, and so is the current directory that Windows lookups
    would try first.
    """

    name = launcher_executable_name()
    for entry in str(env.get("PATH", "")).split(os.pathsep):
        directory = entry.strip()
        if not directory or not os.path.isabs(directory):
            continue
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def configured_launcher(env: Mapping[str, str]) -> Path | None:
    """The launcher the user named in ``CODECLONE_MCP_COMMAND``, if any."""

    raw = _normalized_env_value(env.get(CONFIGURED_COMMAND_ENV))
    if raw is None:
        return None
    configured = Path(raw).expanduser()
    if not configured.is_absolute():
        raise LauncherConfigError(
            f"{CONFIGURED_COMMAND_ENV}={raw!r} must be an absolute path to a "
            "trusted codeclone-mcp."
        )
    if not configured.is_file():
        raise LauncherConfigError(f"{CONFIGURED_COMMAND_ENV}={raw!r} is not a file.")
    return configured


def resolve_launch_target(
    *,
    env: Mapping[str, str],
    cwd: str | None = None,
    repo_root: Path = REPO_ROOT,
) -> LaunchTarget | None:
    """The user's configured launcher, else a trusted install on ``PATH``.

    Nothing inside the workspace is ever chosen on its own: no ``.venv`` or
    ``venv``, no Poetry environment, no relative ``PATH`` entry.
    """

    roots = workspace_roots(env=env, cwd=cwd, repo_root=repo_root)
    workspace_root = roots[0] if roots else None
    configured = configured_launcher(env)
    if configured is not None:
        return LaunchTarget(
            command=str(configured),
            source="configured",
            workspace_root=workspace_root,
        )
    installed = trusted_path_launcher(env)
    if installed is None:
        return None
    return LaunchTarget(
        command=str(installed),
        source="path",
        workspace_root=workspace_root,
    )


def build_setup_message() -> str:
    return (
        "CodeClone launcher not found. Install it outside the workspace, for "
        'example with `uv tool install "codeclone[mcp]"`, so codeclone-mcp is on '
        f"PATH, or set {CONFIGURED_COMMAND_ENV} to the absolute path of a trusted "
        "codeclone-mcp. A launcher inside the opened repository (.venv, venv, a "
        "Poetry environment) is never started automatically."
    )


def exec_launch_target(target: LaunchTarget, env: Mapping[str, str]) -> None:
    child_env = dict(env)
    if target.workspace_root is not None and not _normalized_env_value(
        child_env.get("CODECLONE_WORKSPACE_ROOT")
    ):
        child_env["CODECLONE_WORKSPACE_ROOT"] = str(target.workspace_root)
    argv = [target.command, *TRANSPORT_ARGS]
    os.execvpe(target.command, argv, child_env)


def main() -> int:
    try:
        target = resolve_launch_target(env=os.environ)
    except LauncherConfigError as exc:
        sys.stderr.write(f"[codeclone] {exc}\n")
        return 2
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
