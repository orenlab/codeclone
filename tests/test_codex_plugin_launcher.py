from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_launcher_module() -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    path = root / "plugins" / "codeclone" / "scripts" / "launch_mcp.py"
    spec = importlib.util.spec_from_file_location(
        "codeclone_codex_plugin_launcher",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


launcher_mod = _load_launcher_module()


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


def test_resolve_launch_target_prefers_workspace_local_launcher(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    launcher_path = launcher_mod.workspace_local_launcher_candidates(workspace_root)[0]
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text("", encoding="utf-8")

    target = launcher_mod.resolve_launch_target(
        env={"PWD": str(workspace_root)},
        cwd=str(workspace_root),
        repo_root=workspace_root,
        which=lambda _name: "/usr/local/bin/codeclone-mcp",
    )

    assert target == launcher_mod.LaunchTarget(
        command=str(launcher_path),
        source="workspaceLocal",
        workspace_root=workspace_root,
    )


def test_resolve_launch_target_prefers_poetry_before_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    poetry_root = tmp_path / "poetry-env"
    poetry_launcher = poetry_root / "bin" / "codeclone-mcp"
    poetry_launcher.parent.mkdir(parents=True, exist_ok=True)
    poetry_launcher.write_text("", encoding="utf-8")
    (workspace_root / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    (workspace_root / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )

    def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["cwd"] == str(workspace_root)
        return subprocess.CompletedProcess(
            args=["poetry", "env", "info", "-p"],
            returncode=0,
            stdout=str(poetry_root),
            stderr="",
        )

    target = launcher_mod.resolve_launch_target(
        env={"PWD": str(workspace_root)},
        cwd=str(workspace_root),
        repo_root=workspace_root,
        run_cmd=fake_run,
        which=lambda name: (
            "/usr/local/bin/poetry"
            if name == "poetry"
            else "/usr/local/bin/codeclone-mcp"
        ),
    )

    assert target == launcher_mod.LaunchTarget(
        command=str(poetry_launcher),
        source="poetryEnv",
        workspace_root=workspace_root,
    )


def test_build_setup_message_is_actionable() -> None:
    assert "workspace .venv launcher" in launcher_mod.build_setup_message()
    assert "Poetry environment launcher" in launcher_mod.build_setup_message()
    assert "PATH entry" in launcher_mod.build_setup_message()
