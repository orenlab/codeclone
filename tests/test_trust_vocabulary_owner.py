# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The shared trust words have one owner, and moving them changed no value.

``codeclone.contracts.trust_vocabulary`` now owns the lane-trust reasons and
the clone-baseline file statuses that several layers read (maintainer ruling
2026-10-26). These pins hold the move to its promise: every serialized word,
in the enum, in the canonical house and in a report document, is the word it
was before; and the scanner the architecture ratchet runs counts a status
vocabulary, never a sentence that happens to use the same word.
"""

from __future__ import annotations

import typing

import pytest

from codeclone.baseline.trust import BASELINE_UNTRUSTED_STATUSES, BaselineStatus
from codeclone.canonical import comparison_rows
from codeclone.contracts import trust_vocabulary as owner
from codeclone.models import LaneTrustReason
from tests._trust_vocabulary_scan import semantic_uses

#: The wire words as they were before the owner existed, spelled here on
#: purpose: a test of "unchanged" must not read the code it guards.
_LANE_TRUST_WIRE = (
    "algorithm_revision",
    "baseline_missing",
    "baseline_scope_id",
    "canonicalization_version",
    "compatible",
    "descriptor_version",
    "lane_digest_mismatch",
    "payload_schema",
    "payload_schema_outdated",
    "required_contract",
    "root_digest_mismatch",
    "root_unverified",
    "runtime_lane_unknown",
)
_BASELINE_STATUS_WIRE = {
    "OK": "ok",
    "MISSING": "missing",
    "TOO_LARGE": "too_large",
    "INVALID_JSON": "invalid_json",
    "INVALID_TYPE": "invalid_type",
    "MISSING_FIELDS": "missing_fields",
    "MISMATCH_SCHEMA_VERSION": "mismatch_schema_version",
    "MISMATCH_FINGERPRINT_VERSION": "mismatch_fingerprint_version",
    "MISMATCH_PYTHON_VERSION": "mismatch_python_version",
    "MISMATCH_SCOPE_ID": "mismatch_scope_id",
    "GENERATOR_MISMATCH": "generator_mismatch",
    "INTEGRITY_MISSING": "integrity_missing",
    "INTEGRITY_FAILED": "integrity_failed",
}


def test_the_baseline_status_enum_serializes_as_before() -> None:
    assert {status.name: status.value for status in BaselineStatus} == (
        _BASELINE_STATUS_WIRE
    )
    assert tuple(sorted(_BASELINE_STATUS_WIRE.values())) == owner.BASELINE_STATUSES


def test_the_lane_trust_reasons_are_the_words_they_were() -> None:
    assert owner.LANE_TRUST_REASONS == _LANE_TRUST_WIRE
    assert (owner.LANE_TRUST_COMPATIBLE, owner.LANE_TRUST_BASELINE_MISSING) == (
        "compatible",
        "baseline_missing",
    )
    assert owner.LANE_TRUST_ROOT_UNVERIFIED == "root_unverified"
    # The typing mirror a Literal has to spell, held to the owner.
    assert set(typing.get_args(LaneTrustReason)) == set(_LANE_TRUST_WIRE) - {
        "baseline_missing",
        "root_unverified",
    }


def test_the_canonical_house_reexports_the_owner_unchanged() -> None:
    """API names stay where readers import them; the objects are the owner's."""

    assert comparison_rows.LANE_TRUST_REASONS is owner.LANE_TRUST_REASONS
    assert comparison_rows.LANE_TRUST_COMPATIBLE is owner.LANE_TRUST_COMPATIBLE
    assert (
        comparison_rows.LANE_TRUST_BASELINE_MISSING is owner.LANE_TRUST_BASELINE_MISSING
    )
    assert comparison_rows.BASELINE_STATUSES is owner.BASELINE_STATUSES
    assert comparison_rows.BASELINE_STATUS_OK is owner.BASELINE_STATUS_OK


def test_the_not_refused_sets_are_derived_from_the_owned_words() -> None:
    assert (
        frozenset({owner.LANE_TRUST_COMPATIBLE, owner.LANE_TRUST_BASELINE_MISSING})
        == owner.LANE_TRUST_NOT_REFUSED
    )
    assert (
        frozenset({owner.BASELINE_STATUS_MISSING, owner.BASELINE_STATUS_OK})
        == owner.BASELINE_STATUS_NOT_REFUSED
    )
    # Every other file status is one the run found and refused.
    refused = {
        status
        for status in BaselineStatus
        if status.value not in owner.BASELINE_STATUS_NOT_REFUSED
    }
    assert refused == BASELINE_UNTRUSTED_STATUSES - {BaselineStatus.MISSING}


_WORDS = frozenset(owner.LANE_TRUST_REASONS) | frozenset(owner.BASELINE_STATUSES)


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ('KNOWN = frozenset({"compatible", "baseline_missing"})\n', "collection"),
        ('KNOWN = ("ok", "missing")\n', "collection"),
        ('Reason = Literal["compatible", "root_unverified"]\n', "literal"),
        (
            'class Status(str, Enum):\n    OK = "ok"\n    MISSING = "missing"\n',
            "class",
        ),
        (
            'def f(row):\n    return row.get("reason") == "baseline_missing"\n',
            "comparison",
        ),
        ('def f(lane):\n    return lane.reason != "compatible"\n', "comparison"),
        ('TRUSTED: Final = "compatible"\n', "constant"),
    ],
)
def test_the_scanner_counts_an_independent_vocabulary(source: str, kind: str) -> None:
    assert [found for _line, found in semantic_uses(source, _WORDS)] == [kind]


@pytest.mark.parametrize(
    "source",
    [
        'MESSAGE = "lane is compatible with the baseline_missing rule"\n',
        'def f(log):\n    log.info("compatible")\n',
        'def f():\n    return Row(reason="baseline_missing")\n',
        'def f(status):\n    return status == "ok"\n',
        'STATES = ("missing", "trusted", "untrusted")\n',
    ],
)
def test_the_scanner_ignores_a_message_or_a_single_value(source: str) -> None:
    assert semantic_uses(source, _WORDS) == []
