# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Literal

AnalyticsCapability = Literal["base", "embed", "cluster", "full"]


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    available: bool
    missing_packages: tuple[str, ...]


def _package_available(name: str) -> bool:
    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


def check_capability(capability: AnalyticsCapability) -> CapabilityStatus:
    if capability == "base":
        return CapabilityStatus(available=True, missing_packages=())
    missing: list[str] = []
    if capability in {"embed", "full"}:
        missing.extend(
            package
            for package in ("fastembed", "lancedb")
            if not _package_available(package)
        )
    if capability in {"cluster", "full"}:
        missing.extend(
            package
            for package in ("sklearn", "hdbscan")
            if not _package_available(package)
        )
    return CapabilityStatus(
        available=not missing,
        missing_packages=tuple(sorted(set(missing))),
    )


def install_hint(missing_packages: tuple[str, ...]) -> str:
    if not missing_packages:
        return "uv sync --extra analytics"
    return "uv sync --extra analytics"


__all__ = [
    "AnalyticsCapability",
    "CapabilityStatus",
    "check_capability",
    "install_hint",
]
