# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from ...cache.integrity import canonical_json

LEGACY_REGISTRY_VERSION: Final = "1"
REGISTRY_VERSION: Final = "2"
DEFAULT_TTL_SECONDS: Final = 3600
MIN_TTL_SECONDS: Final = 60
MAX_TTL_SECONDS: Final = 86400
DEFAULT_LEASE_SECONDS: Final = 300
MIN_LEASE_SECONDS: Final = 60
MAX_LEASE_SECONDS: Final = 600
_HEX_DIGEST_LENGTH: Final = 64
_SAFE_INTENT_ID_RE: Final = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class WorkspaceIntentRecord:
    intent_id: str
    agent_pid: int
    agent_start_epoch: int
    agent_label: str
    run_id: str
    declared_at_utc: str
    expires_at_utc: str
    ttl_seconds: int
    status: str
    intent: str
    scope: dict[str, object]
    scope_digest: str
    blast_radius_summary: dict[str, object]
    lease_renewed_at_utc: str
    lease_seconds: int
    report_digest: str

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "registry_version": REGISTRY_VERSION,
            "intent_id": self.intent_id,
            "agent_pid": self.agent_pid,
            "agent_start_epoch": self.agent_start_epoch,
            "agent_label": self.agent_label,
            "run_id": self.run_id,
            "declared_at_utc": self.declared_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status,
            "intent": self.intent,
            "scope": self.scope,
            "scope_digest": self.scope_digest,
            "blast_radius_summary": self.blast_radius_summary,
            "lease_renewed_at_utc": self.lease_renewed_at_utc,
            "lease_seconds": self.lease_seconds,
            "report_digest": self.report_digest,
        }


def compute_scope_digest(scope: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(scope)).encode("utf-8")).hexdigest()


def compute_intent_digest(data: Mapping[str, object]) -> str:
    digestable = {key: value for key, value in data.items() if key != "integrity"}
    return hashlib.sha256(canonical_json(digestable).encode("utf-8")).hexdigest()


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _is_hex_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != _HEX_DIGEST_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


def verify_intent_integrity(data: Mapping[str, object]) -> bool:
    integrity = _as_mapping(data.get("integrity"))
    stored = integrity.get("payload_sha256")
    if not _is_hex_digest(stored):
        return False
    expected = compute_intent_digest(data)
    return hmac.compare_digest(str(stored), expected)


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "LEGACY_REGISTRY_VERSION",
    "MAX_LEASE_SECONDS",
    "MAX_TTL_SECONDS",
    "MIN_LEASE_SECONDS",
    "MIN_TTL_SECONDS",
    "REGISTRY_VERSION",
    "WorkspaceIntentRecord",
    "compute_intent_digest",
    "compute_scope_digest",
    "verify_intent_integrity",
]
