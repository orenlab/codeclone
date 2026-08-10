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


def sign_cache_payload(data: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json_bytes(data)).hexdigest()


def verify_cache_payload_signature(
    payload: Mapping[str, object],
    signature: str,
) -> bool:
    return hmac.compare_digest(signature, sign_cache_payload(payload))


def sign_cache_envelope(version: str, payload: Mapping[str, object]) -> str:
    """Sign the full trust envelope, binding the generation gate into scope.

    ``version`` is the top-level ``v`` mark the loader compares before it decodes
    anything. Folding it into an explicit two-key pre-image ``{v, payload}``
    means the digest changes when ``v`` changes: a migration, backup or
    edit-in-place that rewrites ``v`` without re-signing is refused
    (``INTEGRITY_FAILED``) instead of trusted as a payload it never signed under
    that mark. ``py``/``fp`` already live inside ``payload``; this closes the
    one remaining asymmetry, ``v`` itself.

    Cross-defect witness (Enacta review). This is ONE half of a coupled pair.
    The other half is the ``{11, 17}`` unit-row length tolerance in
    ``_wire_decode._decode_wire_unit`` (dead-by-gate; owned elsewhere, do not
    edit). The envelope-``v`` defect existed only as their product: an unsigned
    ``v`` lets a migration retag a stale-format payload to the running
    generation, and that tolerant decoder then silently accepts its old rows.
    Signing ``v`` is therefore NOT redundant strictness over the
    ``v == CACHE_VERSION`` gate in ``_load_and_validate``: the gate rejects a
    *wrong* ``v``; only this signature rejects a ``v`` *rewritten to match* while
    the payload stays old-format. Do not drop ``v`` from the signed scope while
    that decode tolerance survives, or the cross-defect reassembles.
    """

    return sign_cache_payload({"v": version, "payload": payload})


def verify_cache_envelope_signature(
    version: str,
    payload: Mapping[str, object],
    signature: str,
) -> bool:
    return hmac.compare_digest(signature, sign_cache_envelope(version, payload))


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
    "canonical_json",
    "canonical_json_bytes",
    "read_json_document",
    "sign_cache_envelope",
    "sign_cache_payload",
    "verify_cache_envelope_signature",
    "verify_cache_payload_signature",
    "write_json_document_atomically",
]
