# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Reproducible calibration of the complexity-health reference permilles.

This is the normative measurement PROCEDURE the maintainer's Wave D ruling
requires: the health complexity tail references are a *generated calibration
artifact*, computed from a pinned reference distribution — never hand-chosen
numbers tuned until self-health looks nice.

It lives in the test tree, beside the pins that consume it: the shipping
package needs only the *materialized* permilles (in ``codeclone.contracts``,
read by ``codeclone.metrics.health``), so a package module carrying this
procedure would be production-dead by construction. Keeping the derivation
here — as the retired Y9-CFG calibration did — is the source of truth without
dead runtime code.

Measurement contract (fix every degree of freedom so the same input yields the
same calibration and the same digest):

- **Population.** Every production function and method of the reference
  repository, i.e. every unit the analyzer's own unit collector emits for a
  source file that is NOT under ``tests/`` or ``benchmarks/`` — module-level
  functions and class methods, nested local ``def`` s excluded, no clone floor
  (``min_loc = min_stmt = 1``). This is the identical population the retired
  Y9-CFG calibration used; only the metric changed.
- **Metric.** ``source_decision_complexity`` at
  ``COMPLEXITY_ALGORITHM_REVISION`` — authored source-level decisions, floored
  at 1 (the value the health scorer reads).
- **Reference snapshot.** The distribution measured under that contract at
  calibration time, pinned below as ``COMPLEXITY_REFERENCE_DISTRIBUTION`` (a
  ``(complexity, function_count)`` histogram) plus ``REFERENCE_POPULATION``.
  Regenerated with ``scripts``-free re-measurement over the reference tree; a
  fresh capture that differs is a NEW calibration and needs maintainer
  ratification, not a silent edit.
- **Permille algorithm.** ``round_half_up(count_above(band) * 1000 /
  population)`` — deterministic ROUND_HALF_UP, no banker's rounding.
- **Digest.** ``reference_digest()`` binds the revision, the population and the
  histogram, so a silent edit to any of them fails the procedure pin.

The permilles the scorer actually spends are materialized in
``codeclone.contracts`` (``HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE`` /
``HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE``); the pin in
``tests/test_complexity_calibration.py`` asserts they EQUAL this procedure's
output on the pinned distribution, so hand-editing a materialized permille to a
wrong value reds the pin.

Not architectural truth: these permilles measure *this repository's* current
authored-decision distribution, which carries real, un-waived structural debt
(see ``docs/internal/complexity-authored-decision-debt.md`` and gh #61). The
calibration makes the health scale honest for the source-decision metric; it
does not retire the debt.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from codeclone.contracts import (
    COMPLEXITY_ALGORITHM_REVISION,
    COMPLEXITY_RISK_LOW_MAX,
    COMPLEXITY_RISK_MEDIUM_MAX,
)

#: Human-readable statement of the population filter, kept beside the data it
#: describes so a re-measurement cannot silently change what "population" meant.
COMPLEXITY_REFERENCE_POPULATION_FILTER: Final = (
    "production function/method units (files outside tests/ and benchmarks/), "
    "nested local defs excluded, no clone floor (min_loc=min_stmt=1), scored by "
    "source_decision_complexity floored at 1"
)

#: The pinned reference distribution: source-decision complexity of every
#: production function of this repository, as ``(complexity, function_count)``
#: pairs sorted by complexity. Captured under the measurement contract above at
#: the Wave D option-A landing. Replacing it is a new calibration.
COMPLEXITY_REFERENCE_DISTRIBUTION: Final[tuple[tuple[int, int], ...]] = (
    (1, 1521), (2, 1029), (3, 820), (4, 547), (5, 431), (6, 239),
    (7, 231), (8, 135), (9, 103), (10, 61), (11, 73), (12, 45),
    (13, 34), (14, 32), (15, 20), (16, 12), (17, 15), (18, 13),
    (19, 13), (20, 8), (21, 8), (22, 9), (23, 5), (24, 9),
    (25, 2), (26, 4), (27, 2), (28, 5), (30, 2), (31, 2),
    (32, 3), (35, 1), (38, 1), (40, 2), (98, 1),
)  # fmt: skip

#: Recorded population, asserted equal to the histogram's total by the pin so a
#: histogram edit that changes the count cannot pass unnoticed.
REFERENCE_POPULATION: Final = 5438

#: Domain-separated digest input version; bump if the digest serialization
#: shape changes (it never carries a metric value).
_REFERENCE_DIGEST_DOMAIN: Final = b"codeclone.complexity_calibration.v1\x00"


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def reference_population() -> int:
    """Total function count of the pinned reference distribution."""

    return sum(count for _complexity, count in COMPLEXITY_REFERENCE_DISTRIBUTION)


def count_above(threshold: int) -> int:
    """Reference functions whose complexity is strictly greater than ``threshold``."""

    return sum(
        count
        for complexity, count in COMPLEXITY_REFERENCE_DISTRIBUTION
        if complexity > threshold
    )


def _permille(count: int, population: int) -> int:
    if population <= 0:
        return 0
    return _round_half_up(Decimal(count * 1000) / Decimal(population))


def elevated_reference_permille() -> int:
    """Permille share above ``COMPLEXITY_RISK_LOW_MAX`` (the >10 tail)."""

    return _permille(count_above(COMPLEXITY_RISK_LOW_MAX), reference_population())


def extreme_reference_permille() -> int:
    """Permille share above ``COMPLEXITY_RISK_MEDIUM_MAX`` (the >20 tail)."""

    return _permille(count_above(COMPLEXITY_RISK_MEDIUM_MAX), reference_population())


def reference_permilles() -> tuple[int, int]:
    """The generated ``(elevated, extreme)`` reference permilles."""

    return elevated_reference_permille(), extreme_reference_permille()


def reference_maximum() -> int:
    """Largest complexity in the reference distribution."""

    return max(complexity for complexity, _count in COMPLEXITY_REFERENCE_DISTRIBUTION)


def reference_digest() -> str:
    """Deterministic digest binding revision + population + histogram."""

    payload = "|".join(
        [
            f"rev={COMPLEXITY_ALGORITHM_REVISION}",
            f"pop={reference_population()}",
            COMPLEXITY_REFERENCE_POPULATION_FILTER,
            *(
                f"{complexity}:{count}"
                for complexity, count in sorted(COMPLEXITY_REFERENCE_DISTRIBUTION)
            ),
        ]
    )
    return hashlib.sha256(
        _REFERENCE_DIGEST_DOMAIN + payload.encode("utf-8")
    ).hexdigest()


def debt_distribution_snapshot() -> dict[str, int]:
    """Authored-decision debt aggregates for the in-repo debt receipt (gh #61)."""

    return {
        "population": reference_population(),
        "above_10": count_above(COMPLEXITY_RISK_LOW_MAX),
        "above_20": count_above(COMPLEXITY_RISK_MEDIUM_MAX),
        "above_30": count_above(30),
        "maximum": reference_maximum(),
    }
