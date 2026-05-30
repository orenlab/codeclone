# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_contains_all(text: str, needles: tuple[str, ...]) -> None:
    for needle in needles:
        assert needle in text


def _codeclone_package_version(root: Path) -> str:
    for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("pyproject.toml version not found")


def test_codex_plugin_manifest_is_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "codeclone"
    manifest = _load_json(plugin_root / ".codex-plugin" / "plugin.json")
    marketplace = _load_json(root / ".agents" / "plugins" / "marketplace.json")
    package_version = _codeclone_package_version(root)

    assert isinstance(manifest, dict)
    assert manifest["name"] == plugin_root.name
    assert manifest["name"] == "codeclone"
    assert manifest["version"] == package_version
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["license"] == "MPL-2.0"
    assert manifest["homepage"] == "https://orenlab.github.io/codeclone/codex-plugin/"
    assert isinstance(marketplace, dict)
    assert marketplace["plugins"][0]["name"] == manifest["name"]

    interface = manifest["interface"]
    assert isinstance(interface, dict)
    assert {
        "displayName": interface["displayName"],
        "category": interface["category"],
        "websiteURL": interface["websiteURL"],
    } == {
        "displayName": "CodeClone",
        "category": "Developer Tools",
        "websiteURL": manifest["homepage"],
    }
    assert (
        interface["privacyPolicyURL"]
        == "https://orenlab.github.io/codeclone/privacy-policy/"
    )
    assert (
        interface["termsOfServiceURL"]
        == "https://orenlab.github.io/codeclone/terms-of-use/"
    )
    assert interface["composerIcon"] == "./assets/icon.png"
    assert interface["logo"] == "./assets/logo.png"
    assert "change-control skills" in interface["longDescription"]
    assert (plugin_root / "assets" / "icon.png").is_file()
    assert (plugin_root / "assets" / "logo.png").is_file()
    prompts = interface["defaultPrompt"]
    assert isinstance(prompts, list)
    assert len(prompts) == 4
    assert all(isinstance(prompt, str) and 0 < len(prompt) <= 128 for prompt in prompts)


def test_codex_plugin_marketplace_and_mcp_config_are_aligned() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "codeclone"
    marketplace = _load_json(root / ".agents" / "plugins" / "marketplace.json")
    mcp_config = _load_json(plugin_root / ".mcp.json")

    assert isinstance(marketplace, dict)
    assert marketplace["name"] == "orenlab-local"
    plugins = marketplace["plugins"]
    assert isinstance(plugins, list)
    assert plugins == [
        {
            "name": "codeclone",
            "source": {
                "source": "local",
                "path": "./plugins/codeclone",
            },
            "policy": {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            },
            "category": "Developer Tools",
        }
    ]

    assert isinstance(mcp_config, dict)
    server = mcp_config["mcpServers"]["codeclone"]
    assert server["command"] == "python3"
    assert server["args"] == ["./scripts/launch_mcp"]
    assert (plugin_root / "scripts" / "launch_mcp").is_file()
    assert (plugin_root / "scripts" / "launch_mcp.py").is_file()
    assert (root / "scripts" / "launch_mcp").is_file()


def test_codex_plugin_skill_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "codeclone"
    skill_path = plugin_root / "skills" / "codeclone-review" / "SKILL.md"
    hotspot_skill_path = plugin_root / "skills" / "codeclone-hotspots" / "SKILL.md"
    change_control_skill_path = (
        plugin_root / "skills" / "codeclone-change-control" / "SKILL.md"
    )
    skill_text = skill_path.read_text(encoding="utf-8")
    hotspot_skill_text = hotspot_skill_path.read_text(encoding="utf-8")
    change_control_skill_text = change_control_skill_path.read_text(encoding="utf-8")
    manifest = _load_json(plugin_root / ".codex-plugin" / "plugin.json")
    assert isinstance(manifest, dict)

    _assert_contains_all(
        skill_text,
        (
            "name: codeclone-review",
            "conservative first pass",
            'help(topic="analysis_profile")',
            'help(topic="coverage")',
            'get_report_section(section="metrics")',
            "Use MCP tools only",
            "Do not fall back to CLI or local report files.",
        ),
    )
    _assert_contains_all(
        hotspot_skill_text,
        (
            "name: codeclone-hotspots",
            'get_report_section(section="metrics")',
            'help(topic="coverage")',
            "Use MCP tools only",
            "Do not fall back to CLI or local report files.",
        ),
    )
    _assert_contains_all(
        change_control_skill_text,
        (
            "name: codeclone-change-control",
            "Mandatory before any repository file edit",
            "target Python repository",
            "Normal pipeline",
            "Tool tiers",
            "changed_files` XOR `diff_ref",
            "needs_analysis",
            "start_controlled_change",
            "finish_controlled_change",
            "Completion gate",
            "Advisory acceptance",
            "health_delta",
            "patch contract passed",
        ),
    )

    assert "Use MCP tools only." in manifest["instructions"]
    assert 'get_report_section(section="metrics")' in manifest["instructions"]
    assert 'help(topic="coverage")' in manifest["instructions"]
    assert "never fall back to CLI, local report files" in manifest["instructions"]
    assert "codeclone-change-control skill" in manifest["instructions"]
    assert "start_controlled_change" in manifest["instructions"]
    assert "finish_controlled_change" in manifest["instructions"]
    assert "structural_delta" in manifest["instructions"]


def test_codex_plugin_readme_and_docs_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "codeclone"
    readme_text = (plugin_root / "README.md").read_text(encoding="utf-8")

    assert "# CodeClone for Codex" in readme_text
    assert "marketplace add orenlab/codeclone-codex" in readme_text
    assert "codex mcp add codeclone -- codeclone-mcp --transport stdio" in readme_text
    assert "does not rewrite `~/.codex/config.toml`" in readme_text
    assert "prefers a workspace `.venv`" in readme_text
    assert "current Poetry environment" in readme_text
    assert "without relying on `sh -lc`" in readme_text
    assert 'uv tool install "codeclone[mcp]"' in readme_text
    assert "codeclone-change-control" in readme_text

    assert (root / "docs" / "codex-plugin.md").is_file()
    assert (root / "docs" / "terms-of-use.md").is_file()
