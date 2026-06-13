# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib

from ...contracts import CORPUS_REPRESENTATION_CONTRACT_VERSION


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_record_key(*, project_id: str, intent_id: str) -> str:
    return sha256_hex(f"{project_id}\n{intent_id}")


def representation_key(
    *,
    lane: str,
    representation_kind: str,
    representation_version: str,
    source_record_key_value: str,
) -> str:
    return sha256_hex(
        f"{lane}\n{representation_kind}\n{representation_version}\n"
        f"{source_record_key_value}"
    )


def snapshot_item_id(*, snapshot_id: str, representation_key_value: str) -> str:
    return sha256_hex(f"{snapshot_id}\n{representation_key_value}")


def representation_version_for_kind(representation_kind: str) -> str:
    return CORPUS_REPRESENTATION_CONTRACT_VERSION


def membership_digest(snapshot_item_ids: list[str]) -> str:
    ordered = sorted(snapshot_item_ids)
    return sha256_hex("\n".join(ordered))


__all__ = [
    "membership_digest",
    "representation_key",
    "representation_version_for_kind",
    "sha256_hex",
    "snapshot_item_id",
    "source_record_key",
]
