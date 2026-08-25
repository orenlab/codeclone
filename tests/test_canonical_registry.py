# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""F1 discriminator ratification pins (ruling 2026-08-24 §1, night preflight).

The measured defect: the bare ``(FILE, qualname, dimension)`` key of the
future ``risk_observations`` family is blind to 4 real entity groups
(3 sets of ``@overload`` declarations and one property/setter pair, 9 lost
rows of 17 561 on the frozen corpus) — different declarations, one key.
The ratified resolution is a producer-native discriminator: the
declaration-site ``start_line``, by the product's own precedent
(``complexity.items`` keys ``(path, qualname, start_line)`` and is
12 285/12 285 unique on the same corpus).

FLAG for the maintainer (named fork, morning override): this makes the
declaration site part of an *identity* — unlike dependency occurrences,
where location is evidence and never key.
"""

from __future__ import annotations

import dataclasses

from codeclone.canonical.registry import (
    FACT_FAMILY_FIELDS,
    RISK_OBSERVATIONS_FAMILY,
    RISK_OBSERVATIONS_KEY,
)
from codeclone.models import IntegerObservation, Unit


def test_f1_key_is_the_ratified_declaration_site_key() -> None:
    """The exact ratified key — nothing dropped, nothing smuggled in.

    Dropping ``start_line`` reintroduces the measured 9-row collision;
    adding any further component (``end_line``, ``raw_hash``) would exceed
    the ratified complexity.items precedent. Both directions must red.
    """
    assert RISK_OBSERVATIONS_KEY == ("file", "qualname", "dimension", "start_line")


def test_f1_family_is_declared_but_not_yet_a_wire_family() -> None:
    """The ratification lands as a declaration only: a wire family without
    codec, store, and ingest support would be a partially-introduced family,
    which the night protocol forbids."""
    assert RISK_OBSERVATIONS_FAMILY == "risk_observations"
    assert RISK_OBSERVATIONS_FAMILY not in FACT_FAMILY_FIELDS


def test_f1_discriminator_source_claim_is_executed_not_narrated() -> None:
    """The registry declaration says the fact is producer-native and the
    projection is the lossy step. Execute that claim against the real types:
    ``Unit`` carries ``start_line``; ``IntegerObservation`` (the projection
    row of observations/projection.py) does not. If either side moves, the
    declaration's stated source is stale and this pin reds."""
    unit_fields = {field.name for field in dataclasses.fields(Unit)}
    observation_fields = {
        field.name for field in dataclasses.fields(IntegerObservation)
    }
    assert "start_line" in unit_fields
    assert "start_line" not in observation_fields
