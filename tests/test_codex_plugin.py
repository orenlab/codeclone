from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_codex_plugin_manifest_is_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "codeclone"
    manifest = _load_json(plugin_root / ".codex-plugin" / "plugin.json")
    marketplace = _load_json(root / ".agents" / "plugins" / "marketplace.json")

    assert isinstance(manifest, dict)
    assert manifest["name"] == plugin_root.name
    assert manifest["name"] == "codeclone"
    assert manifest["version"] == "2.0.0-b6.0"
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
    assert (plugin_root / "assets" / "icon.png").is_file()
    assert (plugin_root / "assets" / "logo.png").is_file()
    prompts = interface["defaultPrompt"]
    assert isinstance(prompts, list)
    assert len(prompts) == 3
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
    skill_text = skill_path.read_text(encoding="utf-8")
    hotspot_skill_text = hotspot_skill_path.read_text(encoding="utf-8")
    manifest = _load_json(plugin_root / ".codex-plugin" / "plugin.json")
    assert isinstance(manifest, dict)

    for needle in (
        "name: codeclone-review",
        "conservative first pass",
        'help(topic="analysis_profile")',
        'help(topic="coverage")',
        'get_report_section(section="metrics")',
        "Use MCP tools only",
        "Do not fall back to CLI or local report files.",
    ):
        assert needle in skill_text

    for needle in (
        "name: codeclone-hotspots",
        'get_report_section(section="metrics")',
        'help(topic="coverage")',
        "Use MCP tools only",
        "Do not fall back to CLI or local report files.",
    ):
        assert needle in hotspot_skill_text

    assert "Use MCP tools only." in manifest["instructions"]
    assert 'get_report_section(section="metrics")' in manifest["instructions"]
    assert 'help(topic="coverage")' in manifest["instructions"]
    assert "never fall back to CLI, local report files" in manifest["instructions"]


def test_codex_plugin_readme_and_docs_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = root / "plugins" / "codeclone"
    readme_text = (plugin_root / "README.md").read_text(encoding="utf-8")

    assert "# CodeClone for Codex" in readme_text
    assert "codex mcp add codeclone -- codeclone-mcp --transport stdio" in readme_text
    assert "does not rewrite `~/.codex/config.toml`" in readme_text
    assert "The plugin prefers a workspace launcher first" in readme_text
    assert "the current Poetry environment launcher" in readme_text
    assert "without relying on `sh -lc`" in readme_text
    assert 'uv tool install --pre "codeclone[mcp]"' in readme_text

    assert (root / "docs" / "codex-plugin.md").is_file()
    assert (root / "docs" / "terms-of-use.md").is_file()
