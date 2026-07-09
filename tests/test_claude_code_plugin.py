# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.plugin_test_helpers import (
    CODEX_CLAUDE_SYNC_SKILL_NAMES,
    assert_claude_code_plugin_readme_contract,
    assert_plugin_manifest_version_license_homepage,
    assert_plugin_skills_match_codex,
    assert_repo_doc_paths_exist,
    codeclone_package_version,
    load_json,
    repo_docs_source_available,
)


def test_claude_code_plugin_manifest_and_mcp_config() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "claude-code-codeclone"
    manifest = load_json(plugin_root / ".claude-plugin" / "plugin.json")
    mcp_config = load_json(plugin_root / ".mcp.json")
    package_version = codeclone_package_version(root)

    assert isinstance(manifest, dict)
    assert isinstance(mcp_config, dict)
    assert manifest["name"] == "codeclone"
    assert_plugin_manifest_version_license_homepage(
        manifest,
        package_version=package_version,
        homepage="https://orenlab.github.io/codeclone/integrations/claude/",
    )
    assert manifest["repository"] == "https://github.com/orenlab/codeclone-claude-code"

    server = mcp_config["mcpServers"]["codeclone"]
    assert server == {
        "command": "python3",
        "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/launch_mcp.py"],
    }
    assert (plugin_root / "scripts" / "launch_mcp.py").is_file()


def test_claude_code_plugin_skills_match_shared_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    assert_plugin_skills_match_codex(
        plugin_skills_root=root / "plugins" / "claude-code-codeclone" / "skills",
        codex_skills_root=root / "plugins" / "codeclone" / "skills",
        skill_names=CODEX_CLAUDE_SYNC_SKILL_NAMES,
    )


def test_claude_code_marketplace_overlay_and_install_docs() -> None:
    root = Path(__file__).resolve().parents[1]
    marketplace = json.loads(
        (
            root / "scripts" / "integration_dist" / "marketplace.claude-code.json"
        ).read_text(encoding="utf-8")
    )
    readme = (root / "plugins" / "claude-code-codeclone" / "README.md").read_text(
        encoding="utf-8"
    )

    assert marketplace["name"] == "orenlab-codeclone"
    assert marketplace["metadata"]["description"]
    assert marketplace["plugins"][0]["source"] == "./plugins/codeclone"
    assert_claude_code_plugin_readme_contract(readme)
    if not repo_docs_source_available(root):
        pytest.skip("repo docs source tree is not present")
    assert_repo_doc_paths_exist(
        root,
        "docs/integrations/claude.md",
        "docs/guides/agent-safe-change.md",
    )
