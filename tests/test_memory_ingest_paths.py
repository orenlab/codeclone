# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import IngestConfig, resolve_memory_config
from codeclone.config.pyproject_loader import load_pyproject_config
from codeclone.memory.ingest.paths import (
    resolve_contract_constants_paths,
    resolve_document_link_paths,
    resolve_mcp_tool_contradiction_sources,
)


def test_resolve_contract_constants_paths_auto_discovers_from_registry(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "src" / "myapp" / "contracts" / "__init__.py"
    contracts.parent.mkdir(parents=True)
    contracts.write_text('FOO_VERSION = "1"\n', encoding="utf-8")
    registry = frozenset({"src/myapp/contracts/__init__.py"})
    paths = resolve_contract_constants_paths(
        root_path=tmp_path,
        registry_paths=registry,
        ingest=IngestConfig(),
    )
    assert paths == (contracts,)


def test_resolve_contract_constants_paths_uses_explicit_config(tmp_path: Path) -> None:
    explicit = tmp_path / "pkg" / "contracts" / "__init__.py"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("", encoding="utf-8")
    other = tmp_path / "other" / "contracts" / "__init__.py"
    other.parent.mkdir(parents=True)
    other.write_text("", encoding="utf-8")
    paths = resolve_contract_constants_paths(
        root_path=tmp_path,
        registry_paths=frozenset({"other/contracts/__init__.py"}),
        ingest=IngestConfig(contract_constants_paths=("pkg/contracts/__init__.py",)),
    )
    assert paths == (explicit,)


def test_resolve_document_link_paths_default_root_and_registry_docs(
    tmp_path: Path,
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Root\n", encoding="utf-8")
    doc = tmp_path / "docs" / "guide.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# Guide\n", encoding="utf-8")
    paths = resolve_document_link_paths(
        root_path=tmp_path,
        registry_paths=frozenset({"docs/guide.md", "src/main.py"}),
        ingest=IngestConfig(),
    )
    assert paths == (readme, doc)


def test_resolve_mcp_tool_contradiction_sources_requires_both_sides(
    tmp_path: Path,
) -> None:
    assert (
        resolve_mcp_tool_contradiction_sources(
            root_path=tmp_path,
            ingest=IngestConfig(),
        )
        is None
    )
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    doc = tmp_path / "doc.md"
    doc.write_text("tools", encoding="utf-8")
    sources = resolve_mcp_tool_contradiction_sources(
        root_path=tmp_path,
        ingest=IngestConfig(
            mcp_tool_schema_snapshot_path="snap.json",
            mcp_tool_count_doc_paths=("doc.md",),
        ),
    )
    assert sources == (snapshot, (doc,))


def test_load_pyproject_config_accepts_memory_ingest_nested_table(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        """
[tool.codeclone.memory.ingest]
contract_constants_paths = ["pkg/contracts/__init__.py"]
mcp_tool_schema_snapshot_path = "snap.json"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    loaded = load_pyproject_config(tmp_path)
    memory = loaded.get("memory")
    assert isinstance(memory, dict)
    ingest = memory.get("ingest")
    assert isinstance(ingest, dict)
    assert ingest["contract_constants_paths"] == ["pkg/contracts/__init__.py"]


def test_resolve_memory_config_rejects_unknown_ingest_key(tmp_path: Path) -> None:
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        """
[tool.codeclone.memory.ingest]
unknown_key = true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"Invalid tool\.codeclone\.memory\.ingest"):
        resolve_memory_config(tmp_path)


def test_resolvers_skip_missing_and_escaping_paths(tmp_path: Path) -> None:
    from codeclone.config.memory import IngestConfig
    from codeclone.memory.ingest.paths import (
        resolve_contract_constants_paths,
        resolve_document_link_paths,
        resolve_mcp_tool_contradiction_sources,
        resolve_mcp_tool_schema_snapshot_path,
    )

    root = tmp_path / "repo"
    root.mkdir()
    ingest = IngestConfig(
        contract_constants_paths=("missing/contracts.py",),
        document_link_paths=("../escape.md",),
        mcp_tool_schema_snapshot_path="missing-tools.json",
        mcp_tool_count_doc_paths=("missing-doc.md",),
    )
    assert (
        resolve_contract_constants_paths(
            root_path=root,
            registry_paths=frozenset(),
            ingest=ingest,
        )
        == ()
    )
    assert (
        resolve_document_link_paths(
            root_path=root,
            registry_paths=frozenset({"docs/book/01.md"}),
            ingest=ingest,
        )
        == ()
    )
    assert resolve_mcp_tool_schema_snapshot_path(root_path=root, ingest=ingest) is None
    assert resolve_mcp_tool_contradiction_sources(root_path=root, ingest=ingest) is None
