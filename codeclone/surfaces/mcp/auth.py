# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""FastMCP bearer-token helpers for streamable HTTP transport."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl

MCP_AUTH_TOKEN_ENV = "CODECLONE_MCP_AUTH_TOKEN"
MCP_AUTH_SCOPE = "codeclone:mcp"
MIN_MCP_AUTH_TOKEN_LENGTH = 32


class MCPAuthConfigurationError(ValueError):
    """Raised when MCP HTTP auth is requested but misconfigured."""


class StaticBearerTokenVerifier:
    """FastMCP TokenVerifier backed by one local bearer token."""

    def __init__(self, token: str) -> None:
        self._token = validated_mcp_auth_token(token)

    # FastMCP calls TokenVerifier implementations dynamically.
    # codeclone: ignore[dead-code]
    async def verify_token(self, token: str) -> AccessToken | None:
        from mcp.server.auth.provider import AccessToken

        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(
            token=token,
            client_id="codeclone-local-http",
            scopes=[MCP_AUTH_SCOPE],
        )


def validated_mcp_auth_token(value: str | None) -> str:
    token = "" if value is None else value.strip()
    if len(token) < MIN_MCP_AUTH_TOKEN_LENGTH:
        raise MCPAuthConfigurationError(
            f"{MCP_AUTH_TOKEN_ENV} must be at least "
            f"{MIN_MCP_AUTH_TOKEN_LENGTH} characters for streamable-http."
        )
    return token


def build_http_auth_settings(*, host: str, port: int) -> AuthSettings:
    from mcp.server.auth.settings import AuthSettings

    base_url = _http_base_url(host=host, port=port)
    return AuthSettings(
        issuer_url=_validated_http_url(f"{base_url}/"),
        resource_server_url=_validated_http_url(f"{base_url}/mcp"),
        required_scopes=[MCP_AUTH_SCOPE],
    )


def _validated_http_url(value: str) -> AnyHttpUrl:
    from pydantic import AnyHttpUrl, TypeAdapter

    return TypeAdapter(AnyHttpUrl).validate_python(value)


def _http_base_url(*, host: str, port: int) -> str:
    cleaned = host.strip().strip("[]") or "127.0.0.1"
    display_host = f"[{cleaned}]" if ":" in cleaned else cleaned
    return f"http://{display_host}:{port}"


__all__ = [
    "MCP_AUTH_SCOPE",
    "MCP_AUTH_TOKEN_ENV",
    "MIN_MCP_AUTH_TOKEN_LENGTH",
    "MCPAuthConfigurationError",
    "StaticBearerTokenVerifier",
    "build_http_auth_settings",
    "validated_mcp_auth_token",
]
