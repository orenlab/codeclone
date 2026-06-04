# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Process liveness checks for workspace intent coordination (leaf module)."""

from __future__ import annotations

from ._workspace_intent_lifecycle import (
    PidLiveness,
)
from ._workspace_intent_lifecycle import (
    is_pid_alive as _lifecycle_is_pid_alive,
)
from ._workspace_intent_lifecycle import (
    pid_liveness as _lifecycle_pid_liveness,
)


def is_agent_pid_alive(pid: int) -> bool:
    return _lifecycle_is_pid_alive(pid)


_DEFAULT_IS_AGENT_PID_ALIVE = is_agent_pid_alive


def agent_pid_liveness(pid: int) -> PidLiveness:
    # Existing tests and downstream shims sometimes monkeypatch the legacy
    # boolean probe. Preserve that compatibility while production uses
    # tri-state liveness.
    if is_agent_pid_alive is not _DEFAULT_IS_AGENT_PID_ALIVE:
        return PidLiveness.ALIVE if is_agent_pid_alive(pid) else PidLiveness.DEAD
    return _lifecycle_pid_liveness(pid)


__all__ = ["agent_pid_liveness", "is_agent_pid_alive"]
