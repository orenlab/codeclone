# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.pyproject_loader import (
    ConfigValidationError,
    load_pyproject_config,
)
from codeclone.config.pyproject_writer import (
    PyprojectWriterError,
    apply_tool_codeclone_updates,
    merge_tool_codeclone,
    read_pyproject_document,
    serialize_pyproject_document,
    validate_tool_codeclone_updates,
    write_pyproject_text_atomically,
)
from codeclone.utils.atomic_write import validate_atomic_target, write_text_atomically


def _write_pyproject(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_merge_creates_tool_codeclone_section(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml",
        '[project]\nname = "demo"\n',
    )

    result = merge_tool_codeclone(
        tmp_path,
        {"audit_enabled": True, "baseline": "codeclone.baseline.json"},
    )

    assert result.changed_keys == ("audit_enabled", "baseline")
    assert result.created_section is True
    assert result.dry_run is False
    config = load_pyproject_config(tmp_path)
    assert config["audit_enabled"] is True
    assert config["baseline"] == str(tmp_path / "codeclone.baseline.json")


def test_merge_preserves_comments_round_trip(tmp_path: Path) -> None:
    original = (
        "[project]\n"
        'name = "demo"\n\n'
        "# keep this comment\n"
        "[tool.codeclone]\n"
        'baseline = "codeclone.baseline.json"\n'
        "ci = false\n"
    )
    _write_pyproject(tmp_path / "pyproject.toml", original)

    merge_tool_codeclone(tmp_path, {"ci": True})

    written = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "# keep this comment" in written
    assert "ci = true" in written
    assert load_pyproject_config(tmp_path)["ci"] is True


def test_merge_idempotent_when_values_unchanged(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml",
        "[tool.codeclone]\naudit_enabled = true\n",
    )
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    result = merge_tool_codeclone(tmp_path, {"audit_enabled": True})

    assert result.changed_keys == ()
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before


def test_merge_dry_run_does_not_write(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml",
        "[tool.codeclone]\naudit_enabled = false\n",
    )
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    result = merge_tool_codeclone(
        tmp_path,
        {"audit_enabled": True},
        dry_run=True,
    )

    assert result.changed_keys == ("audit_enabled",)
    assert result.preview_text is not None
    assert "audit_enabled = true" in result.preview_text
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before


def test_merge_rejects_unknown_key(tmp_path: Path) -> None:
    _write_pyproject(tmp_path / "pyproject.toml", "[tool.codeclone]\n")

    with pytest.raises(PyprojectWriterError, match="Unknown key"):
        merge_tool_codeclone(tmp_path, {"not_a_real_key": True})


def test_merge_rejects_invalid_value(tmp_path: Path) -> None:
    _write_pyproject(tmp_path / "pyproject.toml", "[tool.codeclone]\n")

    with pytest.raises(PyprojectWriterError, match="expected int"):
        merge_tool_codeclone(tmp_path, {"min_loc": "not-an-int"})


def test_merge_rejects_nested_table_updates(tmp_path: Path) -> None:
    _write_pyproject(tmp_path / "pyproject.toml", "[tool.codeclone]\n")

    with pytest.raises(PyprojectWriterError, match=r"Nested tool\.codeclone"):
        merge_tool_codeclone(tmp_path, {"memory": {"enabled": True}})


def test_merge_rejects_missing_pyproject(tmp_path: Path) -> None:
    with pytest.raises(PyprojectWriterError, match="not found"):
        merge_tool_codeclone(tmp_path, {"audit_enabled": True})


def test_merge_rejects_symlinked_pyproject(tmp_path: Path) -> None:
    real_config = tmp_path / "actual.toml"
    _write_pyproject(real_config, "[tool.codeclone]\n")
    config_link = tmp_path / "pyproject.toml"
    try:
        config_link.symlink_to(real_config)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(ConfigValidationError, match="must not be a symlink"):
        merge_tool_codeclone(tmp_path, {"audit_enabled": True})


def test_read_and_serialize_round_trip(tmp_path: Path) -> None:
    original = (
        "[project]\n"
        'name = "demo"\n\n'
        "# header comment\n"
        "[tool.codeclone]\n"
        "audit_enabled = true\n"
    )
    _write_pyproject(tmp_path / "pyproject.toml", original)

    document = read_pyproject_document(tmp_path)
    reserialized = serialize_pyproject_document(document)

    assert "# header comment" in reserialized
    assert reserialized.endswith("\n")


def test_validate_tool_codeclone_updates_empty() -> None:
    assert validate_tool_codeclone_updates(root_path=Path("/tmp"), updates={}) == {}


def test_apply_tool_codeclone_updates_empty(tmp_path: Path) -> None:
    _write_pyproject(tmp_path / "pyproject.toml", "[tool.codeclone]\n")
    document = read_pyproject_document(tmp_path)
    assert apply_tool_codeclone_updates(document, {}) == ()


def test_serialize_pyproject_document_adds_trailing_newline(tmp_path: Path) -> None:
    _write_pyproject(tmp_path / "pyproject.toml", "[project]\nname = 'demo'")
    document = read_pyproject_document(tmp_path)
    assert serialize_pyproject_document(document).endswith("\n")


def test_merge_no_op_when_updates_match_current(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml",
        "[tool.codeclone]\naudit_enabled = true\n",
    )
    result = merge_tool_codeclone(tmp_path, {"audit_enabled": True})
    assert result.changed_keys == ()


def test_apply_tool_codeclone_updates_rejects_invalid_tool_table(
    tmp_path: Path,
) -> None:
    _write_pyproject(tmp_path / "pyproject.toml", 'tool = "not-a-table"\n')
    document = read_pyproject_document(tmp_path)
    with pytest.raises(PyprojectWriterError, match="tool' must be a table"):
        apply_tool_codeclone_updates(document, {"audit_enabled": True})


def test_apply_tool_codeclone_updates_rejects_invalid_codeclone_table(
    tmp_path: Path,
) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml",
        "[tool]\ncodeclone = 'not-a-table'\n",
    )
    document = read_pyproject_document(tmp_path)
    with pytest.raises(
        PyprojectWriterError,
        match=r"tool\.codeclone' must be a table",
    ):
        apply_tool_codeclone_updates(document, {"audit_enabled": True})


def test_write_pyproject_text_atomically_rejects_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.toml"
    real.write_text("[tool.codeclone]\n", encoding="utf-8")
    link = tmp_path / "pyproject.toml"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    with pytest.raises(PyprojectWriterError, match="symlink"):
        write_pyproject_text_atomically(link, "[tool.codeclone]\n")


def test_merge_rejects_written_payload_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pyproject(tmp_path / "pyproject.toml", "[tool.codeclone]\n")
    calls = {"count": 0}
    real_loader = load_pyproject_config

    def _loader(root: Path) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] > 1:
            raise ConfigValidationError("broken after write")
        return real_loader(root)

    monkeypatch.setattr(
        "codeclone.config.pyproject_writer.load_pyproject_config",
        _loader,
    )
    with pytest.raises(PyprojectWriterError, match="failed validation after merge"):
        merge_tool_codeclone(tmp_path, {"audit_enabled": True})


def test_apply_tool_codeclone_updates_skips_unchanged_key(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml", "[tool.codeclone]\naudit_enabled = true\n"
    )
    document = read_pyproject_document(tmp_path)
    assert apply_tool_codeclone_updates(document, {"audit_enabled": True}) == ()


def test_merge_empty_updates_is_noop(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml", "[tool.codeclone]\naudit_enabled = true\n"
    )
    result = merge_tool_codeclone(tmp_path, {})
    assert result.changed_keys == ()


def test_write_text_atomically_and_validate_target(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    write_text_atomically(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"

    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    with pytest.raises(OSError, match="symlink"):
        validate_atomic_target(link)

    parent_link = tmp_path / "parent-link"
    nested = parent_link / "nested.txt"
    try:
        parent_link.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")
    with pytest.raises(OSError, match="symlink directory"):
        validate_atomic_target(nested)


def test_write_text_atomically_cleans_up_temp_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "out.txt"

    def _boom(_src: object, _dst: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("codeclone.utils.atomic_write.os.replace", _boom)
    with pytest.raises(OSError, match="replace failed"):
        write_text_atomically(target, "hello\n")
    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []
