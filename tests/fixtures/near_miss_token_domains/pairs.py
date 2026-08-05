# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Near-miss pairs that decide which token domain may claim them.

Every pair here differs from its twin by exactly the edits its ground-truth
case declares. The first pair is the reason the renamed token domain exists:
consistent receiver-attribute renames price as replaces under the y8 tokens,
pushing a true single insertion out of budget, while the renamed-canonical
tokens absorb the renames and leave the insertion as the only edit.
"""

from collections.abc import Iterable


class Account:
    current: bool
    invoices: int
    average_invoice: float
    reference: str


class Tenant:
    current: bool
    leases: int
    average_lease: float
    reference: str


class Parcel:
    routed: bool


class Wagon:
    routed: bool


class Dock:
    paused: bool
    crates: int
    reserve: int
    berth: str


class Yard:
    paused: bool
    wagons: int
    buffer: int
    gate: str


class Route:
    archived: bool
    label: str


class Track:
    filed: bool
    tag: str


def open_invoice_exposure(accounts: Iterable[Account]) -> tuple[float, list[str]]:
    exposure: float = 0
    flagged: list[str] = []
    for account in accounts:
        if not account.current:
            continue
        amount = account.invoices * account.average_invoice
        exposure += amount
        flagged.append(account.reference)
    if flagged:
        exposure = exposure / len(flagged)
    return round(exposure, 2), flagged


def open_lease_exposure(tenants: Iterable[Tenant]) -> tuple[float, list[str]]:
    exposure: float = 0
    flagged: list[str] = []
    for tenant in tenants:
        if not tenant.current:
            continue
        amount = tenant.leases * tenant.average_lease
        exposure += amount
        flagged.append(tenant.reference)
    if flagged:
        exposure = exposure / len(flagged)
    exposure = max(exposure, 0)
    return round(exposure, 2), flagged


def routed_parcel_count(parcels: Iterable[Parcel]) -> tuple[int, int]:
    routed = 0
    skipped = 0
    for parcel in parcels:
        if parcel.routed:
            routed += 1
        else:
            skipped += 1
    return routed, skipped


def routed_wagon_count(wagons: Iterable[Wagon]) -> tuple[int, int]:
    counted = 0
    missed = 0
    for wagon in wagons:
        if wagon.routed:
            counted += 1
        else:
            missed += 1
    counted = max(counted, 0)
    return counted, missed


def pending_dock_backlog(docks: Iterable[Dock]) -> tuple[int, list[str]]:
    backlog = 0
    held: list[str] = []
    for dock in docks:
        if dock.paused:
            continue
        load = dock.crates + dock.reserve
        backlog += load
        held.append(dock.berth)
    return backlog, held


def pending_yard_backlog(yards: Iterable[Yard]) -> tuple[int, list[str]]:
    backlog = 0
    held: list[str] = []
    for yard in yards:
        if yard.paused:
            continue
        load = yard.wagons + yard.buffer
        backlog += load
        held.append(yard.gate)
    backlog = max(backlog, 0)
    held = sorted(held)
    return backlog, held


def archived_route_flags(routes: Iterable[Route]) -> tuple[list[str], int]:
    flags: list[str] = []
    active = 0
    for route in routes:
        if route.archived:
            flags.append(route.label)
        else:
            active += 1
    return flags, active


def filed_track_flags(tracks: Iterable[Track]) -> tuple[list[str], int]:
    marks: list[str] = []
    pending = 0
    for track in tracks:
        if track.filed:
            marks.append(track.tag)
        else:
            pending += 1
    return marks, pending
