# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.config.pyproject_loader import ConfigValidationError


def _write_pyproject(root: Path, body: str) -> None:
    (root / "pyproject.toml").write_text(body, encoding="utf-8")


def test_semantic_defaults_when_table_absent(tmp_path: Path) -> None:
    semantic = resolve_memory_config(tmp_path).semantic
    assert semantic.enabled is False
    assert semantic.backend == "lancedb"
    assert semantic.embedding_provider == "diagnostic"
    assert semantic.dimension == 256
    assert semantic.max_results == 20
    assert semantic.index_audit is True
    # index_path is normalized to an absolute path under the repo root.
    assert semantic.index_path == str(
        tmp_path / ".cache/codeclone/memory/semantic_index.lance"
    )


def test_semantic_nested_table_parsed(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory.semantic]
enabled = true
embedding_provider = "local_model"
dimension = 384
max_results = 50
index_audit = false
""",
    )
    semantic = resolve_memory_config(tmp_path).semantic
    assert semantic.enabled is True
    assert semantic.embedding_provider == "local_model"
    assert semantic.dimension == 384
    assert semantic.max_results == 50
    assert semantic.index_audit is False


def test_semantic_fastembed_provider_defaults(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory.semantic]
enabled = true
embedding_provider = "fastembed"
""",
    )
    semantic = resolve_memory_config(tmp_path).semantic
    assert semantic.enabled is True
    assert semantic.embedding_provider == "fastembed"
    assert semantic.embedding_model == "BAAI/bge-small-en-v1.5"
    assert semantic.dimension == 384
    assert semantic.allow_model_download is False
    assert semantic.embedding_cache_dir == str(
        tmp_path / ".cache/codeclone/memory/fastembed"
    )


def test_semantic_fastembed_env_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_MEMORY_SEMANTIC_ENABLED", "true")
    monkeypatch.setenv("CODECLONE_MEMORY_SEMANTIC_EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setenv("CODECLONE_MEMORY_SEMANTIC_EMBEDDING_MODEL", "custom/model")
    monkeypatch.setenv("CODECLONE_MEMORY_SEMANTIC_ALLOW_MODEL_DOWNLOAD", "true")
    semantic = resolve_memory_config(tmp_path).semantic
    assert semantic.enabled is True
    assert semantic.embedding_provider == "fastembed"
    assert semantic.embedding_model == "custom/model"
    assert semantic.dimension == 384
    assert semantic.allow_model_download is True


def test_semantic_frozen_flat_memory_keys_still_work(tmp_path: Path) -> None:
    # The flat memory keys and the nested semantic sub-table coexist.
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory]
max_records = 5000

[tool.codeclone.memory.semantic]
enabled = true
""",
    )
    config = resolve_memory_config(tmp_path)
    assert config.max_records == 5000
    assert config.semantic.enabled is True


def test_memory_table_must_be_object(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone]
memory = 1
""",
    )
    with pytest.raises(ConfigValidationError, match="memory' must be object"):
        resolve_memory_config(tmp_path)


def test_semantic_rejects_unknown_key(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory.semantic]
bogus = 1
""",
    )
    with pytest.raises(ValueError, match=r"memory\.semantic"):
        resolve_memory_config(tmp_path)


def test_semantic_rejects_bad_provider(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory.semantic]
embedding_provider = "telepathy"
""",
    )
    with pytest.raises(ValueError, match="embedding_provider"):
        resolve_memory_config(tmp_path)


def test_semantic_rejects_nonpositive_dimension(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory.semantic]
dimension = 0
""",
    )
    with pytest.raises(ValueError, match="dimension"):
        resolve_memory_config(tmp_path)


def test_semantic_non_table_rejected_at_load(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory]
semantic = "nope"
""",
    )
    with pytest.raises(ConfigValidationError, match="must be object"):
        resolve_memory_config(tmp_path)


def test_semantic_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_MEMORY_SEMANTIC_ENABLED", "true")
    monkeypatch.setenv("CODECLONE_MEMORY_SEMANTIC_EMBEDDING_PROVIDER", "local_model")
    semantic = resolve_memory_config(tmp_path).semantic
    assert semantic.enabled is True
    assert semantic.embedding_provider == "local_model"


def test_semantic_env_override_invalid_value_fails_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODECLONE_MEMORY_SEMANTIC_ENABLED", "maybe")
    with pytest.raises(ValueError, match=r"memory\.semantic"):
        resolve_memory_config(tmp_path)


def test_memory_invalid_mcp_sync_policy(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory]
mcp_sync_policy = "eventually"
""",
    )
    with pytest.raises(ValueError, match="mcp_sync_policy"):
        resolve_memory_config(tmp_path)


def test_semantic_index_path_must_resolve_to_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import codeclone.config.memory as memory_config_mod
    from codeclone.config.pyproject_loader import normalize_path_config_value

    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.memory.semantic]
enabled = true
index_path = "semantic.lance"
""",
    )

    def _bad_index_path(
        *,
        key: str,
        value: object,
        root_path: Path,
        path_config_keys: frozenset[str] | set[str] = frozenset(),
    ) -> object:
        if key == "index_path":
            return 42
        return normalize_path_config_value(
            key=key,
            value=value,
            root_path=root_path,
            path_config_keys=path_config_keys,
        )

    monkeypatch.setattr(
        memory_config_mod, "normalize_path_config_value", _bad_index_path
    )
    with pytest.raises(TypeError, match="index_path must resolve to a string"):
        resolve_memory_config(tmp_path)


def test_format_semantic_error_fallback_when_validation_has_no_entries() -> None:
    from pydantic import ValidationError

    from codeclone.config.memory import _format_semantic_error

    exc = ValidationError.from_exception_data("SemanticConfig", [])
    assert (
        _format_semantic_error(exc)
        == "Invalid tool.codeclone.memory.semantic configuration"
    )


def test_format_semantic_error_includes_field_path() -> None:
    from pydantic import ValidationError

    from codeclone.config.memory import SemanticConfig, _format_semantic_error

    with pytest.raises(ValidationError) as exc_info:
        SemanticConfig.model_validate({"dimension": 0})
    message = _format_semantic_error(exc_info.value)
    assert "dimension" in message
    assert "greater than" in message.lower() or "greater_than" in message


def test_memory_int_rejects_non_integer_values() -> None:
    from codeclone.config.memory import _memory_int

    with pytest.raises(ValueError, match="max_records"):
        _memory_int("lots", key="max_records")
