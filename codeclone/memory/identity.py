# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from urllib.parse import quote

from .enums import MemoryRecordType, SubjectKind


def _encode_segment(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    return quote(normalized, safe="")


def make_identity_key(
    *,
    type: MemoryRecordType | str,
    subject_kind: SubjectKind | str,
    subject_key: str,
    discriminator: str,
) -> str:
    """Build a deterministic opaque identity key for idempotent upsert."""
    segments = (
        str(type).strip(),
        str(subject_kind).strip(),
        _encode_segment(subject_key),
        _encode_segment(discriminator),
    )
    if not all(segments):
        msg = "identity key segments must be non-empty"
        raise ValueError(msg)
    return ":".join(segments)


__all__ = ["make_identity_key"]
