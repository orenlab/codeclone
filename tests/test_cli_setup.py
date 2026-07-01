# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from codeclone.audit.events import EVENT_PATCH_VERIFIED, AuditEvent, repo_root_digest
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.setup.engine.capabilities import (
    CapabilityAxes,
    CapabilityMeta,
)
from codeclone.surfaces.cli.setup.engine.discover import build_setup_snapshot
from codeclone.surfaces.cli.setup.engine.rollup import derive_readiness
from codeclone.surfaces.cli.setup.main import setup_main
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


@pytest.fixture
def base_install_find_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    real_find_spec = importlib.util.find_spec

    def _fake_find_spec(name: str, package: object | None = None) -> object | None:
        if name in _OPTIONAL_MODULES:
            return None
        return real_find_spec(name, package)  # type: ignore[arg-type]

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    monkeypatch.setattr(
        "codeclone.analytics.capabilities._package_available",
        lambda _name: False,
    )


def _capability_rows(snapshot: dict[str, object]) -> list[dict[str, object]]:
    raw = snapshot.get("capabilities")
    assert isinstance(raw, list)
    return [item for item in raw if isinstance(item, dict)]


def _normalize_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    parsed = json.loads(json.dumps(snapshot))
    if not isinstance(parsed, dict):
        raise TypeError("expected dict snapshot")
    normalized: dict[str, object] = parsed
    normalized["root"] = "<ROOT>"
    normalized["head_commit"] = None
    runtime = normalized.get("runtime")
    if isinstance(runtime, dict):
        runtime["python_tag"] = "<PYTHON_TAG>"
        runtime["codeclone_version"] = "<VERSION>"
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
    first_caps = _capability_rows(first)
    second_caps = _capability_rows(second)
    assert first_caps == second_caps
    groups = [str(item["group"]) for item in first_caps]
    group_rank: dict[str, int] = {
        group: index for index, group in enumerate(GROUP_ORDER)
    }
    assert groups == sorted(groups, key=lambda group: group_rank[group])
    within_group_ids = [
        item["id"]
        for group in GROUP_ORDER
        for item in first_caps
        if item["group"] == group
    ]
    assert within_group_ids == sorted(
        within_group_ids,
        key=lambda cap_id: next(
            index for index, item in enumerate(first_caps) if item["id"] == cap_id
        ),
    )


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
    analysis = next(
        item for item in _capability_rows(snapshot) if item["id"] == "analysis"
    )
    assert analysis["configuration"] == "invalid"
    assert analysis["readiness"] == "blocked"


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


def test_audit_configured_is_attention_not_blocked(
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
    assert audit["readiness"] == "attention"
    assert str(audit["readiness"]) != "blocked"


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
