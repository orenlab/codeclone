# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from codeclone.surfaces.mcp import server as mcp_server
from codeclone.surfaces.mcp.auth import (
    MCP_AUTH_SCOPE,
    MCP_AUTH_TOKEN_ENV,
    MCPAuthConfigurationError,
    StaticBearerTokenVerifier,
    build_http_auth_settings,
    validated_mcp_auth_token,
)


def test_static_bearer_token_verifier_uses_constant_time_contract() -> None:
    token = "t" * 32
    verifier = StaticBearerTokenVerifier(token)

    accepted = asyncio.run(verifier.verify_token(token))
    rejected = asyncio.run(verifier.verify_token("x" * 32))

    assert accepted is not None
    assert accepted.client_id == "codeclone-local-http"
    assert accepted.scopes == [MCP_AUTH_SCOPE]
    assert rejected is None


def test_mcp_http_token_validation_requires_minimum_length() -> None:
    with pytest.raises(MCPAuthConfigurationError, match=MCP_AUTH_TOKEN_ENV):
        validated_mcp_auth_token("short")
    assert validated_mcp_auth_token(f"  {'a' * 32}  ") == "a" * 32


def test_mcp_http_auth_settings_are_resource_server_scoped() -> None:
    settings = build_http_auth_settings(host="127.0.0.1", port=8123)

    assert str(settings.issuer_url) == "http://127.0.0.1:8123/"
    assert str(settings.resource_server_url) == "http://127.0.0.1:8123/mcp"
    assert settings.required_scopes == [MCP_AUTH_SCOPE]


def test_build_mcp_server_wires_fastmcp_token_verifier() -> None:
    server = mcp_server.build_mcp_server(auth_token="a" * 32)

    assert isinstance(server._token_verifier, StaticBearerTokenVerifier)
    assert server.settings.auth is not None
    assert server.settings.auth.required_scopes == [MCP_AUTH_SCOPE]


def test_mcp_main_requires_auth_token_for_streamable_http(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(MCP_AUTH_TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codeclone-mcp", "--transport", "streamable-http"],
    )

    with pytest.raises(SystemExit) as exc:
        mcp_server.main()

    assert exc.value.code == 2
    assert MCP_AUTH_TOKEN_ENV in capsys.readouterr().err


def test_mcp_main_passes_auth_token_to_http_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "b" * 32
    seen: dict[str, Any] = {}

    class _Server:
        def run(self, *, transport: str) -> None:
            seen["transport"] = transport

    def _build_mcp_server(**kwargs: object) -> _Server:
        seen.update(kwargs)
        return _Server()

    monkeypatch.setenv(MCP_AUTH_TOKEN_ENV, token)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codeclone-mcp", "--transport", "streamable-http"],
    )
    monkeypatch.setattr(mcp_server, "build_mcp_server", _build_mcp_server)

    mcp_server.main()

    assert seen["auth_token"] == token
    assert seen["transport"] == "streamable-http"
