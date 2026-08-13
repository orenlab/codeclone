# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Sole bounded reader for stored and foreign canonical report-v3 documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeGuard

from ...contracts.compatibility import check_report_v3_compatibility
from ...models import (
    ReportDocumentV3Input,
    ReportReadFailure,
    ReportReadResult,
    ReportReadSuccess,
)
from ...utils.json_io import (
    DEFAULT_MAX_JSON_BYTES,
    BoundedReadError,
    read_bounded_bytes,
)
from .integrity import verify_report_integrity


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _is_document(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def read_report_document_v3(
    path: Path,
    *,
    limit_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> ReportReadResult:
    """Read, structurally validate, authenticate, and version-check one report."""

    try:
        raw = read_bounded_bytes(path, max_bytes=limit_bytes)
    except BoundedReadError as exc:
        return ReportReadFailure(reason="too_large", detail=str(exc))
    except OSError as exc:
        return ReportReadFailure(reason="unreadable", detail=str(exc))

    try:
        decoded = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError as exc:
        return ReportReadFailure(
            reason="duplicate_key",
            detail=f"duplicate JSON key: {exc}",
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return ReportReadFailure(reason="invalid_json", detail=str(exc))

    # Validate what the duplicate-key scan already decoded. Handing the raw
    # bytes to ``model_validate_json`` decoded this artifact a second time and
    # held a second full object graph alive at the process high-water mark, for
    # a document already measured at several times the reader's own byte limit.
    # The two paths are equivalent for this shape rather than equivalent by
    # hope: the model is strict, and the strict JSON and strict Python
    # validators differ only where a JSON scalar has to be coerced into a
    # narrower Python type -- there is no tuple field and no float field here
    # for them to disagree about.
    try:
        parsed = ReportDocumentV3Input.model_validate(decoded)
    except ValueError as exc:
        return ReportReadFailure(reason="invalid_shape", detail=str(exc))

    document = parsed.model_dump(mode="json")
    if not _is_document(document):
        return ReportReadFailure(
            reason="invalid_shape",
            detail="report document must be a JSON object",
        )

    compatibility = check_report_v3_compatibility(parsed.report_schema_version)
    if not compatibility.compatible:
        return ReportReadFailure(
            reason="incompatible_schema",
            detail=(f"report schema is incompatible: {parsed.report_schema_version!r}"),
        )
    integrity_error = verify_report_integrity(document)
    if integrity_error is not None:
        return ReportReadFailure(reason="invalid_shape", detail=integrity_error)
    return ReportReadSuccess(document=document)


__all__ = ["read_report_document_v3"]
