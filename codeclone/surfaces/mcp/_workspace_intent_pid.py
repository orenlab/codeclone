# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Process liveness checks for workspace intent coordination (leaf module)."""

from __future__ import annotations

from ._workspace_intent_lifecycle import is_pid_alive as _lifecycle_is_pid_alive


def is_agent_pid_alive(pid: int) -> bool:
    return _lifecycle_is_pid_alive(pid)


__all__ = ["is_agent_pid_alive"]
