# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The envelope must not dress a diagnosed user error as an internal fault.

Measured 2026-09-01 on a real invocation: ``CODECLONE_OBSERVABILITY_PROFILE=1``
without the ``codeclone[perf]`` extra printed ``INTERNAL ERROR`` /
``Unexpected exception.``, offered a traceback for a condition the same
process had already diagnosed by name, and asked the user to open a bug
against CodeClone -- for a documented option set without its extra.

Both boundaries are pinned, apart, because each opposite error is its own
defect: a **diagnosed** condition renders as a contract error at exit 2 with
no bug-report line, and a genuinely **internal** one keeps the internal
envelope at exit 5.

The envelope reads the CLASS and not a list of exceptions, so what is pinned
here is the marker, not any one family: the classification of the individual
configuration families is pinned in their own rings
(``test_observability_config``, ``test_audit_diagnosed_error``), and
``test_cli_unit`` carries one real family end to end through this envelope.
"""

from __future__ import annotations

import pytest

import codeclone.surfaces.cli.workflow as cli
from codeclone import ui_messages as ui
from codeclone.contracts import ISSUES_URL
from codeclone.contracts.errors import DiagnosedUserError

from ._assertions import assert_contains_all, assert_contains_none

_INTERNAL_ONLY = (
    "INTERNAL ERROR:",
    "Unexpected exception.",
    "Re-run with --debug to include a traceback.",
    f"{ISSUES_URL}/new?template=bug_report.yml",
)

_MEASURED_DIAGNOSIS = (
    "observability profile=true requires the codeclone[perf] extra (psutil)."
)
_MEASURED_REMEDIATION = 'Run: pip install "codeclone[perf]"'


class _AFamilyOfDiagnosedErrors(DiagnosedUserError):
    """Stands for any family marked at its own definition."""


def _run_main_raising(
    exc: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[object, str]:
    def _boom() -> None:
        raise exc

    monkeypatch.setattr(cli, "_main_impl", _boom)
    with pytest.raises(SystemExit) as raised:
        cli.main()
    return raised.value.code, capsys.readouterr().out


def test_a_diagnosed_condition_is_reported_as_a_contract_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The measured invocation, asserted on the bytes the user reads."""

    code, out = _run_main_raising(
        _AFamilyOfDiagnosedErrors(
            _MEASURED_DIAGNOSIS, remediation=_MEASURED_REMEDIATION
        ),
        monkeypatch,
        capsys,
    )

    assert code == 2
    assert_contains_all(out, "CONTRACT ERROR:", _MEASURED_DIAGNOSIS)
    assert_contains_none(out, *_INTERNAL_ONLY)


def test_the_diagnosis_carries_the_step_that_fixes_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A next step that cannot help must not be printed; one that can, must."""

    _, out = _run_main_raising(
        _AFamilyOfDiagnosedErrors(
            _MEASURED_DIAGNOSIS, remediation=_MEASURED_REMEDIATION
        ),
        monkeypatch,
        capsys,
    )

    assert_contains_all(out, "Next steps:", _MEASURED_REMEDIATION)


def test_a_diagnosis_without_a_step_prints_no_next_steps_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run_main_raising(
        _AFamilyOfDiagnosedErrors("tool.codeclone.min_loc must be an integer"),
        monkeypatch,
        capsys,
    )

    assert code == 2
    assert_contains_all(
        out, "CONTRACT ERROR:", "tool.codeclone.min_loc must be an integer"
    )
    assert_contains_none(out, "Next steps:", *_INTERNAL_ONLY)


def test_a_genuinely_internal_fault_keeps_the_internal_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The opposite boundary: misrouting an internal fault is its own defect."""

    code, out = _run_main_raising(RuntimeError("boom"), monkeypatch, capsys)

    assert code == 5
    assert_contains_all(out, *_INTERNAL_ONLY, "Reason: RuntimeError: boom")
    assert_contains_none(out, "CONTRACT ERROR:")


def test_the_quoted_configuration_survives_markup_rendering() -> None:
    """The one message whose job is to name a key may not lose the key.

    ``[tool.codeclone]`` and ``codeclone[perf]`` are what these diagnoses
    quote, and they are exactly what Rich reads as a style tag and swallows.
    """

    rendered = ui.fmt_diagnosed_user_error(
        _AFamilyOfDiagnosedErrors(
            "set min_loc under [tool.codeclone] in pyproject.toml",
            remediation=_MEASURED_REMEDIATION,
        )
    )

    assert "\\[tool.codeclone]" in rendered
    assert '\\[perf]"' in rendered
    assert ui.strip_markup(rendered).count("[tool.codeclone]") == 1


def test_the_formatter_refuses_an_undiagnosed_error() -> None:
    """The renderer may not be handed something it cannot honestly frame."""

    with pytest.raises(TypeError):
        ui.fmt_diagnosed_user_error(RuntimeError("boom"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Steps are a list, and one of them carries a filesystem path
# ---------------------------------------------------------------------------
#
# This ring pins the envelope, not any one family: the observability family's
# steps -- and the interpreter path in them -- are pinned at their own raise
# site in ``test_observability_config``, which is where an r2 module may be
# imported from. What has to hold *here* is that whatever steps a family
# hands over arrive intact and separate.


def test_every_step_is_rendered_as_its_own_bullet() -> None:
    """Two ways out are two lines; a heading that reads "steps" must list them.

    The alternatives are not interchangeable -- installing into an environment
    the user may not own, versus not asking for the feature -- so folding them
    into one bullet would hide the one some users can actually take.
    """

    rendered = ui.strip_markup(
        ui.fmt_diagnosed_user_error(
            _AFamilyOfDiagnosedErrors(
                _MEASURED_DIAGNOSIS,
                remediation=("install the extra", "or unset the flag"),
            )
        )
    )

    bullets = [line for line in rendered.splitlines() if line.startswith("- ")]
    assert bullets == ["- install the extra", "- or unset the flag"]


def test_an_empty_step_never_becomes_an_empty_bullet() -> None:
    """A blank step is no step: the heading must not stand over a bare dash."""

    rendered = ui.strip_markup(
        ui.fmt_diagnosed_user_error(
            _AFamilyOfDiagnosedErrors(_MEASURED_DIAGNOSIS, remediation=("", "real"))
        )
    )

    assert [line for line in rendered.splitlines() if line.startswith("- ")] == [
        "- real"
    ]
