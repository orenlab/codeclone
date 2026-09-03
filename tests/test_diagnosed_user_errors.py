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

import ast
from pathlib import Path

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


# ---------------------------------------------------------------------------
# The steps are read on one terminal and nowhere else
# ---------------------------------------------------------------------------
#
# The interpreter path is deliberately carried in ``remediation`` rather than
# in the message, *because* the message travels: into MCP responses, into
# logs, into a pasted bug report. That reasoning is only sound while
# ``remediation`` stays where it is read on the terminal of the person who
# owns that path, and until now nothing enforced it -- a second reader added
# in the internal envelope was measured passing all 305 tests of this ring
# untouched. A boundary that holds only because nobody has written the second
# reader yet is a report sentence, not a guarantee.
#
# Two guards, because neither sees what the other does. The first reads the
# source and catches a reader that does not print anything (the measured
# case); it cannot see an access through a computed attribute name. The
# second reads the rendered bytes and catches a leak however it was spelled;
# it cannot see a reader that holds the value without emitting it.

_REMEDIATION_FIELD = "remediation"

#: Named, not counted. ``len(readers) == 1`` would move the magic number into
#: the test, and a second legitimate reader would then be "fixed" by bumping
#: it. These are identities: an unexpected reader fails by name, and adding
#: one is a reviewed edit to this line rather than to an integer.
_REMEDIATION_OWNER = "codeclone/contracts/errors.py:DiagnosedUserError.__init__"
_REMEDIATION_RENDERER = "codeclone/ui_messages/formatters.py:fmt_diagnosed_user_error"


class _RemediationSites(ast.NodeVisitor):
    """Every place production source touches the field, by qualified name.

    Attribute syntax and the ``getattr`` family both count. The measured
    second reader used ``getattr(error, "remediation", ())``, which a grep
    for the dotted attribute does not match -- for this defect a textual
    search is blind by construction, so the inventory is built from the AST.
    """

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.sites: set[str] = set()

    def _where(self) -> str:
        return ".".join(self.scope) or "<module>"

    def _in_scope(self, name: str, node: ast.AST) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._in_scope(node.name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._in_scope(node.name, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._in_scope(node.name, node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == _REMEDIATION_FIELD:
            self.sites.add(self._where())
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in {
            "getattr",
            "setattr",
            "hasattr",
            "delattr",
        }:
            second = node.args[1] if len(node.args) > 1 else None
            if isinstance(second, ast.Constant) and second.value == _REMEDIATION_FIELD:
                self.sites.add(self._where())
        self.generic_visit(node)


def _remediation_sites() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    found: set[str] = set()
    for path in sorted((root / "codeclone").rglob("*.py")):
        visitor = _RemediationSites()
        visitor.visit(ast.parse(path.read_text("utf-8")))
        relative = path.relative_to(root).as_posix()
        found.update(f"{relative}:{where}" for where in visitor.sites)
    return found


def test_no_production_code_reads_the_steps_outside_the_diagnosed_renderer() -> None:
    """A second reader anywhere in ``codeclone/`` fails here, by name.

    Subtraction and not equality on purpose: this guard owns one direction
    only. Losing the legitimate reader is the opposite defect and reds in
    ``test_the_diagnosed_renderer_still_carries_the_steps_it_is_trusted_with``,
    so neither failure can be mistaken for the other.
    """

    unexpected = _remediation_sites() - {_REMEDIATION_OWNER, _REMEDIATION_RENDERER}

    assert unexpected == set(), (
        "DiagnosedUserError.remediation carries a local interpreter path and is "
        "read on the user's terminal only. New reader(s): "
        f"{sorted(unexpected)}. If one of these is genuinely allowed to see it, "
        "say so by name here and re-check that it cannot reach a public surface."
    )


def test_the_internal_envelope_renders_no_part_of_a_remediation() -> None:
    """However it was spelled, the step must not reach the bug-report envelope.

    ``fmt_internal_error`` frames a fault whose text a user is invited to
    paste into a public issue. The steps are the one field allowed to name a
    local filesystem path, so no part of them may appear here -- including
    when the clauses in ``main`` are reordered and a diagnosed error arrives
    at this renderer.
    """

    interpreter = "/opt/uv-tool/bin/python3"
    step = f'"{interpreter}" -m pip install "codeclone[perf]"'

    rendered = ui.strip_markup(
        ui.fmt_internal_error(
            _AFamilyOfDiagnosedErrors(_MEASURED_DIAGNOSIS, remediation=(step,))
        )
    )

    assert interpreter not in rendered
    assert step not in rendered


def test_the_diagnosed_renderer_still_carries_the_steps_it_is_trusted_with() -> None:
    """The opposite defect: a boundary satisfied by nobody reading the field.

    A guard that only forbids readers is passed most easily by deleting the
    legitimate one, which would silence the step the user needs. This is the
    control that makes that a failure instead of a fix.
    """

    interpreter = "/opt/uv-tool/bin/python3"
    step = f'"{interpreter}" -m pip install "codeclone[perf]"'

    rendered = ui.strip_markup(
        ui.fmt_diagnosed_user_error(
            _AFamilyOfDiagnosedErrors(_MEASURED_DIAGNOSIS, remediation=(step,))
        )
    )

    assert f"- {step}" in rendered
