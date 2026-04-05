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

from ._json_io import (
    json_text as _json_text,
)
from ._json_io import (
    read_json_document as _read_json_document,
)
from ._json_io import (
    write_json_document_atomically as _write_json_document_atomically,
)


def as_str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def as_int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def as_object_list(value: object) -> list[object] | None:
    return value if isinstance(value, list) else None


def as_str_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return value


def canonical_json(data: object) -> str:
    return _json_text(data, sort_keys=True)


def sign_cache_payload(data: Mapping[str, object]) -> str:
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_cache_payload_signature(
    payload: Mapping[str, object],
    signature: str,
) -> bool:
    return hmac.compare_digest(signature, sign_cache_payload(payload))


def read_json_document(path: Path) -> object:
    return _read_json_document(path)


def write_json_document_atomically(path: Path, document: object) -> None:
    _write_json_document_atomically(path, document, sort_keys=True)
