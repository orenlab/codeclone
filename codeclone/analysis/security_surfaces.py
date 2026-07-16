# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..models import (
    SecuritySurface,
    SecuritySurfaceCategory,
    SecuritySurfaceClassificationMode,
    SecuritySurfaceEvidenceKind,
    SecuritySurfaceLocationScope,
    SemanticEvent,
)

_SECURITY_PREFIX = "security."
_CATEGORIES: dict[str, SecuritySurfaceCategory] = {
    "archive_extraction": "archive_extraction",
    "crypto_transport": "crypto_transport",
    "database_boundary": "database_boundary",
    "deserialization": "deserialization",
    "dynamic_execution": "dynamic_execution",
    "dynamic_loading": "dynamic_loading",
    "filesystem_mutation": "filesystem_mutation",
    "identity_token": "identity_token",
    "network_boundary": "network_boundary",
    "process_boundary": "process_boundary",
}
_LOCATION_SCOPES: dict[str, SecuritySurfaceLocationScope] = {
    "module": "module",
    "class": "class",
    "callable": "callable",
}
_CLASSIFICATION_MODES: dict[str, SecuritySurfaceClassificationMode] = {
    "exact_builtin": "exact_builtin",
    "exact_call": "exact_call",
    "exact_import": "exact_import",
}
_EVIDENCE_KINDS: dict[str, SecuritySurfaceEvidenceKind] = {
    "builtin": "builtin",
    "call": "call",
    "import": "import",
}


def _security_fields(event: SemanticEvent) -> dict[str, str]:
    fields: dict[str, str] = {}
    for fact in event.inputs:
        if fact.kind != "const" or not fact.ref.startswith(_SECURITY_PREFIX):
            continue
        key, separator, value = fact.ref.partition("=")
        if separator:
            fields[key.removeprefix(_SECURITY_PREFIX)] = value
    return fields


def _category(value: str) -> SecuritySurfaceCategory:
    if value in _CATEGORIES:
        return _CATEGORIES[value]
    raise ValueError(f"unknown security surface category: {value}")


def _location_scope(value: str) -> SecuritySurfaceLocationScope:
    if value in _LOCATION_SCOPES:
        return _LOCATION_SCOPES[value]
    raise ValueError(f"unknown security surface location scope: {value}")


def _classification_mode(value: str) -> SecuritySurfaceClassificationMode:
    if value in _CLASSIFICATION_MODES:
        return _CLASSIFICATION_MODES[value]
    raise ValueError(f"unknown security surface classification mode: {value}")


def _evidence_kind(value: str) -> SecuritySurfaceEvidenceKind:
    if value in _EVIDENCE_KINDS:
        return _EVIDENCE_KINDS[value]
    raise ValueError(f"unknown security surface evidence kind: {value}")


def project_security_surfaces(
    events: tuple[SemanticEvent, ...],
) -> tuple[SecuritySurface, ...]:
    items: list[SecuritySurface] = []
    for event in events:
        if event.kind != "security_observation":
            continue
        fields = _security_fields(event)
        items.append(
            SecuritySurface(
                category=_category(fields["category"]),
                capability=fields["capability"],
                module=fields["module"],
                filepath=event.location[0],
                qualname=fields["qualname"],
                start_line=event.location[1],
                end_line=int(fields["end_line"]),
                location_scope=_location_scope(fields["location_scope"]),
                classification_mode=_classification_mode(fields["classification_mode"]),
                evidence_kind=_evidence_kind(fields["evidence_kind"]),
                evidence_symbol=event.subject,
            )
        )
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.category,
                item.capability,
                item.evidence_symbol,
                item.classification_mode,
            ),
        )
    )


__all__ = ["project_security_surfaces"]
