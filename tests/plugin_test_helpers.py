# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import re
from pathlib import Path


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(?P<body>.*?)\n---\n", text, re.DOTALL)
    assert match is not None
    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields


def assert_plugin_branding_assets(plugin_root: Path) -> None:
    assert (plugin_root / "assets" / "icon.png").is_file()
    assert (plugin_root / "assets" / "logo.png").is_file()


def assert_rules_always_apply(*field_maps: dict[str, str]) -> None:
    for fields in field_maps:
        assert fields["alwaysApply"] == "true"


def assert_cursor_change_control_rules(
    *,
    workflow_fields: dict[str, str],
    gate_fields: dict[str, str],
    python_fields: dict[str, str],
    workflow_text: str,
    gate_text: str,
    python_text: str,
) -> None:
    assert_rules_always_apply(workflow_fields, gate_fields)
    assert "HARD GATE" in gate_fields["description"]
    assert "CodeClone MCP integration rules" in workflow_fields["description"]
    assert python_fields["globs"] == "**/*.py"
    from tests.assertion_helpers import assert_all_contained

    assert_all_contained(
        workflow_text,
        "Use MCP tools only",
        "Do not fall back to CLI or local report files.",
        "change-control-gate",
    )
    assert_all_contained(
        gate_text,
        "start_controlled_change",
        "finish_controlled_change",
        "record_candidate",
        "BLOCKED",
    )
    assert "chat is ephemeral" in gate_text.lower()
    assert "Run CodeClone analysis before making structural changes." in python_text


def assert_codex_manifest_interface(
    interface: dict[str, object],
    *,
    plugin_root: Path,
) -> None:
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
    long_description = interface["longDescription"]
    short_description = interface["shortDescription"]
    assert isinstance(long_description, str)
    assert isinstance(short_description, str)
    assert "engineering-memory skills" in long_description
    assert (
        "Structural Change Controller for AI-assisted Python development"
        in short_description
    )
    assert_plugin_branding_assets(plugin_root)
    prompts = interface["defaultPrompt"]
    assert isinstance(prompts, list)
    assert len(prompts) == 4
    assert all(isinstance(prompt, str) and 0 < len(prompt) <= 128 for prompt in prompts)
