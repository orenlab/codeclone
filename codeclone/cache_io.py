# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


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
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_cache_payload(data: Mapping[str, object]) -> str:
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_cache_payload_signature(
    payload: Mapping[str, object],
    signature: str,
) -> bool:
    return hmac.compare_digest(signature, sign_cache_payload(payload))


def read_json_document(path: Path) -> object:
    return json.loads(path.read_text("utf-8"))


def write_json_document_atomically(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(document).encode("utf-8")
    fd_num, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd_num, "wb") as fd:
            fd.write(data)
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
