# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import json
import re
from pathlib import Path


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(?P<body>.*?)\n---\n", text, re.DOTALL)
    assert match is not None
    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields


def test_cursor_plugin_json_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "cursor-codeclone"
    manifest = _load_json(plugin_root / ".cursor-plugin" / "plugin.json")

    assert isinstance(manifest, dict)
    assert manifest["name"] == "codeclone"
    assert manifest["version"] == "0.1.0"
    assert manifest["license"] == "MPL-2.0"
    assert manifest["rules"] == "rules/"
    assert manifest["skills"] == "skills/"
    assert manifest["mcpServers"] == "mcp.json"
    assert manifest["logo"] == "assets/logo.png"
    assert (plugin_root / "assets" / "logo.png").is_file()
    assert (plugin_root / "assets" / "icon.png").is_file()


def test_cursor_mcp_json_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "cursor-codeclone"
    mcp_config = _load_json(plugin_root / "mcp.json")

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

    workflow_fields = _frontmatter(workflow)
    python_fields = _frontmatter(python)
    assert workflow_fields["alwaysApply"] == "true"
    assert "CodeClone MCP integration rules" in workflow_fields["description"]
    assert python_fields["globs"] == "**/*.py"
    assert "Use MCP tools only" in workflow
    assert "Do not fall back to CLI or local report files." in workflow
    assert "Run CodeClone analysis before making structural changes." in python


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
        assert _frontmatter(cursor_text) == _frontmatter(codex_text)


def test_cursor_plugin_version_is_semver() -> None:
    """Plugin has its own version lifecycle, independent of pyproject."""
    root = Path(__file__).resolve().parents[1]
    manifest = _load_json(
        root / "plugins" / "cursor-codeclone" / ".cursor-plugin" / "plugin.json"
    )
    assert isinstance(manifest, dict)
    version = manifest["version"]
    assert isinstance(version, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"Plugin version must be semver (X.Y.Z), got: {version}"
    )
