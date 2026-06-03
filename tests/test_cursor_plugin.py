# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import re
from pathlib import Path

from tests.plugin_test_helpers import (
    assert_cursor_change_control_rules,
    assert_plugin_branding_assets,
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
    cursor_skills = root / "plugins" / "cursor-codeclone" / "skills"
    codex_skills = root / "plugins" / "codeclone" / "skills"

    for skill_name in (
        "codeclone-review",
        "codeclone-hotspots",
        "codeclone-change-control",
    ):
        cursor_text = (cursor_skills / skill_name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        codex_text = (codex_skills / skill_name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        cursor_frontmatter = parse_frontmatter(cursor_text)
        codex_frontmatter = parse_frontmatter(codex_text)
        if skill_name == "codeclone-review":
            assert cursor_frontmatter["name"] == codex_frontmatter["name"]
            assert "review" in cursor_frontmatter["description"].lower()
            assert "codex" in codex_frontmatter["description"].lower()
            continue
        assert cursor_frontmatter == codex_frontmatter


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
