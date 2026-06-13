# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ...contracts import (
    INTENT_REPRESENTATION_DESCRIPTION,
    INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
)
from ..keys import sha256_hex
from ..normalizer import normalize_corpus_text


@dataclass(frozen=True, slots=True)
class IntentRepresentationInput:
    description: str
    intent_kind: str | None
    declared_path_families: Sequence[str]
    declared_constraints: Sequence[str]


def build_intent_description_v1(description: str) -> str:
    normalized = normalize_corpus_text(description)
    return normalized.text


def build_intent_description_with_frame_v1(payload: IntentRepresentationInput) -> str:
    normalized_description = normalize_corpus_text(payload.description)
    kind = (payload.intent_kind or "").strip()
    families = ", ".join(sorted(set(payload.declared_path_families)))
    constraints = "; ".join(sorted(set(payload.declared_constraints)))
    parts = [
        "DESCRIPTION:",
        normalized_description.text,
        "INTENT_KIND:",
        kind,
        "DECLARED_PATH_FAMILIES:",
        families,
        "DECLARED_CONSTRAINTS:",
        constraints,
    ]
    return "\n".join(parts)


def representation_digest(*, representation_kind: str, normalized_text: str) -> str:
    return sha256_hex(f"{representation_kind}\n{normalized_text}")


def build_representation_text(
    *,
    representation_kind: str,
    payload: IntentRepresentationInput,
) -> str:
    if representation_kind == INTENT_REPRESENTATION_DESCRIPTION:
        return build_intent_description_v1(payload.description)
    if representation_kind == INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME:
        return build_intent_description_with_frame_v1(payload)
    msg = f"unsupported representation kind: {representation_kind}"
    raise ValueError(msg)


def declared_path_families_from_patch_trail(
    patch_trail: Mapping[str, object] | None,
    *,
    limit: int = 12,
) -> tuple[str, ...]:
    if patch_trail is None:
        return ()
    declared = patch_trail.get("declared_files")
    if not isinstance(declared, list):
        return ()
    families: set[str] = set()
    for item in declared:
        if not isinstance(item, str):
            continue
        path = item.strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if not path:
            continue
        top = path.split("/", 1)[0]
        if top:
            families.add(top)
    return tuple(sorted(families)[:limit])


def declared_constraints_from_audit_payload(
    payload: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if payload is None:
        return ()
    constraints: list[str] = []
    for key in ("verification_profile", "dirty_scope_policy", "on_conflict"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            constraints.append(f"{key}={value.strip()}")
    scope = payload.get("scope")
    if isinstance(scope, Mapping):
        for scope_key in ("allowed_files", "allowed_related", "forbidden"):
            items = scope.get(scope_key)
            if isinstance(items, list) and items:
                constraints.append(f"scope.{scope_key}_count={len(items)}")
    return tuple(sorted(constraints))


__all__ = [
    "IntentRepresentationInput",
    "build_intent_description_v1",
    "build_intent_description_with_frame_v1",
    "build_representation_text",
    "declared_constraints_from_audit_payload",
    "declared_path_families_from_patch_trail",
    "representation_digest",
]
