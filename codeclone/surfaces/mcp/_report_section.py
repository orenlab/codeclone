# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Bounded projections for ``get_report_section`` list-shaped report slices."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Final

from ...domain.findings import FAMILY_CLONES, FAMILY_DEAD_CODE, FAMILY_STRUCTURAL
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ._session_shared import MCPServiceContractError
from .payloads import paginate

_REPORT_SECTION_MAX_LIMIT: Final = 200

_FINDINGS_SECTION_FAMILIES: Final = frozenset(
    {
        "clone",
        FAMILY_CLONES,
        FAMILY_STRUCTURAL,
        FAMILY_DEAD_CODE,
        "design",
    }
)

_FINDINGS_FAMILY_ALIASES: Final[dict[str, str]] = {
    "clone": FAMILY_CLONES,
}

_GroupCollector = Callable[[Mapping[str, object]], list[dict[str, object]]]


def normalize_findings_section_family(family: str | None) -> str | None:
    if family is None:
        return None
    return _FINDINGS_FAMILY_ALIASES.get(family, family)


def validate_findings_section_family(family: str) -> str:
    normalized = normalize_findings_section_family(family)
    if normalized not in _FINDINGS_SECTION_FAMILIES:
        raise MCPServiceContractError(
            "Invalid family for findings section. "
            "Use clone, structural, dead_code, or design."
        )
    return normalized


def _paginated_items_payload(
    *,
    items: Sequence[dict[str, object] | str],
    offset: int,
    limit: int,
) -> dict[str, object]:
    page = paginate(
        list(items),
        offset=offset,
        limit=limit,
        max_limit=_REPORT_SECTION_MAX_LIMIT,
    )
    return {
        "offset": page.offset,
        "limit": page.limit,
        "total": page.total,
        "returned": len(page.items),
        "has_more": page.next_offset is not None,
        "next_offset": page.next_offset,
        "items": page.items,
    }


def _clone_groups(groups_root: Mapping[str, object]) -> list[dict[str, object]]:
    clones = _as_mapping(groups_root.get(FAMILY_CLONES))
    items: list[dict[str, object]] = []
    for bucket in ("functions", "blocks", "segments"):
        items.extend(
            dict(_as_mapping(group)) for group in _as_sequence(clones.get(bucket))
        )
    items.sort(key=lambda group: str(group.get("id", "")))
    return items


def _nested_groups(
    groups_root: Mapping[str, object],
    family_key: str,
) -> list[dict[str, object]]:
    family_payload = _as_mapping(groups_root.get(family_key))
    return [
        dict(_as_mapping(group)) for group in _as_sequence(family_payload.get("groups"))
    ]


_GROUP_COLLECTORS: Final[dict[str, _GroupCollector]] = {
    FAMILY_CLONES: _clone_groups,
    FAMILY_STRUCTURAL: lambda root: _nested_groups(root, FAMILY_STRUCTURAL),
    FAMILY_DEAD_CODE: lambda root: _nested_groups(root, FAMILY_DEAD_CODE),
    "design": lambda root: _nested_groups(root, "design"),
}


def inventory_section_payload(
    inventory: Mapping[str, object],
    *,
    offset: int,
    limit: int,
) -> dict[str, object]:
    registry = _as_mapping(inventory.get("file_registry"))
    paths = [str(item) for item in _as_sequence(registry.get("items")) if str(item)]
    page_payload = _paginated_items_payload(items=paths, offset=offset, limit=limit)
    return {
        "files": dict(_as_mapping(inventory.get("files"))),
        "code": dict(_as_mapping(inventory.get("code"))),
        "file_registry": {
            "encoding": str(registry.get("encoding", "relative_path")),
            **page_payload,
        },
    }


def findings_section_payload(
    findings: Mapping[str, object],
    *,
    family: str | None,
    offset: int,
    limit: int,
) -> dict[str, object]:
    summary = dict(_as_mapping(findings.get("summary")))
    if family is None:
        return {
            "summary": summary,
            "_hint": (
                "Use family=clone|structural|dead_code|design with offset/limit "
                "to paginate finding groups. Prefer list_findings for filtered "
                "agent triage."
            ),
        }
    validated_family = validate_findings_section_family(family)
    collector = _GROUP_COLLECTORS[validated_family]
    groups_root = _as_mapping(findings.get("groups"))
    page_payload = _paginated_items_payload(
        items=collector(groups_root),
        offset=offset,
        limit=limit,
    )
    return {
        "summary": summary,
        "family": validated_family,
        **page_payload,
    }


def require_mapping_section(
    report_document: Mapping[str, object],
    *,
    section: str,
) -> Mapping[str, object]:
    payload = report_document.get(section)
    if not isinstance(payload, Mapping):
        raise MCPServiceContractError(
            f"Report section '{section}' is not available in this run."
        )
    return payload


__all__ = [
    "findings_section_payload",
    "inventory_section_payload",
    "normalize_findings_section_family",
    "require_mapping_section",
    "validate_findings_section_family",
]
