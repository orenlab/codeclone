from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _ROOT / "plugins" / "codeclone" / "scripts" / "launch_mcp.py"

#: The user's explicit launcher setting, as the plugin documents it.
_CONFIGURED_COMMAND_ENV = "CODECLONE_MCP_COMMAND"
#: The probes start POSIX shell scripts, so the launcher looks for this name.
_LAUNCHER_NAME = "codeclone-mcp"


def _load_launcher_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "codeclone_codex_plugin_launcher",
        _LAUNCHER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


launcher_mod = _load_launcher_module()

#: The planted and the trusted launchers are shell scripts; the launcher hands
#: them to ``execve``, which needs a POSIX shebang.
_posix_exec = pytest.mark.skipif(
    os.name == "nt", reason="the probe launchers are POSIX shell scripts"
)


def _write_marker_launcher(path: Path, marker: Path) -> Path:
    """An executable that records it was started, with its argv and workspace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f'printf "%s|%s\\n" "$*" "$CODECLONE_WORKSPACE_ROOT" >> "{marker}"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


class _Workspace:
    """A hostile repository that plants a launcher everywhere one used to be found."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "hostile-repo"
        self.hostile_marker = tmp_path / "HOSTILE_LAUNCHER_STARTED"
        self.trusted_marker = tmp_path / "TRUSTED_LAUNCHER_STARTED"
        self.tools = tmp_path / "tools-bin"
        self.trusted = tmp_path / "trusted-install" / "bin"
        for planted in (
            self.root / ".venv" / "bin" / _LAUNCHER_NAME,
            self.root / "venv" / "bin" / _LAUNCHER_NAME,
            self.root / _LAUNCHER_NAME,
        ):
            _write_marker_launcher(planted, self.hostile_marker)
        (self.root / "pyproject.toml").write_text(
            "[tool.poetry]\nname = 'hostile'\n", encoding="utf-8"
        )
        # A Poetry on PATH that reports the repository's own .venv as its env.
        self.tools.mkdir(parents=True)
        poetry = self.tools / "poetry"
        poetry.write_text(
            f"#!/bin/sh\nprintf '%s\\n' '{self.root / '.venv'}'\n", encoding="utf-8"
        )
        poetry.chmod(0o755)
        self.trusted_launcher = _write_marker_launcher(
            self.trusted / _LAUNCHER_NAME, self.trusted_marker
        )

    def run(
        self, *, path_entries: list[str], extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.pathsep.join(path_entries),
            "PWD": str(self.root),
            "HOME": str(self.root.parent / "home"),
            **(extra_env or {}),
        }
        return subprocess.run(
            [sys.executable, "-I", str(_LAUNCHER)],
            cwd=self.root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )


def test_workspace_roots_keep_workspace_root_first() -> None:
    repo_root = Path("/repo")
    roots = launcher_mod.workspace_roots(
        env={
            "CODECLONE_WORKSPACE_ROOT": "/workspace/current",
            "PWD": "/workspace/current",
        },
        cwd="/workspace/plugin",
        repo_root=repo_root,
    )
    assert roots == (
        Path("/workspace/current"),
        Path("/workspace/plugin"),
        repo_root,
    )


@_posix_exec
def test_launcher_never_starts_a_program_planted_in_the_workspace(
    tmp_path: Path,
) -> None:
    # Opening a repository is not consent to run its programs: no .venv, venv,
    # Poetry environment or cwd-relative PATH entry of the workspace is used.
    workspace = _Workspace(tmp_path)

    result = workspace.run(
        path_entries=[str(workspace.tools), ".", ""],
        extra_env={"CODECLONE_WORKSPACE_ROOT": str(workspace.root)},
    )

    assert not workspace.hostile_marker.exists(), result.stderr
    assert result.returncode == 2, result.stderr
    assert "CodeClone launcher not found" in result.stderr
    assert _CONFIGURED_COMMAND_ENV in result.stderr


@_posix_exec
def test_launcher_starts_the_trusted_install_outside_the_workspace(
    tmp_path: Path,
) -> None:
    workspace = _Workspace(tmp_path)

    result = workspace.run(path_entries=[str(workspace.tools), str(workspace.trusted)])

    assert not workspace.hostile_marker.exists(), result.stderr
    assert result.returncode == 0, result.stderr
    assert workspace.trusted_marker.read_text(encoding="utf-8").splitlines() == [
        f"--transport stdio|{workspace.root}"
    ]
    assert "source=path" in result.stderr


@_posix_exec
def test_launcher_skips_relative_path_entries_before_a_trusted_one(
    tmp_path: Path,
) -> None:
    workspace = _Workspace(tmp_path)
    for planted in (workspace.root / ".venv", workspace.root / "venv"):
        (planted / "bin" / _LAUNCHER_NAME).unlink()

    result = workspace.run(path_entries=[".", "", str(workspace.trusted)])

    assert not workspace.hostile_marker.exists(), result.stderr
    assert result.returncode == 0, result.stderr
    assert workspace.trusted_marker.is_file()


@_posix_exec
def test_launcher_starts_the_configured_absolute_launcher(tmp_path: Path) -> None:
    workspace = _Workspace(tmp_path)

    result = workspace.run(
        path_entries=[str(workspace.tools)],
        extra_env={_CONFIGURED_COMMAND_ENV: str(workspace.trusted_launcher)},
    )

    assert not workspace.hostile_marker.exists(), result.stderr
    assert result.returncode == 0, result.stderr
    assert workspace.trusted_marker.is_file()
    assert "source=configured" in result.stderr


@_posix_exec
@pytest.mark.parametrize(
    "configured",
    [
        pytest.param(".venv/bin/codeclone-mcp", id="relative-to-workspace"),
        pytest.param("codeclone-mcp", id="bare-name"),
    ],
)
def test_launcher_refuses_a_configured_launcher_that_is_not_absolute(
    tmp_path: Path, configured: str
) -> None:
    workspace = _Workspace(tmp_path)

    result = workspace.run(
        path_entries=[str(workspace.tools), ".", str(workspace.trusted)],
        extra_env={_CONFIGURED_COMMAND_ENV: configured},
    )

    assert not workspace.hostile_marker.exists(), result.stderr
    assert not workspace.trusted_marker.exists(), result.stderr
    assert result.returncode == 2, result.stderr
    assert "absolute path" in result.stderr


def test_launcher_refuses_a_configured_launcher_that_does_not_exist(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nowhere" / _LAUNCHER_NAME

    with pytest.raises(launcher_mod.LauncherConfigError, match="not a file"):
        launcher_mod.resolve_launch_target(
            env={_CONFIGURED_COMMAND_ENV: str(missing), "PATH": ""},
            cwd=str(tmp_path),
            repo_root=tmp_path,
        )


@pytest.mark.skipif(os.name == "nt", reason="Windows has no execute permission bit")
def test_trusted_path_launcher_ignores_non_executable_files(tmp_path: Path) -> None:
    directory = tmp_path / "bin"
    directory.mkdir()
    candidate = directory / _LAUNCHER_NAME
    candidate.write_text("", encoding="utf-8")

    assert launcher_mod.trusted_path_launcher({"PATH": str(directory)}) is None
    candidate.chmod(0o755)
    assert launcher_mod.trusted_path_launcher({"PATH": str(directory)}) == candidate


def test_launcher_executable_name_follows_the_platform() -> None:
    assert launcher_mod.launcher_executable_name("posix") == "codeclone-mcp"
    assert launcher_mod.launcher_executable_name("nt") == "codeclone-mcp.exe"


def test_build_setup_message_is_actionable() -> None:
    message = launcher_mod.build_setup_message()

    assert 'uv tool install "codeclone[mcp]"' in message
    assert _CONFIGURED_COMMAND_ENV in message
    assert "never started automatically" in message
