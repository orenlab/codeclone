# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import json
from pathlib import Path

from tests.plugin_test_helpers import load_json, parse_frontmatter


def test_claude_code_plugin_manifest_and_mcp_config() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "claude-code-codeclone"
    manifest = load_json(plugin_root / ".claude-plugin" / "plugin.json")
    mcp_config = load_json(plugin_root / ".mcp.json")

    assert isinstance(manifest, dict)
    assert isinstance(mcp_config, dict)
    assert manifest["name"] == "codeclone"
    assert manifest["license"] == "MPL-2.0"
    assert (
        manifest["homepage"]
        == "https://orenlab.github.io/codeclone/guide/integrations/claude-code/setup/"
    )
    assert manifest["repository"] == "https://github.com/orenlab/codeclone-claude-code"
    assert "version" not in manifest

    server = mcp_config["mcpServers"]["codeclone"]
    assert server == {
        "command": "python3",
        "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/launch_mcp.py"],
    }
    assert (plugin_root / "scripts" / "launch_mcp.py").is_file()


def test_claude_code_plugin_skills_match_shared_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    claude_skills = root / "plugins" / "claude-code-codeclone" / "skills"
    codex_skills = root / "plugins" / "codeclone" / "skills"

    for skill_name in (
        "codeclone-review",
        "codeclone-hotspots",
        "codeclone-change-control",
        "codeclone-engineering-memory",
    ):
        claude_text = (claude_skills / skill_name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        codex_text = (codex_skills / skill_name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        claude_frontmatter = parse_frontmatter(claude_text)
        codex_frontmatter = parse_frontmatter(codex_text)
        assert claude_frontmatter["name"] == codex_frontmatter["name"]
        if skill_name == "codeclone-review":
            assert "claude code" in claude_frontmatter["description"].lower()
            assert "codex" in codex_frontmatter["description"].lower()
            continue
        assert claude_frontmatter == codex_frontmatter


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
    assert "claude plugin marketplace add orenlab/codeclone-claude-code" in readme
    assert "claude plugin install codeclone@orenlab-codeclone" in readme
    assert 'uv tool install "codeclone[mcp]"' in readme

    assert (
        root / "docs" / "guide" / "integrations" / "claude-code" / "setup.md"
    ).is_file()
    assert (root / "docs" / "book" / "integrations" / "claude-code-plugin.md").is_file()
