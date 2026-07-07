# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.memory import enums as memory_enums


@pytest.mark.parametrize(
    ("validator", "field"),
    [
        (memory_enums.validate_memory_record_type, "record_type"),
        (memory_enums.validate_memory_status, "record_status"),
        (memory_enums.validate_memory_confidence, "record_confidence"),
        (memory_enums.validate_memory_origin, "record_origin"),
        (memory_enums.validate_memory_ingest_source, "record_ingest_source"),
        (memory_enums.validate_subject_kind, "subject_kind"),
        (memory_enums.validate_subject_relation, "subject_relation"),
        (memory_enums.validate_evidence_kind, "evidence_kind"),
        (memory_enums.validate_link_relation, "link_relation"),
        (memory_enums.validate_ingestion_mode, "ingestion_mode"),
        (memory_enums.validate_ingestion_run_status, "ingestion_run_status"),
    ],
)
def test_memory_enum_validators_reject_unknown_values(
    validator: object,
    field: str,
) -> None:
    with pytest.raises(ValueError, match=field):
        validator("not-a-valid-enum-value", field=field)  # type: ignore[operator]
