# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from pathlib import Path

import orjson

from ..utils.json_io import read_json_document as _read_json_document
from ..utils.json_io import (
    write_json_document_atomically as _write_json_document_atomically,
)


def as_str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def as_int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return list(value)


def as_str_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, object] = {}
    for raw_key, item in value.items():
        if not isinstance(raw_key, str):
            return None
        result[raw_key] = item
    return result


def canonical_json(data: object) -> str:
    return _canonical_json_bytes(data).decode("utf-8")


def canonical_json_bytes(data: object) -> bytes:
    """Canonical serialization as bytes, for callers that only hash it.

    Reaching a hash through `canonical_json` costs a decode to `str` and an
    encode straight back, holding two extra full copies of the payload. That
    is ruinous for documents the size of a report.
    """

    return _canonical_json_bytes(data)


def cache_payload_checksum(data: Mapping[str, object]) -> str:
    """Integrity checksum of a canonical cache payload - NOT a signature.

    Threat model (owner ruling). Cache trust equals source trust: the cache
    lives beside the analyzed source under the same permissions, so anyone who
    can forge the cache can simply edit the source instead. A keyed/secret
    signature would buy nothing against a local adversary who already controls
    the input. This is a keyless SHA-256 checksum whose only job is INTEGRITY -
    catching accidental desync (migration, backup, partial write, cross-version
    skew) - and it makes no authenticity claim. Do NOT re-introduce a keyed
    signature here as a security control: it is not authentication and must not
    be described, named, or relied on as one.
    """

    return hashlib.sha256(_canonical_json_bytes(data)).hexdigest()


def verify_cache_payload_checksum(
    payload: Mapping[str, object],
    checksum: str,
) -> bool:
    return hmac.compare_digest(checksum, cache_payload_checksum(payload))


def cache_envelope_checksum(version: str, payload: Mapping[str, object]) -> str:
    """Integrity checksum over the full trust envelope, binding the gate.

    ``version`` is the top-level ``v`` mark the loader compares before it decodes
    anything. Folding it into an explicit two-key pre-image ``{v, payload}``
    means the checksum changes when ``v`` changes: a migration, backup or
    edit-in-place that rewrites ``v`` without re-checksumming is refused
    (``INTEGRITY_FAILED``) instead of trusted as a payload it never covered under
    that mark. ``py``/``fp`` already live inside ``payload``; this closes the one
    remaining asymmetry, ``v`` itself. Like ``cache_payload_checksum`` this is an
    integrity check, not authentication - see its threat-model note.

    Cross-defect witness (Enacta review). This was ONE half of a coupled pair.
    The other half -- the ``{11, 17}`` unit-row length tolerance in
    ``_wire_decode._decode_wire_unit`` -- was independently closed by Wave D,
    whose widened 18-column row decodes strictly (``valid_lengths={18}``), so no
    stale-format row is tolerated there any more. Binding ``v`` is still NOT
    redundant strictness over the ``v == CACHE_VERSION`` gate in
    ``_load_and_validate``: the gate rejects a *wrong* ``v`` and the strict
    decode rejects a *wrong-shape* payload, but only this checksum rejects a
    ``v`` *rewritten to match* the running generation while the payload is
    otherwise valid -- the migration/backup/edit-in-place desync neither of the
    other two can see. Keep ``v`` inside the checksummed scope.
    """

    return cache_payload_checksum({"v": version, "payload": payload})


def verify_cache_envelope_checksum(
    version: str,
    payload: Mapping[str, object],
    checksum: str,
) -> bool:
    return hmac.compare_digest(checksum, cache_envelope_checksum(version, payload))


def _canonical_json_bytes(data: object) -> bytes:
    return orjson.dumps(data, option=orjson.OPT_SORT_KEYS)


def read_json_document(path: Path, *, max_bytes: int | None = None) -> object:
    if max_bytes is None:
        return _read_json_document(path)
    return _read_json_document(path, max_bytes=max_bytes)


def write_json_document_atomically(path: Path, document: object) -> None:
    _write_json_document_atomically(path, document, sort_keys=True)


__all__ = [
    "as_int_or_none",
    "as_object_list",
    "as_str_dict",
    "as_str_or_none",
    "cache_envelope_checksum",
    "cache_payload_checksum",
    "canonical_json",
    "canonical_json_bytes",
    "read_json_document",
    "verify_cache_envelope_checksum",
    "verify_cache_payload_checksum",
    "write_json_document_atomically",
]
