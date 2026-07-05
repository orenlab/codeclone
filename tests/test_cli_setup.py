# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import types
from collections.abc import Callable, Mapping
from contextlib import redirect_stdout
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from codeclone.audit.events import EVENT_PATCH_VERIFIED, AuditEvent, repo_root_digest
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.config.pyproject_loader import load_pyproject_config
from codeclone.config.pyproject_writer import PyprojectWriterError
from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.console import PlainConsole
from codeclone.surfaces.cli.setup import render as setup_render
from codeclone.surfaces.cli.setup.engine.apply import apply_setup_plan
from codeclone.surfaces.cli.setup.engine.capabilities import (
    CAPABILITY_REGISTRY,
    CapabilityAxes,
    CapabilityMeta,
    DiscoverContext,
)
from codeclone.surfaces.cli.setup.engine.discover import (
    _client_config_present,
    build_setup_snapshot,
)
from codeclone.surfaces.cli.setup.engine.plan import build_setup_plan
from codeclone.surfaces.cli.setup.engine.rollup import (
    Readiness,
    _axes_satisfied,
    _optional_install_hint,
    derive_readiness,
    describe_capability,
)
from codeclone.surfaces.cli.setup.main import setup_main
from codeclone.surfaces.cli.setup.wizard import WizardPrompts, run_setup_wizard
from codeclone.surfaces.cli.types import PrinterLike
from codeclone.utils.json_io import json_text
from tests.test_cli_inprocess import _write_current_python_baseline

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN_SNAPSHOT = (
    _REPO_ROOT / "tests" / "fixtures" / "contract_snapshots" / "setup_snapshot_v1.json"
)
_DISCOVER_SOURCE = (
    _REPO_ROOT / "codeclone" / "surfaces" / "cli" / "setup" / "engine" / "discover.py"
)
_WORKFLOW_SOURCE = _REPO_ROOT / "codeclone" / "surfaces" / "cli" / "workflow.py"

_OPTIONAL_MODULES = frozenset(
    {
        "mcp",
        "defusedxml",
        "psutil",
        "tiktoken",
        "fastembed",
        "lancedb",
        "sklearn",
        "hdbscan",
    }
)


def _pop_modules_with_prefix(prefix: str) -> dict[str, types.ModuleType]:
    removed: dict[str, types.ModuleType] = {}
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            removed[name] = sys.modules.pop(name)
    return removed


def _restore_modules(modules: Mapping[str, types.ModuleType]) -> None:
    sys.modules.update(modules)


@pytest.fixture
def base_install_find_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    real_find_spec = importlib.util.find_spec

    def _fake_find_spec(name: str, package: object | None = None) -> object | None:
        if name in _OPTIONAL_MODULES:
            return None
        return real_find_spec(name, cast(str | None, package))

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    monkeypatch.setattr(
        "codeclone.analytics.capabilities._package_available",
        lambda _name: False,
    )


def _present(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: str,
    ctx: DiscoverContext,
) -> tuple[str, str, str]:
    """Bridge for tests: readiness is authoritative (derive_readiness); this echoes
    the given readiness and returns the presentation reason/action for it."""

    reason, action = describe_capability(
        meta,
        axes,
        cast(Readiness, readiness),
        ctx,
    )
    return readiness, reason, action


def _capability_rows(snapshot: dict[str, object]) -> list[dict[str, object]]:
    raw = snapshot.get("capabilities")
    assert isinstance(raw, list)
    return [cast(dict[str, object], item) for item in raw if isinstance(item, dict)]


def _plan_actions(plan: dict[str, object]) -> list[dict[str, object]]:
    raw = plan.get("actions")
    assert isinstance(raw, list)
    return [cast(dict[str, object], item) for item in raw if isinstance(item, dict)]


def _normalize_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    parsed = json.loads(json.dumps(snapshot))
    if not isinstance(parsed, dict):
        raise TypeError("expected dict snapshot")
    normalized: dict[str, object] = parsed
    normalized["root"] = "<ROOT>"
    normalized["head_commit"] = None
    runtime = normalized.get("runtime")
    if isinstance(runtime, dict):
        runtime_fields = cast(dict[str, object], runtime)
        runtime_fields["python_tag"] = "<PYTHON_TAG>"
        runtime_fields["codeclone_version"] = "<VERSION>"
    return normalized


def _build_canonical_fixture_root(root: Path) -> Path:
    _write_minimal_pyproject(root / "pyproject.toml", audit_enabled=False)
    _write_current_python_baseline(root / "codeclone.baseline.json")
    (root / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    return root


def _write_minimal_pyproject(path: Path, *, audit_enabled: bool = False) -> None:
    path.write_text(
        "[tool.codeclone]\n"
        'baseline = "codeclone.baseline.json"\n'
        f"audit_enabled = {'true' if audit_enabled else 'false'}\n",
        encoding="utf-8",
    )


def test_lazy_load_setup_not_imported_with_main() -> None:
    for name in list(sys.modules):
        if name == "codeclone.surfaces.cli.setup" or name.startswith(
            "codeclone.surfaces.cli.setup."
        ):
            del sys.modules[name]
    import codeclone.main  # noqa: F401

    assert "codeclone.surfaces.cli.setup" not in sys.modules


def test_lazy_load_positive_path(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(sys.modules):
        if name.startswith("codeclone.surfaces.cli.setup"):
            del sys.modules[name]
    monkeypatch.setattr(sys, "argv", ["codeclone", "setup", "status"])
    with pytest.raises(SystemExit) as exc:
        import codeclone.surfaces.cli.workflow as workflow

        workflow.main()
    assert exc.value.code == int(ExitCode.SUCCESS)
    assert "codeclone.surfaces.cli.setup" in sys.modules


def test_workflow_has_single_deferred_setup_import() -> None:
    text = _WORKFLOW_SOURCE.read_text(encoding="utf-8")
    assert text.count("from .setup import setup_main") == 1


def test_discover_does_not_import_mcp_surface() -> None:
    source = _DISCOVER_SOURCE.read_text(encoding="utf-8")
    assert "surfaces.mcp" not in source
    assert "collect_session_snapshot" not in source
    assert "run_memory_analysis_report" not in source


def test_import_setup_without_optional_extras(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    snapshot = build_setup_snapshot(tmp_path)
    assert snapshot["schema_version"] == "1"
    controlled = next(
        item for item in _capability_rows(snapshot) if item["id"] == "controlled_change"
    )
    assert controlled["readiness"] == "optional"
    assert str(controlled["readiness"]) != "blocked"


def test_setup_json_matches_golden_snapshot(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    root = _build_canonical_fixture_root(tmp_path)
    snapshot = build_setup_snapshot(root)
    expected = json.loads(_GOLDEN_SNAPSHOT.read_text(encoding="utf-8"))
    assert _normalize_snapshot(snapshot) == expected


def test_setup_json_stable_ordering(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    from codeclone.surfaces.cli.setup.engine.capabilities import GROUP_ORDER

    root = _build_canonical_fixture_root(tmp_path)
    first = build_setup_snapshot(root)
    second = build_setup_snapshot(root)
    # Full byte-identical determinism on a fixed repo/install/config state (I-05).
    assert first == second
    assert json_text(first, sort_keys=True) == json_text(second, sort_keys=True)
    first_caps = _capability_rows(first)
    second_caps = _capability_rows(second)
    assert first_caps == second_caps
    groups = [str(item["group"]) for item in first_caps]
    group_rank: dict[str, int] = {
        group: index for index, group in enumerate(GROUP_ORDER)
    }
    assert groups == sorted(groups, key=lambda group: group_rank[group])
    # Global order is (group rank, then capability id lexicographically).
    ordered_keys = [
        (group_rank[str(item["group"])], str(item["id"])) for item in first_caps
    ]
    assert ordered_keys == sorted(ordered_keys)
    # And within each group, ids are strictly lexicographic.
    for group in GROUP_ORDER:
        ids_in_group = [
            str(item["id"]) for item in first_caps if item["group"] == group
        ]
        assert ids_in_group == sorted(ids_in_group)
    # evidence lists are sorted within each capability.
    for item in first_caps:
        evidence = item["evidence"]
        assert isinstance(evidence, list)
        assert evidence == sorted(evidence)


def test_baseline_ready_with_trusted_baseline(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    _write_current_python_baseline(tmp_path / "codeclone.baseline.json")
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    snapshot = build_setup_snapshot(tmp_path)
    baseline = next(
        item for item in _capability_rows(snapshot) if item["id"] == "baseline"
    )
    assert baseline["readiness"] == "ready"


def test_workspace_hygiene_attention_without_gitignore(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    snapshot = build_setup_snapshot(tmp_path)
    hygiene = next(
        item for item in _capability_rows(snapshot) if item["id"] == "workspace_hygiene"
    )
    assert hygiene["readiness"] == "attention"


def test_malformed_pyproject_marks_analysis_invalid(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.codeclone]\nmin_loc = "not-an-int"\n',
        encoding="utf-8",
    )
    snapshot = build_setup_snapshot(tmp_path)
    rows = {str(item["id"]): item for item in _capability_rows(snapshot)}
    # Every built-in required capability fails closed to blocked; in particular
    # engineering_memory must not be masked as attention (no false "run init").
    for cap_id in ("analysis", "engineering_memory", "audit_and_intents", "ci_policy"):
        assert rows[cap_id]["configuration"] == "invalid"
        assert rows[cap_id]["readiness"] == "blocked"


def test_optional_extra_installed_invalid_config_is_attention_not_blocked() -> None:
    meta = CapabilityMeta(
        id="semantic_retrieval",
        group="project_knowledge",
        availability="optional_extra",
        optional_extra_name="semantic-local",
        requires_config=True,
    )
    axes = CapabilityAxes(
        installation="installed",
        configuration="invalid",
        runtime="not_verified",
        evidence=["probe:capability:embed"],
    )
    assert derive_readiness(meta, axes) == "attention"


def test_readiness_r2_optional_when_extra_missing() -> None:
    meta = CapabilityMeta(
        id="mcp_runtime",
        group="governed_agent_workflows",
        availability="optional_extra",
        optional_extra_name="mcp",
    )
    axes = CapabilityAxes(
        installation="missing",
        configuration="not_required",
        runtime="not_required",
        evidence=["probe:find_spec:mcp"],
    )
    assert derive_readiness(meta, axes) == "optional"


def test_default_subcommand_equals_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    buf_default = io.StringIO()
    buf_status = io.StringIO()
    with redirect_stdout(buf_default):
        rc_default = setup_main(["--json", "--root", str(tmp_path)])
    with redirect_stdout(buf_status):
        rc_status = setup_main(["status", "--json", "--root", str(tmp_path)])
    assert rc_default == rc_status == int(ExitCode.SUCCESS)
    assert json.loads(buf_default.getvalue()) == json.loads(buf_status.getvalue())


def test_json_writes_stdout_not_file(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    out = io.StringIO()
    with redirect_stdout(out):
        rc = setup_main(["--json", "--root", str(tmp_path)])
    assert rc == int(ExitCode.SUCCESS)
    payload = json.loads(out.getvalue())
    assert payload["projection_kind"] == "setup_snapshot"
    assert not (tmp_path / "--json").exists()


def test_head_commit_null_for_non_git_fixture(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    snapshot = build_setup_snapshot(tmp_path)
    assert snapshot["head_commit"] is None


def test_setup_snapshot_has_no_edit_allowed_field(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    snapshot = build_setup_snapshot(tmp_path)
    assert "edit_allowed" not in snapshot


def test_setup_does_not_invoke_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess must not be invoked by setup")

    monkeypatch.setattr("subprocess.run", _forbidden)
    monkeypatch.setattr("subprocess.Popen", _forbidden)
    assert setup_main(["--json", "--root", str(tmp_path)]) == int(ExitCode.SUCCESS)


def test_non_ascii_repo_path(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    root = tmp_path / "répo-测试"
    root.mkdir()
    _write_minimal_pyproject(root / "pyproject.toml")
    snapshot = build_setup_snapshot(root)
    assert snapshot["root"] == str(root.resolve())


def test_status_output_positioning_vocabulary(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        setup_main(["status", "--root", str(tmp_path)])
    text = buf.getvalue().lower()
    assert "governed agent workflows" in text
    assert "optional" in text or "attention" in text
    assert "linter" not in text
    assert "edit_allowed" not in text


def test_audit_populated_trail_is_ready(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True)
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    try:
        writer.emit(
            AuditEvent(
                event_type=EVENT_PATCH_VERIFIED,
                severity="info",
                repo_root_digest=repo_root_digest(tmp_path),
                agent_pid=123,
                agent_label="setup-test",
                run_id="abcdef123456",
                intent_id="intent-abcdef12-001",
                status="accepted",
            )
        )
    finally:
        writer.close()
    snapshot = build_setup_snapshot(tmp_path)
    audit = next(
        item for item in _capability_rows(snapshot) if item["id"] == "audit_and_intents"
    )
    # A populated audit trail is runtime-verified -> ready (never blocked).
    assert audit["runtime"] == "verified"
    assert audit["readiness"] == "ready"


def test_audit_enabled_empty_db_is_attention(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True)
    SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30).close()
    snapshot = build_setup_snapshot(tmp_path)
    audit = next(
        item for item in _capability_rows(snapshot) if item["id"] == "audit_and_intents"
    )
    # DB exists but no events recorded yet -> attention, not ready, never blocked.
    assert audit["readiness"] == "attention"
    assert audit["runtime"] == "not_verified"


def test_setup_json_serialization_contract(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    snapshot = build_setup_snapshot(tmp_path)
    rendered = json_text(snapshot, sort_keys=True, indent=True, trailing_newline=True)
    assert rendered.endswith("\n")
    roundtrip = json.loads(rendered)
    assert roundtrip["schema_version"] == "1"


def test_setup_plan_proposes_pyproject_section(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")

    plan = build_setup_plan(tmp_path)

    assert plan["projection_kind"] == "setup_plan"
    assert plan["read_only"] is True
    assert plan["status"] == "ready"
    assert isinstance(plan["plan_id"], str) and len(str(plan["plan_id"])) == 16
    actions = _plan_actions(plan)
    merge = next(item for item in actions if item["kind"] == "pyproject_merge")
    assert merge["capability_id"] == "analysis"
    assert merge["changed_keys"] == ["baseline"]
    preview = merge["preview"]
    assert isinstance(preview, dict)
    assert "tool.codeclone" in str(preview.get("unified_diff", ""))


def test_setup_plan_proposes_gitignore_append(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)

    plan = build_setup_plan(tmp_path)

    gitignore = next(
        item for item in _plan_actions(plan) if item["kind"] == "gitignore_append"
    )
    assert gitignore["capability_id"] == "workspace_hygiene"
    assert gitignore["lines"] == [".codeclone/"]
    preview = gitignore["preview"]
    assert isinstance(preview, dict)
    assert ".codeclone/" in str(preview.get("unified_diff", ""))


def test_setup_plan_is_empty_when_satisfied(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")

    plan = build_setup_plan(tmp_path)

    assert plan["status"] == "empty"
    assert plan["actions"] == []


def test_setup_plan_blocked_on_invalid_pyproject(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\nmin_loc = not-a-number\n",
        encoding="utf-8",
    )

    plan = build_setup_plan(tmp_path)

    blockers = plan["blockers"]
    assert isinstance(blockers, list)
    blocker_rows = [
        cast(dict[str, object], item) for item in blockers if isinstance(item, dict)
    ]
    assert any(item.get("kind") == "invalid_pyproject" for item in blocker_rows)
    assert not any(
        item.get("kind") == "pyproject_merge" for item in _plan_actions(plan)
    )


def test_setup_plan_does_not_write_files(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n', encoding="utf-8")
    before = pyproject.read_text(encoding="utf-8")

    setup_main(["plan", "--root", str(tmp_path)])

    assert pyproject.read_text(encoding="utf-8") == before


def test_setup_plan_json_has_no_edit_allowed(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        setup_main(["plan", "--json", "--root", str(tmp_path)])
    payload = json.loads(buf.getvalue())
    rendered = json.dumps(payload)
    assert "edit_allowed" not in rendered


def test_setup_plan_idempotent(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")

    first = build_setup_plan(tmp_path)
    second = build_setup_plan(tmp_path)

    assert first["plan_id"] == second["plan_id"]


def test_setup_apply_writes_pyproject_section(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")

    result = apply_setup_plan(tmp_path)

    assert result["projection_kind"] == "setup_apply"
    assert result["status"] == "applied"
    config = load_pyproject_config(tmp_path)
    assert config["baseline"] == str(tmp_path / "codeclone.baseline.json")
    assert "[tool.codeclone]" in (tmp_path / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_setup_apply_writes_gitignore(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)

    result = apply_setup_plan(tmp_path)

    assert result["status"] == "applied"
    assert ".codeclone/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_setup_apply_noop_when_plan_empty(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")

    result = apply_setup_plan(tmp_path)

    assert result["status"] == "noop"
    assert result["results"] == []


def test_setup_apply_dry_run_does_not_write(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n', encoding="utf-8")
    before = pyproject.read_text(encoding="utf-8")

    result = apply_setup_plan(tmp_path, dry_run=True)

    assert result["status"] == "preview"
    assert result["dry_run"] is True
    assert pyproject.read_text(encoding="utf-8") == before


def test_setup_apply_idempotent_when_already_satisfied(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")

    first = apply_setup_plan(tmp_path)
    second = apply_setup_plan(tmp_path)

    assert first["status"] == "noop"
    assert second["status"] == "noop"


def test_setup_apply_main_exit_success(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    assert setup_main(["apply", "--yes", "--root", str(tmp_path)]) == int(
        ExitCode.SUCCESS
    )


def test_setup_wizard_requires_tty(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    assert setup_main(["wizard", "--root", str(tmp_path)]) == int(
        ExitCode.CONTRACT_ERROR
    )


def test_setup_render_payload_default_console_respects_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_main_mod = importlib.import_module("codeclone.surfaces.cli.setup.main")
    calls: list[bool | None] = []
    rendered: list[PrinterLike] = []

    def _fake_console(*, no_color: bool | None = None) -> PlainConsole:
        calls.append(no_color)
        return PlainConsole()

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(setup_main_mod, "make_query_console", _fake_console)
    monkeypatch.setitem(
        setup_main_mod._PAYLOAD_RENDERERS,
        "status",
        lambda console, _payload: rendered.append(console),
    )

    setup_main_mod._render_payload("status", {})

    assert calls == [None]
    assert len(rendered) == 1


def test_setup_confirm_apply_default_console_respects_no_color(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_main_mod = importlib.import_module("codeclone.surfaces.cli.setup.main")
    calls: list[bool | None] = []

    def _fake_console(*, no_color: bool | None = None) -> PlainConsole:
        calls.append(no_color)
        return PlainConsole()

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(setup_main_mod, "make_query_console", _fake_console)
    monkeypatch.setattr(
        setup_main_mod,
        "build_setup_plan",
        lambda _root: {"projection_kind": "setup_plan"},
    )
    monkeypatch.setattr(setup_main_mod, "render_setup_plan", lambda **_kwargs: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    assert setup_main_mod._confirm_apply(tmp_path) is False
    assert calls == [None]


def test_setup_apply_interactive_binds_confirmed_plan_id(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_main_mod = importlib.import_module("codeclone.surfaces.cli.setup.main")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n', encoding="utf-8")

    monkeypatch.setattr(setup_main_mod, "_confirm_apply", lambda _root: "stale-plan")

    rc = setup_main_mod.setup_main(["apply", "--root", str(tmp_path)])

    assert rc == int(ExitCode.CONTRACT_ERROR)
    assert "[tool.codeclone]" not in pyproject.read_text(encoding="utf-8")


def test_setup_wizard_quit(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    choices = iter(["0"])
    prompts = WizardPrompts(
        ask_choice=lambda _message, _choices: next(choices),
        confirm=lambda _message, _default: False,
    )

    assert run_setup_wizard(tmp_path, prompts=prompts) == int(ExitCode.SUCCESS)


def test_setup_wizard_default_console_respects_no_color(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.setup import wizard as wizard_mod

    calls: list[bool | None] = []

    def _fake_console(*, no_color: bool | None = None) -> PlainConsole:
        calls.append(no_color)
        return PlainConsole()

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(wizard_mod, "_interactive_terminal_available", lambda: True)
    monkeypatch.setattr(wizard_mod, "make_query_console", _fake_console)

    assert wizard_mod.run_setup_wizard(tmp_path) == int(ExitCode.CONTRACT_ERROR)
    assert calls == [None]


def test_setup_wizard_guided_apply(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n',
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    choices = iter(["g", "0"])
    prompts = WizardPrompts(
        ask_choice=lambda _message, _choices: next(choices),
        confirm=lambda _message, _default: True,
    )

    assert run_setup_wizard(tmp_path, prompts=prompts) == int(ExitCode.SUCCESS)
    assert ".codeclone/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "[tool.codeclone]" in (tmp_path / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_setup_wizard_guided_apply_skipped(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n', encoding="utf-8")
    before = pyproject.read_text(encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    choices = iter(["g", "0"])
    prompts = WizardPrompts(
        ask_choice=lambda _message, _choices: next(choices),
        confirm=lambda _message, _default: False,
    )

    assert run_setup_wizard(tmp_path, prompts=prompts) == int(ExitCode.SUCCESS)
    assert pyproject.read_text(encoding="utf-8") == before


def _fresh_apply_module() -> types.ModuleType:
    return importlib.import_module("codeclone.surfaces.cli.setup.engine.apply")


def _fresh_setup_main() -> Callable[..., int]:
    setup_main = importlib.import_module("codeclone.surfaces.cli.setup.main").setup_main
    return cast(Callable[..., int], setup_main)


def _minimal_setup_snapshot(root: Path) -> dict[str, object]:
    return {
        "root": str(root),
        "runtime": {"python_tag": "cp314", "codeclone_version": "2.1.0"},
        "maturity": {
            "connected": False,
            "governed": False,
            "evidence_backed": False,
            "team_ready": False,
            "release_ready": False,
        },
        "capabilities": [
            {
                "id": "analysis",
                "group": "project_knowledge",
                "label": "Analysis",
                "readiness": "attention",
                "availability": "core",
                "reason": "missing pyproject section",
                "installation": "installed",
                "configuration": "missing",
                "runtime": "not_verified",
                "evidence": ["probe:pyproject"],
                "recommended_action": "run setup plan",
            }
        ],
    }


def _rich_console() -> PrinterLike:
    from rich.console import Console

    return cast(PrinterLike, Console(file=io.StringIO(), force_terminal=True))


def test_setup_render_status_plain_and_rich(tmp_path: Path) -> None:
    snapshot = _minimal_setup_snapshot(tmp_path)
    plain = PlainConsole()
    setup_render.render_setup_status(console=plain, snapshot=snapshot)
    with patch.object(setup_render, "supports_rich_console", return_value=True):
        setup_render.render_setup_status(console=_rich_console(), snapshot=snapshot)


def test_setup_render_string_list_guard_requires_string_elements() -> None:
    assert setup_render._is_string_list(["probe:pyproject"]) is True
    assert setup_render._is_string_list(["probe:pyproject", 1]) is False
    assert setup_render._is_string_list(("probe:pyproject",)) is False


def test_setup_render_doctor_plain_and_rich(tmp_path: Path) -> None:
    snapshot = _minimal_setup_snapshot(tmp_path)
    plain = PlainConsole()
    setup_render.render_setup_doctor(console=plain, snapshot=snapshot)
    with patch.object(setup_render, "supports_rich_console", return_value=True):
        setup_render.render_setup_doctor(console=_rich_console(), snapshot=snapshot)


def test_setup_render_plan_plain_and_rich(tmp_path: Path) -> None:
    plan: dict[str, object] = {
        "root": str(tmp_path),
        "status": "ready",
        "plan_id": "abcd1234ef567890",
        "blockers": [{"kind": "invalid_pyproject", "reason": "bad min_loc"}],
        "actions": [
            {
                "kind": "pyproject_merge",
                "path": "pyproject.toml",
                "status": "ready",
                "preview": {"unified_diff": "+[tool.codeclone]\n"},
            }
        ],
    }
    plain = PlainConsole()
    setup_render.render_setup_plan(console=plain, plan=plan)
    with patch.object(setup_render, "supports_rich_console", return_value=True):
        setup_render.render_setup_plan(console=_rich_console(), plan=plan)

    empty_plan: dict[str, object] = {"status": "empty", "plan_id": "empty000000000000"}
    setup_render.render_setup_plan(console=plain, plan=empty_plan)


def test_setup_render_apply_plain_and_rich(tmp_path: Path) -> None:
    blocked: dict[str, object] = {
        "status": "blocked",
        "plan_id": "blocked0000000000",
        "dry_run": False,
        "results": [],
    }
    applied: dict[str, object] = {
        "status": "applied",
        "plan_id": "applied0000000000",
        "dry_run": True,
        "results": [
            {
                "kind": "gitignore_append",
                "path": ".gitignore",
                "status": "applied",
                "message": "ok",
            }
        ],
    }
    plain = PlainConsole()
    setup_render.render_setup_apply(console=plain, result=blocked)
    setup_render.render_setup_apply(console=plain, result=applied)
    with patch.object(setup_render, "supports_rich_console", return_value=True):
        setup_render.render_setup_apply(console=_rich_console(), result=applied)


def test_setup_render_capability_table_and_helpers() -> None:
    rows: list[Mapping[str, object]] = [
        {"label": "Analysis", "readiness": "ready", "reason": ""},
    ]
    plain = PlainConsole()
    setup_render.render_setup_capability_table(plain, rows)
    with patch.object(setup_render, "supports_rich_console", return_value=True):
        setup_render.render_setup_capability_table(_rich_console(), rows)
    assert setup_render.snapshot_capabilities({"capabilities": "not-a-list"}) == []
    assert setup_render.snapshot_capabilities({"capabilities": rows}) == rows


def test_setup_wizard_requires_rich_console(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert run_setup_wizard(tmp_path, console=PlainConsole()) == int(
        ExitCode.CONTRACT_ERROR
    )


def test_setup_wizard_doctor_and_sphere(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    choices = iter(["d", "1", "0"])
    prompts = WizardPrompts(
        ask_choice=lambda _message, _choices: next(choices),
        confirm=lambda _message, _default: False,
    )
    assert run_setup_wizard(tmp_path, prompts=prompts) == int(ExitCode.SUCCESS)


def test_setup_wizard_guided_blocked_plan(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\nmin_loc = not-a-number\n",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    choices = iter(["g", "0"])
    prompts = WizardPrompts(
        ask_choice=lambda _message, _choices: next(choices),
        confirm=lambda _message, _default: True,
    )
    assert run_setup_wizard(tmp_path, prompts=prompts) == int(ExitCode.CONTRACT_ERROR)


def test_setup_wizard_guided_empty_plan(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    choices = iter(["g", "0"])
    prompts = WizardPrompts(
        ask_choice=lambda _message, _choices: next(choices),
        confirm=lambda _message, _default: True,
    )
    assert run_setup_wizard(tmp_path, prompts=prompts) == int(ExitCode.SUCCESS)


def test_setup_apply_blocked_and_failure_paths(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone]\nmin_loc = not-a-number\n",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    blocked = apply_setup_plan(tmp_path)
    assert blocked["status"] == "blocked"

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    def _fail_merge(*_args: object, **_kwargs: object) -> None:
        raise PyprojectWriterError("merge failed")

    apply_mod = _fresh_apply_module()
    monkeypatch.setattr(apply_mod, "merge_tool_codeclone", _fail_merge)
    failed = apply_mod.apply_setup_plan(tmp_path)
    assert failed["status"] == "partial"
    assert failed["results"][0]["status"] == "applied"
    assert failed["results"][1]["status"] == "failed"


def test_setup_apply_unsupported_action_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = {
        "root": str(tmp_path),
        "plan_id": "test000000000000",
        "status": "ready",
        "actions": [
            {
                "id": "bad-action",
                "kind": "unknown_kind",
                "path": "nowhere",
                "status": "ready",
            }
        ],
    }
    apply_mod = _fresh_apply_module()
    monkeypatch.setattr(apply_mod, "build_setup_plan", lambda _root: plan)
    result = apply_mod.apply_setup_plan(tmp_path)
    assert result["status"] == "failed"


def test_setup_main_invalid_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing-root"
    assert setup_main(["status", "--root", str(missing)]) == int(
        ExitCode.CONTRACT_ERROR
    )


def test_setup_main_apply_failed_exit(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    def _fail_merge(*_args: object, **_kwargs: object) -> None:
        raise PyprojectWriterError("merge failed")

    apply_mod = _fresh_apply_module()
    monkeypatch.setattr(apply_mod, "merge_tool_codeclone", _fail_merge)
    setup_main = _fresh_setup_main()
    assert setup_main(["apply", "--yes", "--root", str(tmp_path)]) == int(
        ExitCode.INTERNAL_ERROR
    )


def test_setup_main_doctor_command(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = setup_main(["doctor", "--root", str(tmp_path)])
    assert rc == int(ExitCode.SUCCESS)
    assert "doctor" in buf.getvalue().lower() or "analysis" in buf.getvalue().lower()


def test_setup_apply_dry_run_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    def _fail_merge(*_args: object, **_kwargs: object) -> None:
        raise PyprojectWriterError("merge failed")

    apply_mod = _fresh_apply_module()
    monkeypatch.setattr(apply_mod, "merge_tool_codeclone", _fail_merge)
    result = apply_mod.apply_setup_plan(tmp_path, dry_run=True)
    assert result["status"] == "preview"
    assert result["dry_run"] is True
    assert result["results"][-1]["status"] == "failed"


def test_setup_apply_gitignore_missing_lines(tmp_path: Path) -> None:
    apply_mod = _fresh_apply_module()
    action = {
        "id": "gitignore_append:workspace_hygiene",
        "kind": "gitignore_append",
        "path": ".gitignore",
        "status": "ready",
        "lines": [],
    }
    row = apply_mod._apply_gitignore_append(tmp_path, action, dry_run=False)
    assert row["status"] == "failed"
    assert row["message"] == "missing lines"


def test_setup_rollup_optional_install_hints() -> None:
    assert "codeclone[mcp]" in _optional_install_hint(
        CapabilityMeta(
            id="mcp_runtime",
            group="governed_agent_workflows",
            availability="optional_extra",
            optional_extra_name="mcp",
        )
    )
    assert _optional_install_hint(
        CapabilityMeta(
            id="semantic_retrieval",
            group="project_knowledge",
            availability="optional_extra",
            optional_extra_name="semantic-local",
        )
    ).endswith("semantic-local")
    assert (
        _optional_install_hint(
            CapabilityMeta(
                id="other",
                group="project_knowledge",
                availability="optional_extra",
                optional_extra_name="unknown-extra",
            )
        )
        == ""
    )


def test_setup_rollup_axes_satisfied_branches() -> None:
    meta = CapabilityMeta(
        id="analysis",
        group="core_analysis",
        availability="built_in",
        requires_config=True,
        requires_runtime_proof=True,
    )
    assert not _axes_satisfied(
        meta,
        CapabilityAxes(
            installation="unknown",
            configuration="configured",
            runtime="verified",
            evidence=[],
        ),
    )
    assert not _axes_satisfied(
        meta,
        CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="verified",
            evidence=[],
        ),
    )
    assert not _axes_satisfied(
        meta,
        CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="unavailable",
            evidence=[],
        ),
    )


def test_setup_discover_audit_summary_oserror(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("not sqlite", encoding="utf-8")

    def _raise_oserror(**_kwargs: object) -> None:
        raise OSError("audit unreadable")

    monkeypatch.setattr(
        "codeclone.surfaces.cli.setup.engine.discover.read_audit_summary",
        _raise_oserror,
    )
    snapshot = build_setup_snapshot(tmp_path)
    audit = next(
        item for item in _capability_rows(snapshot) if item["id"] == "audit_and_intents"
    )
    assert audit["readiness"] in {"attention", "optional", "ready", "blocked"}


def test_setup_main_payload_build_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    setup_main_mod = importlib.import_module("codeclone.surfaces.cli.setup.main")

    def _boom(_root: Path) -> dict[str, object]:
        raise RuntimeError("snapshot failed")

    monkeypatch.setitem(setup_main_mod._PAYLOAD_BUILDERS, "status", _boom)
    assert setup_main_mod.setup_main(["status", "--root", str(tmp_path)]) == int(
        ExitCode.INTERNAL_ERROR
    )


def test_setup_apply_pyproject_merge_missing_updates(tmp_path: Path) -> None:
    apply_mod = _fresh_apply_module()
    row = apply_mod._apply_pyproject_merge(
        tmp_path,
        {
            "id": "pyproject_merge:analysis",
            "kind": "pyproject_merge",
            "updates": "not-a-mapping",
        },
        dry_run=False,
    )
    assert row["status"] == "failed"
    assert row["message"] == "missing updates"


def test_setup_apply_pyproject_merge_already_satisfied(tmp_path: Path) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    apply_mod = _fresh_apply_module()
    row = apply_mod._apply_pyproject_merge(
        tmp_path,
        {
            "id": "pyproject_merge:audit_and_intents",
            "kind": "pyproject_merge",
            "updates": {"audit_enabled": True},
        },
        dry_run=False,
    )
    assert row["status"] == "skipped"


def test_setup_plan_missing_pyproject_blocker(tmp_path: Path) -> None:
    plan = build_setup_plan(tmp_path)
    blockers = plan["blockers"]
    assert isinstance(blockers, list)
    blocker_rows = [
        cast(dict[str, object], item) for item in blockers if isinstance(item, dict)
    ]
    assert any(item.get("kind") == "missing_pyproject" for item in blocker_rows)


def test_setup_rollup_derive_readiness_branches() -> None:
    unsupported = CapabilityMeta(
        id="legacy",
        group="core_analysis",
        availability="unsupported",
    )
    axes = CapabilityAxes(
        installation="installed",
        configuration="configured",
        runtime="verified",
        evidence=[],
    )
    assert derive_readiness(unsupported, axes) == "not_applicable"

    optional_unknown = CapabilityMeta(
        id="mcp_runtime",
        group="governed_agent_workflows",
        availability="optional_extra",
        optional_extra_name="mcp",
    )
    assert (
        derive_readiness(
            optional_unknown,
            CapabilityAxes(
                installation="unknown",
                configuration="not_required",
                runtime="not_required",
                evidence=[],
            ),
        )
        == "attention"
    )

    built_in = CapabilityMeta(
        id="analysis",
        group="core_analysis",
        availability="built_in",
        requires_config=True,
    )
    assert (
        derive_readiness(
            built_in,
            CapabilityAxes(
                installation="installed",
                configuration="invalid",
                runtime="verified",
                evidence=[],
            ),
        )
        == "blocked"
    )

    assert (
        derive_readiness(
            built_in,
            CapabilityAxes(
                installation="unknown",
                configuration="unconfigured",
                runtime="not_verified",
                evidence=[],
            ),
        )
        == "attention"
    )

    assert (
        derive_readiness(
            CapabilityMeta(
                id="analysis",
                group="core_analysis",
                availability="built_in",
                requires_config=True,
                requires_runtime_proof=True,
            ),
            CapabilityAxes(
                installation="installed",
                configuration="configured",
                runtime="unavailable",
                evidence=[],
            ),
        )
        == "attention"
    )


def test_setup_wizard_default_prompts_rejects_plain_console() -> None:
    from codeclone.surfaces.cli.setup.wizard import _default_wizard_prompts

    with pytest.raises(RuntimeError, match="Rich"):
        _default_wizard_prompts(PlainConsole())


def _capability_meta(capability_id: str) -> CapabilityMeta:
    return next(item for item in CAPABILITY_REGISTRY if item.id == capability_id)


def _empty_discover_context(root: Path) -> DiscoverContext:
    return DiscoverContext(
        root_path=root,
        config={},
        config_error=None,
        has_codeclone_section=False,
        baseline_path=root / "codeclone.baseline.json",
        baseline_status=None,
        head_commit=None,
        install_extras={},
        mcp_installed=False,
    )


def test_setup_presentation_handlers(tmp_path: Path) -> None:
    ctx = _empty_discover_context(tmp_path)
    mcp_meta = _capability_meta("mcp_runtime")
    missing_axes = CapabilityAxes(
        installation="missing",
        configuration="not_required",
        runtime="not_required",
        evidence=[],
    )
    readiness, reason, _action = _present(
        mcp_meta,
        missing_axes,
        "optional",
        ctx,
    )
    assert readiness == "optional"
    assert reason

    controlled_meta = _capability_meta("controlled_change")
    readiness, _, _ = _present(
        controlled_meta,
        missing_axes,
        "optional",
        ctx,
    )
    assert readiness == "optional"

    baseline_meta = _capability_meta("baseline")
    readiness, _, _ = _present(
        baseline_meta,
        CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="not_verified",
            evidence=[],
        ),
        "ready",
        ctx,
    )
    assert readiness == "ready"


def test_setup_rollup_coverage_xml_hint() -> None:
    hint = _optional_install_hint(
        CapabilityMeta(
            id="coverage_evidence",
            group="project_knowledge",
            availability="optional_extra",
            optional_extra_name="coverage-xml",
        )
    )
    assert "coverage-xml" in hint


def test_setup_discover_audit_summary_exception(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)
    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("x", encoding="utf-8")

    def _raise_runtime(**_kwargs: object) -> None:
        raise RuntimeError("audit summary failed")

    monkeypatch.setattr(
        "codeclone.surfaces.cli.setup.engine.discover.read_audit_summary",
        _raise_runtime,
    )
    snapshot = build_setup_snapshot(tmp_path)
    assert snapshot["schema_version"] == "1"


def test_setup_discover_client_config_from_cursor_mcp(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text("{}", encoding="utf-8")
    snapshot = build_setup_snapshot(tmp_path)
    controlled = next(
        item for item in _capability_rows(snapshot) if item["id"] == "controlled_change"
    )
    assert controlled["readiness"] in {"attention", "optional", "ready"}


def test_setup_presentation_default_for_unknown_capability(tmp_path: Path) -> None:
    ctx = _empty_discover_context(tmp_path)
    unknown_meta = CapabilityMeta(
        id="not_registered_capability",
        group="core_analysis",
        availability="built_in",
    )
    readiness, reason, action = _present(
        unknown_meta,
        CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="verified",
            evidence=[],
        ),
        "attention",
        ctx,
    )
    assert readiness == "attention"
    assert reason
    assert action == ""


def test_setup_main_apply_blocked_exit_code() -> None:
    setup_main_mod = importlib.import_module("codeclone.surfaces.cli.setup.main")
    assert setup_main_mod._exit_code_for_apply("blocked") == int(
        ExitCode.CONTRACT_ERROR
    )
    assert setup_main_mod._exit_code_for_apply("stale_plan") == int(
        ExitCode.CONTRACT_ERROR
    )
    assert setup_main_mod._exit_code_for_apply("partial") == int(
        ExitCode.INTERNAL_ERROR
    )
    assert setup_main_mod._exit_code_for_apply("applied") == int(ExitCode.SUCCESS)


def test_setup_rollup_analytics_optional_hint() -> None:
    hint = _optional_install_hint(
        CapabilityMeta(
            id="analytics_cockpit",
            group="project_knowledge",
            availability="optional_extra",
            optional_extra_name="analytics",
        )
    )
    assert hint


def test_setup_discover_vscode_settings_client_config(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    (vscode_dir / "settings.json").write_text(
        '{"mcp.servers": {"codeclone": {}}}',
        encoding="utf-8",
    )
    snapshot = build_setup_snapshot(tmp_path)
    maturity = cast(dict[str, object], snapshot["maturity"])
    assert maturity["connected"] is True


def test_setup_apply_gitignore_post_write_verification_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_mod = _fresh_apply_module()
    monkeypatch.setattr(
        apply_mod,
        "repo_gitignore_covers_codeclone_cache",
        lambda _root: False,
    )
    row = apply_mod._apply_gitignore_append(
        tmp_path,
        {
            "id": "gitignore_append:workspace_hygiene",
            "kind": "gitignore_append",
            "lines": [".codeclone/"],
        },
        dry_run=False,
    )
    assert row["status"] == "failed"
    assert row["message"] == "post-write verification failed"


def test_setup_derive_readiness_unconfigured_requires_config() -> None:
    meta = CapabilityMeta(
        id="analysis",
        group="core_analysis",
        availability="built_in",
        requires_config=True,
    )
    assert (
        derive_readiness(
            meta,
            CapabilityAxes(
                installation="installed",
                configuration="unconfigured",
                runtime="not_verified",
                evidence=[],
            ),
        )
        == "attention"
    )


def test_setup_discover_root_mcp_json_client_config(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    snapshot = build_setup_snapshot(tmp_path)
    maturity = cast(dict[str, object], snapshot["maturity"])
    assert maturity["connected"] is True


def test_setup_derive_readiness_optional_extra_invalid_config() -> None:
    meta = CapabilityMeta(
        id="mcp_runtime",
        group="governed_agent_workflows",
        availability="optional_extra",
        optional_extra_name="mcp",
    )
    assert (
        derive_readiness(
            meta,
            CapabilityAxes(
                installation="installed",
                configuration="invalid",
                runtime="not_required",
                evidence=[],
            ),
        )
        == "attention"
    )


def test_setup_presentation_default_ready_path(tmp_path: Path) -> None:
    ctx = _empty_discover_context(tmp_path)
    readiness, reason, action = _present(
        CapabilityMeta(
            id="not_registered_capability",
            group="core_analysis",
            availability="built_in",
        ),
        CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="verified",
            evidence=[],
        ),
        "ready",
        ctx,
    )
    assert readiness == "ready"
    assert reason == ""
    assert action == ""


def test_setup_apply_ignores_non_list_plan_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_mod = _fresh_apply_module()
    monkeypatch.setattr(
        apply_mod,
        "build_setup_plan",
        lambda _root: {
            "root": str(tmp_path),
            "plan_id": "bad0000000000000",
            "status": "ready",
            "actions": "not-a-list",
        },
    )
    result = apply_mod.apply_setup_plan(tmp_path)
    assert result["status"] == "noop"


def test_setup_apply_gitignore_read_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")
    apply_mod = _fresh_apply_module()
    original_read_text = Path.read_text

    def _patched_read_text(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if self == gitignore:
            raise OSError("read failed")
        return original_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)
    row = apply_mod._apply_gitignore_append(
        tmp_path,
        {
            "id": "gitignore_append:workspace_hygiene",
            "kind": "gitignore_append",
            "lines": [".codeclone/"],
        },
        dry_run=False,
    )
    assert row["status"] == "failed"
    assert "read failed" in str(row["message"])


def test_setup_discover_probe_unknown_capability(tmp_path: Path) -> None:
    from codeclone.surfaces.cli.setup.engine import discover as discover_mod

    ctx = _empty_discover_context(tmp_path)
    probed = discover_mod._probe_capability(
        CapabilityMeta(
            id="capability_without_probe",
            group="core_analysis",
            availability="built_in",
        ),
        ctx,
    )
    assert probed.axes.installation == "unknown"
    assert probed.axes.evidence == ["probe:unknown:capability"]


def test_setup_apply_gitignore_write_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_mod = _fresh_apply_module()

    def _raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(apply_mod, "write_gitignore_text_atomically", _raise_oserror)
    row = apply_mod._apply_gitignore_append(
        tmp_path,
        {
            "id": "gitignore_append:workspace_hygiene",
            "kind": "gitignore_append",
            "lines": [".codeclone/"],
        },
        dry_run=False,
    )
    assert row["status"] == "failed"
    assert row["message"] == "write failed"


def test_setup_discover_vscode_settings_symlink_refused(
    tmp_path: Path,
) -> None:
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    settings = vscode_dir / "settings.json"
    settings.write_text('{"mcp.servers": {"codeclone": {}}}', encoding="utf-8")
    assert _client_config_present(tmp_path) is True
    # A symlinked settings file is refused (fail closed), so not detected.
    settings.unlink()
    settings.symlink_to(tmp_path / "does-not-exist.json")
    assert _client_config_present(tmp_path) is False


def test_setup_rollup_axes_satisfied_invalid_configuration() -> None:
    meta = CapabilityMeta(
        id="analysis",
        group="core_analysis",
        availability="built_in",
    )
    assert not _axes_satisfied(
        meta,
        CapabilityAxes(
            installation="installed",
            configuration="invalid",
            runtime="verified",
            evidence=[],
        ),
    )


def test_setup_discover_audit_resolve_and_summary_errors(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.setup.engine.discover import build_discover_context

    _write_minimal_pyproject(tmp_path / "pyproject.toml", audit_enabled=True)

    def _resolve_oserror(**_kwargs: object) -> None:
        raise OSError("audit path failed")

    monkeypatch.setattr(
        "codeclone.surfaces.cli.setup.engine.discover.resolve_audit_path",
        _resolve_oserror,
    )
    ctx = build_discover_context(tmp_path)
    assert ctx.audit_db_exists is False

    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"present")

    monkeypatch.setattr(
        "codeclone.surfaces.cli.setup.engine.discover.resolve_audit_path",
        lambda **_kwargs: db_path,
    )

    def _summary_runtime_error(**_kwargs: object) -> None:
        raise RuntimeError("summary failed")

    monkeypatch.setattr(
        "codeclone.surfaces.cli.setup.engine.discover.read_audit_summary",
        _summary_runtime_error,
    )
    ctx_after_summary_error = build_discover_context(tmp_path)
    assert ctx_after_summary_error.audit_db_exists is False
    assert ctx_after_summary_error.audit_summary_events == 0


def test_setup_discover_analysis_find_spec_import_error(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_find_spec = importlib.util.find_spec

    def _raising_find_spec(name: str, package: object | None = None) -> object | None:
        if name == "codeclone.core":
            raise ImportError("blocked import")
        return real_find_spec(name, cast(str | None, package))

    monkeypatch.setattr(importlib.util, "find_spec", _raising_find_spec)
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    snapshot = build_setup_snapshot(tmp_path)
    analysis = next(
        item for item in _capability_rows(snapshot) if item["id"] == "analysis"
    )
    assert analysis["installation"] == "unknown"


def test_setup_discover_github_and_pre_commit_probes(
    tmp_path: Path,
) -> None:
    from codeclone.surfaces.cli.setup.engine import discover as discover_mod

    ctx = _empty_discover_context(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (workflows / "codeclone.yml").write_text(
        "uses: orenlab/codeclone-action\n",
        encoding="utf-8",
    )
    github_axes = discover_mod._probe_github_workflow(ctx)
    assert github_axes.configuration == "configured"

    # A workflow that is a refused symlink is the only entry -> unknown install.
    broken_root = tmp_path / "broken-workflows"
    broken_root.mkdir()
    broken_ctx = _empty_discover_context(broken_root)
    only_unreadable = broken_root / ".github" / "workflows"
    only_unreadable.mkdir(parents=True)
    (only_unreadable / "broken.yml").symlink_to(broken_root / "missing.yml")
    broken_axes = discover_mod._probe_github_workflow(broken_ctx)
    assert broken_axes.installation == "unknown"

    pre_commit = tmp_path / ".pre-commit-config.yaml"
    pre_commit.write_text("repos:\n  - repo: local\n", encoding="utf-8")
    assert discover_mod._probe_pre_commit_hook(ctx).configuration == "unconfigured"

    pre_commit.write_text("repos:\n  - repo: codeclone\n", encoding="utf-8")
    assert discover_mod._probe_pre_commit_hook(ctx).configuration == "configured"

    # A symlinked pre-commit config is refused -> unknown installation.
    symlink_root = tmp_path / "symlink-precommit"
    symlink_root.mkdir()
    symlink_ctx = _empty_discover_context(symlink_root)
    (symlink_root / ".pre-commit-config.yaml").symlink_to(symlink_root / "missing.yaml")
    unreadable_pre_commit = discover_mod._probe_pre_commit_hook(symlink_ctx)
    assert unreadable_pre_commit.installation == "unknown"


def test_setup_discover_semantic_and_ci_policy_probes(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.setup.engine import discover as discover_mod

    ctx = DiscoverContext(
        root_path=tmp_path,
        config={"semantic_enabled": True},
        config_error=None,
        has_codeclone_section=True,
        baseline_path=tmp_path / "codeclone.baseline.json",
        baseline_status=None,
        head_commit=None,
        install_extras={},
        mcp_installed=False,
        memory_report=None,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.cli.setup.engine.discover.check_capability",
        lambda name: type("Status", (), {"available": name == "embed"})(),
    )
    semantic_axes = discover_mod._probe_semantic_retrieval(ctx)
    assert semantic_axes.runtime == "not_verified"

    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.codeclone]\nci = true\nbaseline = "missing.json"\n',
        encoding="utf-8",
    )
    ci_ctx = build_setup_snapshot(tmp_path)
    ci_policy = next(
        item for item in _capability_rows(ci_ctx) if item["id"] == "ci_policy"
    )
    assert ci_policy["configuration"] == "unconfigured"


def test_setup_discover_baseline_status_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.baseline import Baseline
    from codeclone.surfaces.cli.setup.engine import discover as discover_mod

    baseline_path = tmp_path / "codeclone.baseline.json"
    baseline_path.write_text("{", encoding="utf-8")

    def _load_oserror(self: Baseline, **_kwargs: object) -> None:
        raise OSError("baseline unreadable")

    monkeypatch.setattr(Baseline, "load", _load_oserror)
    # An unreadable baseline is "unknown" (fail closed), not "invalid JSON".
    assert discover_mod._probe_baseline_status(baseline_path) is None


def test_setup_discover_tool_codeclone_section_edge_cases(tmp_path: Path) -> None:
    from codeclone.surfaces.cli.setup.engine import discover as discover_mod

    assert discover_mod._tool_codeclone_section_present(tmp_path) is False
    (tmp_path / "pyproject.toml").write_text("tool = 1\n", encoding="utf-8")
    assert discover_mod._tool_codeclone_section_present(tmp_path) is False
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    assert discover_mod._tool_codeclone_section_present(tmp_path) is False


def test_setup_presentation_controlled_change_unconfigured(tmp_path: Path) -> None:
    ctx = _empty_discover_context(tmp_path)
    meta = _capability_meta("controlled_change")
    readiness, reason, action = _present(
        meta,
        CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[],
        ),
        "attention",
        ctx,
    )
    assert readiness == "attention"
    assert reason
    assert action


def test_setup_presentation_default_optional_path(tmp_path: Path) -> None:
    ctx = _empty_discover_context(tmp_path)
    readiness, reason, action = _present(
        CapabilityMeta(
            id="not_registered_capability",
            group="core_analysis",
            availability="optional_extra",
            optional_extra_name="mcp",
        ),
        CapabilityAxes(
            installation="missing",
            configuration="not_required",
            runtime="not_required",
            evidence=[],
        ),
        "optional",
        ctx,
    )
    assert readiness == "optional"
    assert reason
    assert action


def test_setup_presentation_baseline_untrusted(tmp_path: Path) -> None:
    from codeclone.baseline.trust import BaselineStatus

    ctx = DiscoverContext(
        root_path=tmp_path,
        config={},
        config_error=None,
        has_codeclone_section=True,
        baseline_path=tmp_path / "codeclone.baseline.json",
        baseline_status=BaselineStatus.INVALID_JSON,
        head_commit=None,
        install_extras={},
        mcp_installed=False,
    )
    meta = _capability_meta("baseline")
    readiness, reason, action = _present(
        meta,
        CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[],
        ),
        "attention",
        ctx,
    )
    assert readiness == "attention"
    assert reason
    assert action


# ---------------------------------------------------------------------------
# Isolation / permission regression (§17.2, §17.4, AC-01, AC-09)
# ---------------------------------------------------------------------------


def test_setup_main_does_not_import_mcp_surface(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    removed_mcp_modules = _pop_modules_with_prefix("codeclone.surfaces.mcp")
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert setup_main(["status", "--json", "--root", str(tmp_path)]) == int(
                ExitCode.SUCCESS
            )
        assert not any(
            name.startswith("codeclone.surfaces.mcp") for name in sys.modules
        )
    finally:
        _restore_modules(removed_mcp_modules)


def test_setup_does_not_create_intents(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    for command in ("status", "doctor", "plan"):
        with redirect_stdout(io.StringIO()):
            setup_main([command, "--root", str(tmp_path)])
    assert not (tmp_path / ".codeclone" / "intents").exists()


# ---------------------------------------------------------------------------
# Mutation safety: confirmation gate and plan-id binding (§3.3, TOCTOU)
# ---------------------------------------------------------------------------


def test_apply_refuses_without_yes_noninteractive(
    tmp_path: Path,
    base_install_find_spec: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    before = pyproject.read_text(encoding="utf-8")
    rc = setup_main(["apply", "--root", str(tmp_path)])
    assert rc == int(ExitCode.CONTRACT_ERROR)
    assert pyproject.read_text(encoding="utf-8") == before


def test_apply_stale_plan_id_refused_no_write(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    result = apply_setup_plan(tmp_path, expected_plan_id="deadbeefdeadbeef")
    assert result["status"] == "stale_plan"
    assert "[tool.codeclone]" not in pyproject.read_text(encoding="utf-8")


def test_apply_matching_plan_id_proceeds(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    plan = build_setup_plan(tmp_path)
    result = apply_setup_plan(tmp_path, expected_plan_id=str(plan["plan_id"]))
    assert result["status"] == "applied"


# ---------------------------------------------------------------------------
# Flag validation (§10.9 grammar)
# ---------------------------------------------------------------------------


def test_flag_validation_rejects_dry_run_on_status(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    assert setup_main(["status", "--dry-run", "--root", str(tmp_path)]) == int(
        ExitCode.CONTRACT_ERROR
    )


def test_flag_validation_rejects_wizard_json(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    assert setup_main(["wizard", "--json", "--root", str(tmp_path)]) == int(
        ExitCode.CONTRACT_ERROR
    )


# ---------------------------------------------------------------------------
# Readiness honesty regressions (§8.5, §10.4.3)
# ---------------------------------------------------------------------------


def test_ci_policy_not_enabled_is_attention(
    tmp_path: Path,
    base_install_find_spec: None,
) -> None:
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    snapshot = build_setup_snapshot(tmp_path)
    ci_policy = next(
        item for item in _capability_rows(snapshot) if item["id"] == "ci_policy"
    )
    assert ci_policy["configuration"] == "unconfigured"
    assert ci_policy["readiness"] == "attention"


def test_semantic_without_store_is_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.setup.engine import discover as discover_mod

    monkeypatch.setattr(
        "codeclone.surfaces.cli.setup.engine.discover.check_capability",
        lambda name: type(
            "Status", (), {"available": name == "embed", "missing_packages": []}
        )(),
    )
    ctx = DiscoverContext(
        root_path=tmp_path,
        config={},
        config_error=None,
        has_codeclone_section=True,
        baseline_path=tmp_path / "codeclone.baseline.json",
        baseline_status=None,
        head_commit=None,
        install_extras={},
        mcp_installed=False,
        memory_report=None,
    )
    axes = discover_mod._probe_semantic_retrieval(ctx)
    # Packages present but no memory store to index -> unconfigured -> attention.
    assert axes.installation == "installed"
    assert axes.configuration == "unconfigured"
    assert derive_readiness(_capability_meta("semantic_retrieval"), axes) == "attention"


def test_governed_maturity_reachable_when_mcp_configured(
    tmp_path: Path,
) -> None:
    # Regression for the maturity.governed inversion: installing AND configuring
    # MCP must make controlled_change ready and governed True.
    if importlib.util.find_spec("mcp") is None:
        pytest.skip("mcp extra not installed in this environment")
    _write_minimal_pyproject(tmp_path / "pyproject.toml")
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    snapshot = build_setup_snapshot(tmp_path)
    controlled = next(
        item for item in _capability_rows(snapshot) if item["id"] == "controlled_change"
    )
    assert controlled["readiness"] == "ready"
    maturity = cast(dict[str, object], snapshot["maturity"])
    assert maturity["governed"] is True
