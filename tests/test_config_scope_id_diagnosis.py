# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""An invalid ``baseline_scope_id`` is diagnosed, not dumped.

Measured 2026-09-05 on a real invocation with
``baseline_scope_id = "not-a-uuid"`` in ``pyproject.toml``::

    CONTRACT ERROR
      Invalid value for tool.codeclone foundation configuration: 1 validation
      error for FoundationConfigInput
      baseline_scope_id
        Value error, baseline_scope_id must be a canonical UUID
        [type=value_error, input_value='not-a-uuid', input_type=str]
          For further information visit
          https://errors.pydantic.dev/2.13/v/value_error

The validator's own frame -- the model's class name, the ``[type=...]``
tail, and a link to a validation library's documentation -- was the whole
body of a typed contract refusal, and there was no step to take. The
*missing* scope id one field away already does this correctly: it names the
contract's own reason and hands over the exact line to paste. The invalid
one now owes the same.

Both halves of the defect are pinned, in two modules, because the phase-39S
boundary ratchet is shrink-only: this one reaches only the config ring and
holds what the OWNER produces. The reader's half -- that the step survives
the CLI surface and reaches a terminal -- is
``test_cli_unit::test_an_invalid_scope_id_reaches_the_terminal_with_its_step``,
behind an ``r4 -> r2`` test edge the allowlist already carries.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from codeclone.config.pyproject_loader import (
    ConfigValidationError,
    _apply_foundation_config_boundary,
    _rejected_foundation_fields,
    load_pyproject_config,
)

#: Fragments that only a validation library emits. None of them answers the
#: user's question, and the last one sends the reader to another project's
#: documentation for a rule this project owns.
_VALIDATOR_FRAME = (
    "errors.pydantic.dev",
    "[type=value_error",
    "input_value=",
    "input_type=",
    "validation error for",
    "FoundationConfigInput",
)

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _project(tmp_path: Path, scope_id: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "fixture"\n'
        'version = "0.0.0"\n'
        "\n"
        "[tool.codeclone]\n"
        f'baseline_scope_id = "{scope_id}"\n',
        encoding="utf-8",
    )
    return tmp_path


def test_the_refusal_states_the_contract_reason_and_not_the_validator_frame(
    tmp_path: Path,
) -> None:
    """The body is this project's rule, in this project's words."""

    with pytest.raises(ConfigValidationError) as raised:
        load_pyproject_config(_project(tmp_path, "not-a-uuid"))

    message = str(raised.value)
    assert "baseline_scope_id" in message
    assert "canonical UUID" in message
    assert "not-a-uuid" in message
    for fragment in _VALIDATOR_FRAME:
        assert fragment not in message, fragment


def test_the_refusal_carries_a_step_the_user_can_execute(tmp_path: Path) -> None:
    """A typed outcome without a procedure is half an answer.

    The step is the same shape the missing-key refusal already hands over: a
    line to paste, under a named table, in a named file -- with a UUID
    generated for this run rather than an instruction to invent one.
    """

    with pytest.raises(ConfigValidationError) as raised:
        load_pyproject_config(_project(tmp_path, "not-a-uuid"))

    steps = raised.value.remediation
    assert steps
    joined = "\n".join(steps)
    assert "baseline_scope_id = " in joined
    assert "[tool.codeclone]" in joined
    assert str(tmp_path / "pyproject.toml") in joined
    assert _UUID_RE.search(joined), joined


def test_a_generated_step_never_repeats_a_uuid_between_runs(tmp_path: Path) -> None:
    """``uuid4`` and never a name-derived id, for the reason the key exists.

    A deterministic suggestion would hand two checkouts one scope id and
    reproduce the very confusion ``baseline_scope_id`` prevents.
    """

    def _suggested() -> str:
        with pytest.raises(ConfigValidationError) as raised:
            load_pyproject_config(_project(tmp_path, "not-a-uuid"))
        found = _UUID_RE.search("\n".join(raised.value.remediation))
        assert found is not None
        return found.group(0)

    assert _suggested() != _suggested()


def test_a_canonical_uuid_is_still_accepted(tmp_path: Path) -> None:
    """The opposite boundary: the guard must not refuse a valid scope id."""

    config = load_pyproject_config(
        _project(tmp_path, "aa720ae7-1c78-4cc2-b3f9-de635e2d9ac9")
    )

    assert config["baseline_scope_id"] == "aa720ae7-1c78-4cc2-b3f9-de635e2d9ac9"


def test_a_sibling_foundation_failure_keeps_the_generic_refusal() -> None:
    """Only the diagnosed key is re-framed; its siblings are untouched.

    Called at the boundary and not through ``load_pyproject_config``, on
    purpose and after measuring: the key specs refuse a malformed
    ``source_roots`` one layer earlier, so a file-level probe never reaches
    this model at all and would have proved nothing about the routing. The
    routing is what is at stake -- widening the re-frame would print the
    scope-id procedure under a ``project_label`` failure, and a wrong
    instruction is worse than a generic one.
    """

    with pytest.raises(ConfigValidationError) as raised:
        _apply_foundation_config_boundary(
            {"project_label": 7}, config_path=Path("pyproject.toml")
        )

    assert "foundation configuration" in str(raised.value)
    assert raised.value.remediation == ()


def test_an_unattributable_refusal_falls_back_instead_of_guessing() -> None:
    """A refusal whose fields cannot be read blames no key.

    ``_apply_foundation_config_boundary`` catches ``ValueError``, which is
    wider than the validator's own error type, so the field reader must
    answer "I do not know" for anything that is not shaped like one -- and a
    guard no input can reach is theatre, so here is the input that reaches
    it.
    """

    assert (
        _rejected_foundation_fields(ValueError("not a validation error")) == frozenset()
    )
