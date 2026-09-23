# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

import codeclone.surfaces.mcp.server as mcp_server

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "mcp_registry"

# Body digests (trailing newlines stripped) of the schemas as published at
# https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json
# and https://glama.ai/mcp/schemas/server.json on 2026-09-23.
_PUBLISHED_SCHEMA_DIGESTS = {
    "server.schema.2025-12-11.json": (
        "f58692606964038e16334bf3da9b476b28d16b9980a66d3c2881ab93ef60c815"
    ),
    "glama.server.schema.json": (
        "7f652273293b658bcf9156646745c3aa9c42edcbd179ee126361e462814f1508"
    ),
}


def _json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _sequence(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _project() -> dict[str, object]:
    toml = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    pyproject: dict[str, object] = toml.loads(
        (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return _mapping(pyproject["project"])


def _schema_errors(document: dict[str, object], schema_name: str) -> list[str]:
    jsonschema = pytest.importorskip("jsonschema")
    schema = _json_object(_FIXTURES / schema_name)
    validator_class = jsonschema.Draft7Validator
    validator_class.check_schema(schema)
    validator = validator_class(schema, format_checker=validator_class.FORMAT_CHECKER)
    return sorted(
        f"{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in validator.iter_errors(document)
    )


def _server_package() -> dict[str, object]:
    packages = _sequence(_json_object(_REPO_ROOT / "server.json")["packages"])
    assert len(packages) == 1
    return _mapping(packages[0])


def test_registry_schema_fixtures_match_the_published_schemas() -> None:
    digests = {
        name: hashlib.sha256((_FIXTURES / name).read_bytes().rstrip(b"\n")).hexdigest()
        for name in sorted(_PUBLISHED_SCHEMA_DIGESTS)
    }

    assert digests == _PUBLISHED_SCHEMA_DIGESTS


def test_server_json_validates_against_the_declared_registry_schema() -> None:
    server = _json_object(_REPO_ROOT / "server.json")
    schema = _json_object(_FIXTURES / "server.schema.2025-12-11.json")

    assert server["$schema"] == schema["$id"]
    assert _schema_errors(server, "server.schema.2025-12-11.json") == []


def test_server_json_tracks_the_released_package() -> None:
    project = _project()
    server = _json_object(_REPO_ROOT / "server.json")
    package = _server_package()
    version = project["version"]

    assert server["name"] == "io.github.orenlab/codeclone"
    assert (server["version"], package["version"]) == (version, version)
    assert (package["registryType"], package["identifier"]) == (
        "pypi",
        project["name"],
    )
    assert _mapping(package["transport"]) == {"type": "stdio"}
    assert "registryBaseUrl" not in package
    assert "fileSha256" not in package


def _typed_arguments(items: object) -> list[tuple[object, object, object]]:
    return [
        (_mapping(item)["type"], _mapping(item).get("name"), _mapping(item)["value"])
        for item in _sequence(items)
    ]


def _client_argv(items: object) -> list[str]:
    # How an MCP client turns registry arguments into argv (VS Code
    # mcpManagementService.processArguments): a positional contributes its
    # value, a named argument its name followed by its value.
    argv: list[str] = []
    for item in _sequence(items):
        argument = _mapping(item)
        if argument["type"] == "named":
            argv.append(str(argument["name"]))
        if "value" in argument:
            argv.append(str(argument["value"]))
    return argv


def test_server_json_launches_the_mcp_flag_with_the_mcp_extra() -> None:
    project = _project()
    package = _server_package()

    assert package["runtimeHint"] == "uvx"
    assert _typed_arguments(package["runtimeArguments"]) == [
        ("named", "--with", f"{project['name']}[mcp]=={project['version']}"),
    ]
    assert _typed_arguments(package["packageArguments"]) == [
        ("positional", None, "--mcp"),
        ("named", "--transport", "stdio"),
    ]
    assert "mcp" in _mapping(project["optional-dependencies"])
    assert "codeclone-mcp" in _mapping(project["scripts"])


def test_server_json_client_command_reaches_the_mcp_server_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project()
    package = _server_package()
    tool = f"{package['identifier']}@{package['version']}"
    command = [
        *_client_argv(package["runtimeArguments"]),
        tool,
        *_client_argv(package["packageArguments"]),
    ]
    module_name, _, attribute = str(
        _mapping(project["scripts"])[str(package["identifier"])]
    ).partition(":")
    entry = getattr(importlib.import_module(module_name), attribute)
    received: list[object] = []

    def _server_main(argv: object = None) -> None:
        received.append(argv)

    monkeypatch.setattr(mcp_server, "main", _server_main)
    monkeypatch.setattr(
        sys, "argv", [str(package["identifier"]), *command[command.index(tool) + 1 :]]
    )
    try:
        entry()
    except SystemExit as exc:
        pytest.fail(f"the client command left the CLI with exit code {exc.code}")

    assert command == [
        "--with",
        f"{project['name']}[mcp]=={project['version']}",
        tool,
        "--mcp",
        "--transport",
        "stdio",
    ]
    assert received == [["--transport", "stdio"]]


@pytest.mark.parametrize(
    "readme",
    ["package_readme", "README.md"],
)
def test_readme_carries_the_registry_ownership_marker(readme: str) -> None:
    project = _project()
    if readme == "package_readme":
        readme_path = _REPO_ROOT / str(_mapping(project["readme"])["file"])
    else:
        readme_path = _REPO_ROOT / readme
    server_name = _json_object(_REPO_ROOT / "server.json")["name"]

    assert f"<!-- mcp-name: {server_name} -->" in (
        readme_path.read_text(encoding="utf-8").splitlines()
    )


def test_glama_json_names_the_repository_owner_as_maintainer() -> None:
    glama = _json_object(_REPO_ROOT / "glama.json")
    schema = _json_object(_FIXTURES / "glama.server.schema.json")
    repository_url = str(
        _mapping(_json_object(_REPO_ROOT / "server.json")["repository"])["url"]
    )
    owner = re.fullmatch(r"https://github\.com/([^/]+)/[^/]+", repository_url)

    assert glama["$schema"] == schema["$id"]
    assert _schema_errors(glama, "glama.server.schema.json") == []
    assert owner is not None
    assert glama["maintainers"] == [owner.group(1)]


def test_registry_publish_job_follows_the_pypi_release_only() -> None:
    yaml = importlib.import_module("yaml")
    workflow: object = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(
            encoding="utf-8"
        )
    )
    jobs = _mapping(_mapping(workflow)["jobs"])
    registry = _mapping(jobs["publish-registry"])
    environment = _mapping(registry["env"])
    commands = [
        str(_mapping(step)["run"])
        for step in _sequence(registry["steps"])
        if "run" in _mapping(step)
    ]
    publisher_calls = [
        match.group(1)
        for command in commands
        for match in re.finditer(r'mcp-publisher" (\w+)', command)
    ]

    assert registry["needs"] == "publish-pypi"
    assert registry["if"] == _mapping(jobs["publish-pypi"])["if"]
    assert "testpypi" not in str(registry["if"])
    assert _mapping(registry["permissions"]) == {
        "contents": "read",
        "id-token": "write",
    }
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(environment["MCP_PUBLISHER_VERSION"]))
    assert re.fullmatch(r"[0-9a-f]{64}", str(environment["MCP_PUBLISHER_SHA256"]))
    assert "sha256sum --check --strict" in commands[0]
    assert publisher_calls == ["validate", "login", "publish"]
    assert any("login github-oidc" in command for command in commands)
    assert "secrets." not in json.dumps(registry)
