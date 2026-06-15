# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import re
from pathlib import Path

from tests.plugin_test_helpers import (
    CODEX_CURSOR_SYNC_SKILL_NAMES,
    assert_cursor_change_control_rules,
    assert_plugin_branding_assets,
    assert_plugin_skills_match_codex,
    load_json,
    parse_frontmatter,
)


def test_cursor_plugin_json_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "cursor-codeclone"
    manifest = load_json(plugin_root / ".cursor-plugin" / "plugin.json")

    assert isinstance(manifest, dict)
    assert manifest["name"] == "codeclone"
    assert manifest["version"] == "0.1.0"
    assert manifest["license"] == "MPL-2.0"
    assert manifest["rules"] == "rules/"
    assert manifest["skills"] == "skills/"
    assert manifest["mcpServers"] == "mcp.json"
    assert manifest["logo"] == "assets/logo.png"
    assert_plugin_branding_assets(plugin_root)


def test_cursor_mcp_json_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "cursor-codeclone"
    mcp_config = load_json(plugin_root / "mcp.json")

    assert isinstance(mcp_config, dict)
    server = mcp_config["mcpServers"]["codeclone"]
    assert server == {
        "command": "python3",
        "args": ["./scripts/launch_mcp.py"],
    }
    assert (plugin_root / "scripts" / "launch_mcp.py").is_file()


def test_cursor_rules_have_valid_frontmatter() -> None:
    root = Path(__file__).resolve().parents[1]
    rules_root = root / "plugins" / "cursor-codeclone" / "rules"
    workflow = (rules_root / "codeclone-workflow.mdc").read_text(encoding="utf-8")
    python = (rules_root / "codeclone-python.mdc").read_text(encoding="utf-8")
    gate = (rules_root / "change-control-gate.mdc").read_text(encoding="utf-8")

    workflow_fields = parse_frontmatter(workflow)
    python_fields = parse_frontmatter(python)
    gate_fields = parse_frontmatter(gate)
    assert_cursor_change_control_rules(
        workflow_fields=workflow_fields,
        gate_fields=gate_fields,
        python_fields=python_fields,
        workflow_text=workflow,
        gate_text=gate,
        python_text=python,
    )


def test_cursor_skills_match_codex_skills() -> None:
    root = Path(__file__).resolve().parents[1]
    assert_plugin_skills_match_codex(
        plugin_skills_root=root / "plugins" / "cursor-codeclone" / "skills",
        codex_skills_root=root / "plugins" / "codeclone" / "skills",
        skill_names=CODEX_CURSOR_SYNC_SKILL_NAMES,
        review_platform_keyword="review",
    )


def test_cursor_plugin_version_is_semver() -> None:
    """Plugin has its own version lifecycle, independent of pyproject."""
    root = Path(__file__).resolve().parents[1]
    manifest = load_json(
        root / "plugins" / "cursor-codeclone" / ".cursor-plugin" / "plugin.json"
    )
    assert isinstance(manifest, dict)
    version = manifest["version"]
    assert isinstance(version, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"Plugin version must be semver (X.Y.Z), got: {version}"
    )


def test_cursor_readme_uses_marketplace_install_flow() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "plugins" / "cursor-codeclone" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "https://github.com/orenlab/codeclone-cursor" in readme
    assert "Import from Repo" in readme
    assert "development only" in readme.lower()
