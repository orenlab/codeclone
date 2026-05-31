# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations


class MemoryError(RuntimeError):
    """Base error for engineering memory operations."""


class MemorySchemaError(MemoryError):
    """Raised for unsupported or corrupt engineering memory database schemas."""


class MemoryContractError(MemoryError):
    """Raised when memory record or config contracts are violated."""


class MemoryInitLockError(MemoryError):
    """Raised when the memory init advisory lock cannot be acquired."""


class MemoryCapacityError(MemoryContractError):
    """Raised when memory store capacity limits are exceeded."""


__all__ = [
    "MemoryCapacityError",
    "MemoryContractError",
    "MemoryError",
    "MemoryInitLockError",
    "MemorySchemaError",
]
