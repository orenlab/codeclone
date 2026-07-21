# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

import codeclone.surfaces.cli.controller_queries as controller_queries
import codeclone.surfaces.cli.subcommands as subcommands
from codeclone.surfaces.cli.types import CLIArgsLike, StatusConsole
from tests._import_graph import _iter_local_imports


def _args(**overrides: object) -> CLIArgsLike:
    values: dict[str, object] = {
        "blast_radius": (),
        "patch_verify": False,
        "session_stats": False,
        "audit": False,
        "audit_json": False,
        "strictness": "ci",
        "quiet": True,
        "no_color": True,
        "audit_enabled": False,
        "audit_path": ".codeclone/db/audit.sqlite3",
    }
    values.update(overrides)
    return cast(CLIArgsLike, Namespace(**values))


def test_pre_analysis_routing_preserves_session_stats_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def _render_session_stats(**kwargs: object) -> int:
        events.append("session")
        return 11

    monkeypatch.setattr(
        "codeclone.surfaces.cli.session_stats.render_session_stats",
        _render_session_stats,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.audit.render_audit",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("audit dispatched")),
    )

    result = controller_queries.run_pre_analysis_controller_query(
        args=_args(session_stats=True, audit=True, audit_json=True),
        root_path=tmp_path,
        query_console_factory=lambda args: cast(StatusConsole, object()),
    )

    assert result == 11
    assert events == ["session"]


def test_post_analysis_routing_preserves_blast_radius_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def _render_blast_radius(**kwargs: object) -> int:
        events.append("blast")
        return 12

    monkeypatch.setattr(
        "codeclone.surfaces.cli.blast_radius.render_blast_radius",
        _render_blast_radius,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.patch_verify.render_patch_verify",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("patch dispatched")),
    )

    result = controller_queries.run_post_analysis_controller_query(
        args=_args(blast_radius=("pkg/a.py",), patch_verify=True),
        report_document=None,
        root_path=tmp_path,
        analysis_result=cast(Any, object()),
        diff_context=cast(Any, object()),
        baseline_state=cast(Any, object()),
        console_factory=lambda: cast(StatusConsole, object()),
    )

    assert result == 12
    assert events == ["blast"]


def test_noop_controller_routing_does_not_create_console(tmp_path: Path) -> None:
    def _unexpected(*args: object) -> StatusConsole:
        raise AssertionError("console constructed for no-op routing")

    assert (
        controller_queries.run_pre_analysis_controller_query(
            args=_args(),
            root_path=tmp_path,
            query_console_factory=_unexpected,
        )
        is None
    )
    assert (
        controller_queries.run_post_analysis_controller_query(
            args=_args(),
            report_document=None,
            root_path=tmp_path,
            analysis_result=cast(Any, object()),
            diff_context=cast(Any, object()),
            baseline_state=cast(Any, object()),
            console_factory=lambda: _unexpected(),
        )
        is None
    )


@pytest.mark.parametrize(
    ("command", "module_name", "handler_name"),
    [
        ("setup", "codeclone.surfaces.cli.setup", "setup_main"),
        ("analytics", "codeclone.surfaces.cli.analytics", "analytics_main"),
        ("memory", "codeclone.surfaces.cli.memory", "memory_main"),
        (
            "observability",
            "codeclone.surfaces.cli.observability",
            "observability_main",
        ),
    ],
)
def test_subcommand_dispatch_is_lazy_and_forwards_exact_argv(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    module_name: str,
    handler_name: str,
) -> None:
    calls: list[list[str]] = []
    fake_module = ModuleType(module_name)

    def _handler(argv: list[str]) -> int:
        calls.append(argv)
        return 17

    setattr(fake_module, handler_name, _handler)
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    with pytest.raises(SystemExit) as caught:
        subcommands.dispatch_subcommand(["codeclone", command, "one", "two"])

    assert caught.value.code == 17
    assert calls == [["one", "two"]]


def test_analysis_dispatch_does_not_import_heavy_subcommands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = (
        "codeclone.surfaces.cli.setup",
        "codeclone.surfaces.cli.analytics",
        "codeclone.surfaces.cli.memory",
        "codeclone.surfaces.cli.observability",
    )
    for name in names:
        monkeypatch.delitem(sys.modules, name, raising=False)

    subcommands.dispatch_subcommand(["codeclone", "."])

    assert [name for name in names if name in sys.modules] == []


def test_baseline_recover_lock_dispatches_exact_operator_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"
    observed: dict[str, object] = {}

    def _recover(**kwargs: object) -> None:
        observed.update(kwargs)
        return None

    monkeypatch.setattr(
        "codeclone.surfaces.cli.baseline_state.recover_baseline_publish_lock",
        _recover,
    )
    with pytest.raises(SystemExit) as caught:
        subcommands.dispatch_subcommand(
            [
                "codeclone",
                "baseline",
                "recover-lock",
                "--path",
                str(target),
                "--expected-token",
                "operator-token",
                "--force",
            ]
        )

    assert caught.value.code == 0
    assert observed == {
        "target": target.resolve(),
        "expected_token": "operator-token",
        "force": True,
    }


def test_baseline_recover_lock_surfaces_typed_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "codeclone.surfaces.cli.baseline_state.recover_baseline_publish_lock",
        lambda **_kwargs: "foreign lock",
    )
    with pytest.raises(SystemExit) as caught:
        subcommands.dispatch_subcommand(
            [
                "codeclone",
                "baseline",
                "recover-lock",
                "--path",
                str(tmp_path / "baseline.json"),
                "--expected-token",
                "operator-token",
            ]
        )

    assert caught.value.code == 2
    assert "foreign lock" in capsys.readouterr().out


def test_routing_modules_have_one_way_cli_owned_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        Path("codeclone/surfaces/cli/controller_queries.py"),
        Path("codeclone/surfaces/cli/subcommands.py"),
    ):
        path = root / relative
        module_name = ".".join(relative.with_suffix("").parts)
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))
        assert [name for name in imports if name.endswith(".workflow")] == []
        assert [name for name in imports if ".surfaces.mcp" in name] == []

    workflow_source = (
        root / "codeclone" / "surfaces" / "cli" / "workflow.py"
    ).read_text("utf-8")
    for deferred_import in (
        "from .setup import setup_main",
        "from .analytics import analytics_main",
        "from .memory import memory_main",
        "from .observability import observability_main",
    ):
        assert deferred_import not in workflow_source
