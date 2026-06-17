# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.analytics import resolve_analytics_config


def _write_pyproject(root: Path, body: str) -> None:
    (root / "pyproject.toml").write_text(body, encoding="utf-8")


def test_analytics_defaults_when_table_absent(tmp_path: Path) -> None:
    config = resolve_analytics_config(tmp_path)
    assert config.embedding_model == "BAAI/bge-small-en-v1.5"
    assert config.embedding_dimension == 384
    assert config.min_correlation_sample_size == 5
    assert config.default_min_cluster_size == 8
    assert config.allow_model_download is False
    assert config.db_path == tmp_path / ".codeclone/analytics/corpus_clustering.sqlite3"


def test_analytics_nested_table_parsed(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.analytics]
db_path = "custom/analytics.sqlite3"
default_min_cluster_size = 12
allow_model_download = true
""",
    )
    config = resolve_analytics_config(tmp_path)
    assert config.db_path == tmp_path / "custom/analytics.sqlite3"
    assert config.default_min_cluster_size == 12
    assert config.allow_model_download is True


def test_analytics_uses_configured_audit_path(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone]
audit_path = "evidence/controller.db"
""",
    )
    config = resolve_analytics_config(tmp_path)
    assert config.audit_db_path == tmp_path / "evidence/controller.db"


def test_analytics_unknown_key_rejected(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.analytics]
unexpected = true
""",
    )
    with pytest.raises(ValueError, match="unexpected"):
        resolve_analytics_config(tmp_path)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("embedding_provider", '"unsupported"'),
        ("default_cluster_selection_method", '"other"'),
    ],
)
def test_analytics_rejects_unsupported_runtime_choices(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    _write_pyproject(
        tmp_path,
        f"""
[tool.codeclone.analytics]
{key} = {value}
""",
    )
    with pytest.raises(ValueError, match=key):
        resolve_analytics_config(tmp_path)


def test_analytics_pyproject_validators_reject_empty_sweep_axes() -> None:
    from codeclone.config.analytics import AnalyticsPyprojectTable

    with pytest.raises(ValueError, match="positive integers"):
        AnalyticsPyprojectTable.model_validate({"sweep_pca_dimensions": ()})
    with pytest.raises(ValueError, match="positive integers"):
        AnalyticsPyprojectTable.model_validate({"sweep_min_cluster_sizes": [0, 8]})

    table = AnalyticsPyprojectTable.model_validate(
        {
            "sweep_pca_dimensions": [64, 32, 64],
            "sweep_selection_methods": ["leaf", "eom"],
        }
    )
    assert table.sweep_pca_dimensions == (32, 64)
    assert table.sweep_selection_methods == ("eom", "leaf")


def test_analytics_pyproject_validators_reject_blank_profile_fields() -> None:
    from codeclone.config.analytics import AnalyticsPyprojectTable

    with pytest.raises(ValueError, match="profile paths"):
        AnalyticsPyprojectTable.model_validate({"profile_paths": [" "]})
    with pytest.raises(ValueError, match="default_profile_id"):
        AnalyticsPyprojectTable.model_validate({"default_profile_id": "   "})


def test_analytics_pyproject_validators_reject_invalid_sweep_axes() -> None:
    from codeclone.config.analytics import AnalyticsPyprojectTable

    with pytest.raises(ValueError, match="positive integers"):
        AnalyticsPyprojectTable.model_validate({"sweep_pca_dimensions": [0]})
    with pytest.raises(ValueError, match="selection methods must not be empty"):
        AnalyticsPyprojectTable.model_validate({"sweep_selection_methods": []})
    with pytest.raises(ValueError, match="positive integers"):
        AnalyticsPyprojectTable.model_validate({"sweep_pca_dimensions": []})
    with pytest.raises(ValueError, match="default_profile_id must not be empty"):
        AnalyticsPyprojectTable.model_validate({"default_profile_id": "   "})


def test_analytics_pyproject_validators_accept_none_defaults() -> None:
    from codeclone.config.analytics import AnalyticsPyprojectTable

    table = AnalyticsPyprojectTable.model_validate({})
    assert table.sweep_pca_dimensions is None
    assert table.sweep_selection_methods is None
    assert table.default_profile_id is None


def test_analytics_pyproject_validators_return_none_for_explicit_nulls() -> None:
    from codeclone.config.analytics import AnalyticsPyprojectTable

    table = AnalyticsPyprojectTable.model_validate(
        {
            "sweep_pca_dimensions": None,
            "sweep_min_cluster_sizes": None,
            "sweep_min_samples": None,
            "sweep_selection_methods": None,
            "default_profile_id": None,
        }
    )
    assert table.sweep_pca_dimensions is None
    assert table.sweep_min_cluster_sizes is None
    assert table.sweep_min_samples is None
    assert table.sweep_selection_methods is None
    assert table.default_profile_id is None


def test_analytics_config_validates_profile_registry(tmp_path: Path) -> None:
    from codeclone.analytics.profiles.loader import (
        canonical_manifest_json,
        load_bundled_profiles,
    )

    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(canonical_manifest_json(profile), encoding="utf-8")
    _write_pyproject(
        tmp_path,
        """
[tool.codeclone.analytics]
default_profile_id = "intent-small-balanced-v1"
profile_paths = ["profile.json"]
""",
    )
    config = resolve_analytics_config(tmp_path)
    assert config.default_profile_id == "intent-small-balanced-v1"
    assert config.profile_paths == (profile_path,)


def test_observability_config_honors_explicit_false_env() -> None:
    from codeclone.config.observability import resolve_observability_config

    config = resolve_observability_config(
        environ={"CODECLONE_OBSERVABILITY_ENABLED": "false"}
    )
    assert config.enabled is False
