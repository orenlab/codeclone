# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Compatibility exports for surface-neutral workspace intent models."""

from __future__ import annotations

from ...workspace_intent.models import (
    IntentIntegrityModel,
    IntentScopeModel,
    WorkspaceIntentDocument,
    WorkspaceIntentRowModel,
    document_to_record_fields,
    parse_workspace_document,
    parse_workspace_document_json,
    record_from_document,
    signed_payload_dict_from_record,
    signed_payload_json_from_record,
    unsigned_document_payload,
)
from ...workspace_intent.models import (
    _validate_dirty_snapshot_payload as _validate_dirty_snapshot_payload,
)

__all__ = [
    "IntentIntegrityModel",
    "IntentScopeModel",
    "WorkspaceIntentDocument",
    "WorkspaceIntentRowModel",
    "document_to_record_fields",
    "parse_workspace_document",
    "parse_workspace_document_json",
    "record_from_document",
    "signed_payload_dict_from_record",
    "signed_payload_json_from_record",
    "unsigned_document_payload",
]
