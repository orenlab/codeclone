# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Near-miss witness fixture: edit counting and the canonical witness law.

Every function here exists to pin one behavior of the near-miss tier's
sequence edit distance and its canonical evidence:

- ``order_total_value`` / ``order_total_value_clamped`` — the empirical
  ``PAIR-T3-01`` shape: identical bodies apart from local/parameter renames
  plus ONE inserted statement (``acc = max(acc, 0)``).
- ``order_total_value_clamped_sorted`` — the negative twin carrying TWO true
  insertions relative to ``order_total_value``; out of budget.
- ``shipment_mass_total`` / ``shipment_span_total`` — exactly one replaced
  statement (a different attribute read); within budget as a replace.
- ``discount_ratio`` / ``rebate_ratio`` — pure renames; the exact tier's
  business, never a near-miss pair.
- ``repeated_tail_pings`` / ``repeated_tail_pings_extra`` and
  ``repeated_head_audit`` / ``repeated_head_audit_extra`` — the ambiguity
  class: an insertion into a run of REPEATED IDENTICAL statement
  fingerprints, at the sequence tail and head. The verdict is unambiguous;
  the canonical witness law decides which run statement is reported.

Expected outcomes live in ``ground_truth.json`` — never inlined in tests.
"""

from collections.abc import Iterable


class Party:
    active: bool
    orders: int
    average_order: float
    identifier: str


class Parcel:
    grams: float
    height: float
    label: str


class Ping:
    flagged: bool
    weight: int


class Audit:
    valid: bool
    score: int


class Sale:
    discounted: bool
    amount: float


def order_total_value(items: Iterable[Party]) -> tuple[float, list[str]]:
    total: float = 0
    kept: list[str] = []
    for item in items:
        if not item.active:
            continue
        value = item.orders * item.average_order
        total += value
        kept.append(item.identifier)
    if kept:
        total = total / len(kept)
    return round(total, 2), kept


def order_total_value_clamped(records: Iterable[Party]) -> tuple[float, list[str]]:
    acc: float = 0
    chosen: list[str] = []
    for record in records:
        if not record.active:
            continue
        amount = record.orders * record.average_order
        acc += amount
        chosen.append(record.identifier)
    if chosen:
        acc = acc / len(chosen)
    acc = max(acc, 0)
    return round(acc, 2), chosen


def order_total_value_clamped_sorted(rows: Iterable[Party]) -> tuple[float, list[str]]:
    accum: float = 0
    taken: list[str] = []
    for entry in rows:
        if not entry.active:
            continue
        gain = entry.orders * entry.average_order
        accum += gain
        taken.append(entry.identifier)
    if taken:
        accum = accum / len(taken)
    accum = max(accum, 0)
    taken.sort()
    return round(accum, 2), taken


def shipment_mass_total(parcels: Iterable[Parcel]) -> tuple[float, list[str]]:
    mass: float = 0
    labels: list[str] = []
    for parcel in parcels:
        mass += parcel.grams
        labels.append(parcel.label)
    if labels:
        mass = mass / len(labels)
    return round(mass, 2), labels


def shipment_span_total(parcels: Iterable[Parcel]) -> tuple[float, list[str]]:
    size: float = 0
    tags: list[str] = []
    for parcel in parcels:
        size += parcel.height
        tags.append(parcel.label)
    if tags:
        size = size / len(tags)
    return round(size, 2), tags


def discount_ratio(entries: Iterable[Sale]) -> float:
    paid: float = 0
    seen: int = 0
    for entry in entries:
        if entry.discounted:
            paid += entry.amount
        seen += 1
    if seen:
        return paid / seen
    return 0.0


def rebate_ratio(rows: Iterable[Sale]) -> float:
    granted: float = 0
    counted: int = 0
    for row in rows:
        if row.discounted:
            granted += row.amount
        counted += 1
    if counted:
        return granted / counted
    return 0.0


def repeated_tail_pings(events: Iterable[Ping]) -> int:
    count = 0
    for event in events:
        if event.flagged:
            count += event.weight
    count += 1
    count += 1
    return count


def repeated_tail_pings_extra(items: Iterable[Ping]) -> int:
    total = 0
    for item in items:
        if item.flagged:
            total += item.weight
    total += 1
    total += 1
    total += 1
    return total


def repeated_head_audit(rows: Iterable[Audit]) -> int:
    checks = 0
    checks += 1
    checks += 1
    for row in rows:
        if row.valid:
            checks += row.score
    return checks


def repeated_head_audit_extra(cells: Iterable[Audit]) -> int:
    marks = 0
    marks += 1
    marks += 1
    marks += 1
    for cell in cells:
        if cell.valid:
            marks += cell.score
    return marks
