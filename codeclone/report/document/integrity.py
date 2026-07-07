# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256

import orjson


def _canonical_integrity_payload(
    *,
    report_schema_version: str,
    meta: Mapping[str, object],
    inventory: Mapping[str, object],
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    canonical_meta = {
        str(key): value for key, value in meta.items() if str(key) != "runtime"
    }
    canonical_inventory = _canonical_inventory(inventory)

    def _strip_noncanonical(value: object) -> object:
        if isinstance(value, Mapping):
            return {
                str(key): _strip_noncanonical(item)
                for key, item in value.items()
                if str(key) != "display_facts"
            }
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return [_strip_noncanonical(item) for item in value]
        return value

    return {
        "report_schema_version": report_schema_version,
        "meta": canonical_meta,
        "inventory": canonical_inventory,
        "findings": _strip_noncanonical(findings),
        "metrics": metrics,
    }


def _canonical_inventory(inventory: Mapping[str, object]) -> dict[str, object]:
    """Return inventory facts without local cache execution provenance."""

    canonical: dict[str, object] = {}
    for key, value in inventory.items():
        key_text = str(key)
        if key_text == "cache":
            continue
        if key_text == "files" and isinstance(value, Mapping):
            canonical[key_text] = {
                str(file_key): file_value
                for file_key, file_value in value.items()
                if str(file_key)
                not in {
                    "analyzed",
                    "cached",
                    "source_io_skipped",
                }
            }
            continue
        canonical[key_text] = value
    return canonical


def _build_integrity_payload(
    *,
    report_schema_version: str,
    meta: Mapping[str, object],
    inventory: Mapping[str, object],
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    canonical_payload = _canonical_integrity_payload(
        report_schema_version=report_schema_version,
        meta=meta,
        inventory=inventory,
        findings=findings,
        metrics=metrics,
    )
    canonical_json = orjson.dumps(
        canonical_payload,
        option=orjson.OPT_SORT_KEYS,
    )
    payload_sha = sha256(canonical_json).hexdigest()
    return {
        "canonicalization": {
            "version": "2",
            "scope": "canonical_only",
            "sections": [
                "report_schema_version",
                "meta",
                "inventory",
                "findings",
                "metrics",
            ],
            "excluded": [
                "meta.runtime",
                "inventory.cache",
                "inventory.files.analyzed",
                "inventory.files.cached",
                "inventory.files.source_io_skipped",
                "findings.*.display_facts",
            ],
        },
        "digest": {
            "verified": True,
            "algorithm": "sha256",
            "value": payload_sha,
        },
    }
