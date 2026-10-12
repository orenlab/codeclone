# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Memory projection rebuild jobs: the detected CI wins over every setting.

The explicit enqueue (``memory jobs enqueue``, MCP
``enqueue_projection_rebuild``) and the automatic one after
``finish_controlled_change`` stop at the CI gate before policy or ``force``
is read, so no explicit setting lifts it. Each side of the gate is pinned:
in CI the call is skipped; outside CI it reaches the next step, which the
tests replace with a sentinel so nothing touches a memory store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.jobs import workflow
from codeclone.utils.ci import _CI_ENV_KEYS


class _PastTheCiGate(Exception):
    """Raised by the first step after the CI gate: the gate let the call in."""


@pytest.fixture
def ci_free(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in _CI_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def _past_the_gate(*_args: object, **_kwargs: object) -> object:
        raise _PastTheCiGate

    monkeypatch.setattr(workflow, "resolve_memory_config", _past_the_gate)
    return monkeypatch


@pytest.mark.parametrize("ci", ["true", "false"])
@pytest.mark.parametrize("force", [False, True])
def test_projection_enqueue_in_ci_is_skipped_even_when_forced(
    ci_free: pytest.MonkeyPatch, tmp_path: Path, ci: str, force: bool
) -> None:
    ci_free.setenv("CI", ci)
    payload = workflow.execute_enqueue_projection_rebuild(
        root_path=tmp_path, trigger="explicit", force=force
    )
    assert payload["status"] == "skipped"
    assert payload["reason"] == "ci_environment"


@pytest.mark.parametrize("force", [False, True])
def test_projection_enqueue_outside_ci_passes_the_gate(
    ci_free: pytest.MonkeyPatch, tmp_path: Path, force: bool
) -> None:
    with pytest.raises(_PastTheCiGate):
        workflow.execute_enqueue_projection_rebuild(
            root_path=tmp_path, trigger="explicit", force=force
        )


def test_automatic_projection_enqueue_in_ci_is_skipped(
    ci_free: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ci_free.setenv("CI", "true")
    assert workflow.maybe_auto_enqueue_projection_rebuild(root_path=tmp_path) is None


def test_automatic_projection_enqueue_outside_ci_passes_the_gate(
    ci_free: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(_PastTheCiGate):
        workflow.maybe_auto_enqueue_projection_rebuild(root_path=tmp_path)
