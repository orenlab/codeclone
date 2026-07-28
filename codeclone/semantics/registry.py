# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Single validation authority for human-authored semantic owners."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final

from ..contracts import AUTHORITY_REGISTRY_VERSION
from ..models import AuthorityRegistry, AuthorityRegistryEntry

_ENTRY_KEYS: Final = frozenset(
    {
        "contract_id",
        "canonical_owner",
        "allowed_adapters",
        "forbidden_raw_inputs",
        "required_provenance",
    }
)
_CONTRACT_ID_RE: Final = re.compile(r"^[a-z][a-z0-9_.-]*/v[1-9][0-9]*$")
_SYMBOL_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$")


class AuthorityRegistryError(ValueError):
    """Raised when the authority registry is not canonical and reviewable."""


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AuthorityRegistryError(f"authority.{field} must be a non-empty string")
    return value


def _string_tuple(
    value: object,
    *,
    field: str,
    symbols: bool = False,
    required: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AuthorityRegistryError(f"authority.{field} must be a list[str]")
    rows = tuple(_string(item, field=field) for item in value)
    if required and not rows:
        raise AuthorityRegistryError(f"authority.{field} must not be empty")
    if rows != tuple(sorted(set(rows))):
        raise AuthorityRegistryError(
            f"authority.{field} must be sorted and duplicate-free"
        )
    if symbols and any(_SYMBOL_RE.fullmatch(item) is None for item in rows):
        raise AuthorityRegistryError(
            f"authority.{field} must contain module:symbol identities"
        )
    return rows


def _entry(value: object) -> AuthorityRegistryEntry:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise AuthorityRegistryError(
            "each tool.codeclone.authority item must be a table"
        )
    row: dict[str, object] = {
        key: item for key, item in value.items() if isinstance(key, str)
    }
    unknown = sorted(set(row) - _ENTRY_KEYS)
    missing = sorted(_ENTRY_KEYS - set(row))
    if unknown:
        raise AuthorityRegistryError(
            "unknown authority registry key(s): " + ", ".join(unknown)
        )
    if missing:
        raise AuthorityRegistryError(
            "missing authority registry key(s): " + ", ".join(missing)
        )
    contract_id = _string(row["contract_id"], field="contract_id")
    if _CONTRACT_ID_RE.fullmatch(contract_id) is None:
        raise AuthorityRegistryError(
            "authority.contract_id must use the <name>/v<positive-int> form"
        )
    canonical_owner = _string(row["canonical_owner"], field="canonical_owner")
    if _SYMBOL_RE.fullmatch(canonical_owner) is None:
        raise AuthorityRegistryError(
            "authority.canonical_owner must be a module:symbol identity"
        )
    allowed_adapters = _string_tuple(
        row["allowed_adapters"],
        field="allowed_adapters",
        symbols=True,
    )
    if canonical_owner in allowed_adapters:
        raise AuthorityRegistryError(
            "authority.allowed_adapters must not repeat canonical_owner"
        )
    return AuthorityRegistryEntry(
        contract_id=contract_id,
        canonical_owner=canonical_owner,
        allowed_adapters=allowed_adapters,
        forbidden_raw_inputs=_string_tuple(
            row["forbidden_raw_inputs"],
            field="forbidden_raw_inputs",
        ),
        required_provenance=_string_tuple(
            row["required_provenance"],
            field="required_provenance",
            required=True,
        ),
    )


def parse_authority_registry(value: object) -> AuthorityRegistry:
    """Validate and freeze the reviewed ``[[tool.codeclone.authority]]`` rows."""

    if isinstance(value, AuthorityRegistry):
        return value
    if value is None:
        rows: tuple[AuthorityRegistryEntry, ...] = ()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        rows = tuple(_entry(item) for item in value)
    else:
        raise AuthorityRegistryError(
            "tool.codeclone.authority must be an array of tables"
        )
    ordered = tuple(sorted(rows, key=lambda item: item.contract_id))
    if rows != ordered:
        raise AuthorityRegistryError(
            "tool.codeclone.authority entries must be sorted by contract_id"
        )
    contract_ids = tuple(item.contract_id for item in rows)
    owners = tuple(item.canonical_owner for item in rows)
    if len(contract_ids) != len(set(contract_ids)):
        raise AuthorityRegistryError("authority contract_id values must be unique")
    if len(owners) != len(set(owners)):
        raise AuthorityRegistryError("authority canonical_owner values must be unique")
    return AuthorityRegistry(version=AUTHORITY_REGISTRY_VERSION, entries=rows)


__all__ = [
    "AuthorityRegistryError",
    "parse_authority_registry",
]
