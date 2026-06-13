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
