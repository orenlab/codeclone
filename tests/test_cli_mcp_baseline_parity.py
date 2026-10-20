# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The CLI and MCP against one table of expected outcomes, never against
each other.

Two implementations that are wrong the same way agree with each other, so a
parity test that compares the surfaces is green over a defect they share
(``test_the_oracle_sees_what_a_surface_to_surface_comparison_cannot`` shows
it on the shared lane owner).  Every expectation below is derived from the
contracts, and each surface is held to it separately:

* trust -- a container of another ``baseline_scope_id`` describes nothing
  about this run whatever the gates read (``api.comparison.
  CONTEXT_INCOMPATIBLE_REASONS``): not loaded, ``mismatch_scope_id``, for the
  clone and the metrics lanes of the one file.  An absent file is
  ``missing``; a file that exists and fails its integrity check is
  ``integrity_failed`` for both lanes of the file -- never ``missing``;
* compatibility per lane -- a baseline without an API snapshot keeps every
  other metrics lane comparable; a gate that reads the missing lane is
  refused by the evaluator with ``lane:unavailable:api_surface`` and
  ``ExitCode.CONTRACT_ERROR`` (2), never by condemning the file;
* not compared -> null (ruling 2026-10-03): an opaque or untrusted clone lane
  states no novelty count; the patch verdict is ``UNVERIFIED`` with
  ``ExitCode.CONTRACT_ERROR``; a new clone on a compared lane is
  ``VIOLATED`` with ``ExitCode.GATING_FAILURE`` (3);
* both facts (ruling 2026-10-20 (13)) -- a proven violation beside a
  required check that did not run is ``VIOLATED`` *and* ``INCOMPLETE``, and
  exits with the contract-error code the gate itself returns for an
  unavailable lane before it evaluates any failure
  (``report.gates.evaluator._unavailable``): 2, never 3;
* the completeness of the reasons -- the ``Unverified lanes`` list is held
  entry for entry to the expected verdicts below, written from the
  contracts, not from either surface's answer;
* ``relaxed`` changes the sanction policy, never the completeness (ruling
  2026-10-20 (17)): one opaque clone lane beside a compared one is
  ``UNVERIFIED``, and a proven violation it lets pass still reads
  ``VIOLATED`` -- non-blocking, never "accepted";
* a population the gate refuses to answer over (``unmeasured``,
  ``complete_empty``) is a measurement the policy required and the run did
  not make: a ``Policy failures (missing measurement)`` line, ``INCOMPLETE``
  and exit 2 -- never a proven violation.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from codeclone.contracts import ExitCode
from codeclone.report.messages import gates as gate_msgs
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPGateRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.conftest import _run_codeclone_cli_exit
from tests.test_baseline_lane_degradation import retag_lane_descriptor

_OWN_SCOPE = "11111111-1111-4111-8111-111111111111"
_FOREIGN_SCOPE = "22222222-2222-4222-8222-222222222222"
#: One function body, cloned across ``pkg/m<i>.py``: two files hold one
#: function clone group.
_BODY = """
def {name}(items, factor):
    total = 0
    for item in items:
        if item > factor:
            total += item * factor
        else:
            total -= item
    result = total * 2
    result = result + len(items)
    print(result)
    return result
"""

_OK = (True, "ok")
_FOREIGN = (False, "mismatch_scope_id")
_MISSING = (False, "missing")
_CORRUPTED = (False, "integrity_failed")
_SUCCESS = int(ExitCode.SUCCESS)
_CONTRACT_ERROR = int(ExitCode.CONTRACT_ERROR)
_GATING_FAILURE = int(ExitCode.GATING_FAILURE)
_CLONE_LANES = ("lane:unavailable:clones.blocks", "lane:unavailable:clones.functions")
_API_LANE = ("lane:unavailable:api_surface",)


# -- the trees -------------------------------------------------------------------


def _set_scope(root: Path, scope: str) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "parity"\nversion = "0"\n\n[tool.codeclone]\n'
        f'baseline_scope_id = "{scope}"\n',
        "utf-8",
    )


def _project(root: Path, *, clone_files: int) -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text('"""pkg."""\n', "utf-8")
    for index in range(clone_files):
        (package / f"m{index}.py").write_text(
            _BODY.format(name=f"work_{index}"), "utf-8"
        )
    (package / "util.py").write_text(
        "def helper(x: int) -> int:\n    return x + 1\n", "utf-8"
    )


def _cli(root: Path, *args: str) -> tuple[int, str]:
    """One in-process CLI run over ``root``: its exit code and its output."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = _run_codeclone_cli_exit(
            [str(root), "--no-progress", "--no-color", *args], {}
        )
    return int(code or 0), out.getvalue()


def _baseline(root: Path) -> None:
    code, text = _cli(root, "--update-baseline")
    assert code == _SUCCESS, text


def _opaque_clone_lanes(path: Path) -> None:
    """Re-describe both clone lanes under another algorithm revision, the
    container re-authenticated: an authentic file another generation could
    have written, whose clone lanes this run cannot compare."""
    for lane in ("clones.functions", "clones.blocks"):
        retag_lane_descriptor(path, lane_name=lane, algorithm_revision="0-older")


def _own(root: Path) -> None:
    _project(root, clone_files=2)
    _set_scope(root, _OWN_SCOPE)
    _baseline(root)


def _foreign(root: Path) -> None:
    _own(root)
    _set_scope(root, _FOREIGN_SCOPE)


def _opaque(root: Path) -> None:
    _own(root)
    _opaque_clone_lanes(root / "codeclone.baseline.json")


def _new_clone(root: Path) -> None:
    _project(root, clone_files=1)
    _set_scope(root, _OWN_SCOPE)
    _baseline(root)
    _project(root, clone_files=3)


def _absent(root: Path) -> None:
    """The project of :func:`_own`, and no baseline file at all."""
    _project(root, clone_files=2)
    _set_scope(root, _OWN_SCOPE)


def _partially_opaque(root: Path) -> None:
    """The file of :func:`_own` with only its block-clone lane re-described:
    ``clones.functions`` compared, ``clones.blocks`` not."""
    _own(root)
    retag_lane_descriptor(
        root / "codeclone.baseline.json",
        lane_name="clones.blocks",
        algorithm_revision="0-older",
    )


def _emptied(root: Path) -> None:
    """The baseline of :func:`_own`, then every source file removed: a
    complete scan of an empty scope."""
    _own(root)
    for path in (root / "pkg").glob("*.py"):
        path.unlink()


def _unread(root: Path) -> None:
    """The baseline of :func:`_own`, then every source file unparsable:
    files found, none read."""
    _own(root)
    for path in (root / "pkg").glob("*.py"):
        path.write_text("def broken(:\n", "utf-8")


def _corrupted(root: Path) -> None:
    """The file of :func:`_own`, its root digest overwritten: a file that
    exists and fails its integrity check."""
    _own(root)
    path = root / "codeclone.baseline.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["meta"]["root_digest"]["value"] = "0" * 64
    path.write_text(json.dumps(payload), "utf-8")


# -- the oracle --------------------------------------------------------------------


class _Verdict(NamedTuple):
    """One patch verification, as the CLI must state it: the five labelled
    lines of ruling 2026-10-20 (13), the policy-failure line when a required
    measurement was not made (``None``: the CLI prints none), the closing
    sentence, and the process exit code."""

    verdict: str
    completeness: str
    exit_line: str
    proven_violations: str
    unverified_lanes: str
    policy_failures: str | None
    closing: str
    exit_code: int


def _listed(*items: str) -> str:
    return f"[{', '.join(items)}]"


_EXIT_ACCEPTED = "Exit: 0"
_EXIT_ADVISORY = "Exit: 0 (relaxed: violations are advisory)"
_EXIT_UNAVAILABLE = "Exit: 2 (required verification unavailable)"
_EXIT_VIOLATION = "Exit: 3 (proven violation)"
_ACCEPTED = "✔ Patch contract accepted."
_NOT_VERIFIED = "⚠ Patch contract not verified: a required check did not run."
_VIOLATED = "✗ Patch contract violated."
_VIOLATED_INCOMPLETE = "✗ Patch contract violated; the verification is incomplete."
_ADVISORY = "⚠ Patch contract has advisory violations but relaxed mode exits 0."
_POLICY_FAILURES = "Policy failures (missing measurement)"


def _accepted() -> _Verdict:
    return _Verdict(
        "Verdict: ACCEPTED",
        "Completeness: COMPLETE",
        _EXIT_ACCEPTED,
        "Proven violations: []",
        "Unverified lanes: []",
        None,
        _ACCEPTED,
        _SUCCESS,
    )


def _unverified(*lanes: str, policy: tuple[str, ...] = ()) -> _Verdict:
    return _Verdict(
        "Verdict: UNVERIFIED",
        "Completeness: INCOMPLETE",
        _EXIT_UNAVAILABLE,
        "Proven violations: []",
        f"Unverified lanes: {_listed(*lanes)}",
        f"{_POLICY_FAILURES}: {_listed(*policy)}" if policy else None,
        _NOT_VERIFIED,
        _CONTRACT_ERROR,
    )


def _violated(
    violations: tuple[str, ...],
    *lanes: str,
    exit_line: str,
    exit_code: int,
    closing: str,
) -> _Verdict:
    return _Verdict(
        "Verdict: VIOLATED",
        "Completeness: INCOMPLETE" if lanes else "Completeness: COMPLETE",
        exit_line,
        f"Proven violations: {_listed(*violations)}",
        f"Unverified lanes: {_listed(*lanes)}",
        None,
        closing,
        exit_code,
    )


# The reasons, each from its owner's vocabulary -- never from a surface's
# answer:
#
# * ``baseline:<status>`` -- the clone baseline status of the file
#   (``baseline.BaselineStatus``): another scope is ``mismatch_scope_id``, no
#   file ``missing``, a failed root digest ``integrity_failed``;
# * ``<clone lane>:<reason>`` -- the run's own lane trust for a clone lane it
#   did not compare (``canonical.comparison_rows`` reasons): every lane of a
#   foreign container ``baseline_scope_id``, a re-described lane
#   ``algorithm_revision``, and ``baseline_missing`` where the document holds
#   no container -- which, for a corrupted file the resolver refused, is the
#   report's own word too;
# * ``lane:unavailable:<lane>`` -- the evaluator's refusal for each lane an
#   active gate reads and cannot trust (``_unavailable``).  ``ci`` always runs
#   the clone gate (``fail_on_new``: ``clones.blocks``, ``clones.functions``);
#   ``relaxed`` runs no gate (``RELAXED_BUDGETS``); ``strict`` reads every
#   enabled lane (``STRICT_BUDGETS`` through the gate-to-lane matrix), and
#   ``--fail-on-api-break`` adds ``api_surface`` under ``ci`` and ``strict``.
_FOREIGN_BASELINE = "baseline:mismatch_scope_id"
_FOREIGN_CLONES = (
    "clones.blocks:baseline_scope_id",
    "clones.functions:baseline_scope_id",
)
_OPAQUE_CLONES = (
    "clones.blocks:algorithm_revision",
    "clones.functions:algorithm_revision",
)
_NO_CONTAINER_CLONES = (
    "clones.blocks:baseline_missing",
    "clones.functions:baseline_missing",
)
#: The gate's two population refusals (``report.gates.evaluator``
#: ``_POPULATION_REFUSALS``), each as the gate states it.
_EMPTY_SCOPE = f"metric:{gate_msgs.GATE_REASON_EMPTY_ANALYSIS_SCOPE}"
_UNMEASURED = f"metric:{gate_msgs.GATE_REASON_UNMEASURED_POPULATION}"
#: Every lane the run enables without ``--api-surface``, each read by a
#: ``strict`` gate.
_STRICT_LANES = tuple(
    f"lane:unavailable:{lane}"
    for lane in (
        "adoption_counts",
        "clones.blocks",
        "clones.functions",
        "coupling_cohesion_observations",
        "dead_code",
        "dependencies",
        "module_identity",
        "risk_observations",
    )
)


@dataclass(frozen=True)
class _Scenario:
    build: Callable[[Path], None]
    #: Analysed with the API surface (the baselines never hold one).
    api_surface: bool = False
    #: The gate request, as CLI flags and as the MCP request's fields.
    gate: tuple[str, ...] = ()
    #: Flags every CLI run of the scenario carries (MCP always measures).
    cli_flags: tuple[str, ...] = ()
    #: Whether the two surfaces' answers are held to :data:`ORACLE` too; the
    #: rows without one are held to their patch verdicts alone.
    surfaces: bool = True
    #: Each patch-verify run: its extra flags, and its expected verdict.
    patch_verify: Mapping[tuple[str, ...], _Verdict] = field(default_factory=dict)


#: What each surface must answer, from the contracts alone.
#: ``baseline`` / ``metrics_baseline``: ``(loaded, status)``;
#: ``new_clones``: the clone novelty count, ``None`` when no clone lane was
#: compared; ``health_compared``: whether the health delta was compared;
#: ``gate``: ``(exit code, reasons)`` under the scenario's gate request.
ORACLE: dict[str, dict[str, Any]] = {
    "own": {
        "baseline": _OK,
        "metrics_baseline": _OK,
        "new_clones": 0,
        "health_compared": True,
        "gate": (_SUCCESS, ()),
    },
    "foreign_without_gates": {
        "baseline": _FOREIGN,
        "metrics_baseline": _FOREIGN,
        "new_clones": None,
        "health_compared": False,
        "gate": (_SUCCESS, ()),
    },
    "foreign_with_gates": {
        "baseline": _FOREIGN,
        "metrics_baseline": _FOREIGN,
        "new_clones": None,
        "health_compared": False,
        "gate": (_CONTRACT_ERROR, _CLONE_LANES),
    },
    "no_api_snapshot_without_api_gate": {
        "baseline": _OK,
        "metrics_baseline": _OK,
        "new_clones": 0,
        "health_compared": True,
        "gate": (_SUCCESS, ()),
    },
    "no_api_snapshot_with_api_gate": {
        "baseline": _OK,
        "metrics_baseline": _OK,
        "new_clones": 0,
        "health_compared": True,
        "gate": (_CONTRACT_ERROR, _API_LANE),
    },
    "opaque_clone_lanes": {
        "baseline": _OK,
        "metrics_baseline": _OK,
        "new_clones": None,
        "health_compared": False,
        "gate": (_SUCCESS, ()),
    },
    "new_clone_on_a_compared_lane": {
        "baseline": _OK,
        "metrics_baseline": _OK,
        "new_clones": 1,
        "health_compared": True,
        "gate": (_GATING_FAILURE, ("clone:new",)),
    },
    "violation_beside_an_unavailable_lane": {
        "baseline": _OK,
        "metrics_baseline": _OK,
        "new_clones": 1,
        "health_compared": True,
        "gate": (_CONTRACT_ERROR, _API_LANE),
    },
    "absent_baseline": {
        "baseline": _MISSING,
        "metrics_baseline": _MISSING,
        "new_clones": None,
        "health_compared": False,
        "gate": (_SUCCESS, ()),
    },
    "corrupted_baseline": {
        "baseline": _CORRUPTED,
        "metrics_baseline": _CORRUPTED,
        "new_clones": None,
        "health_compared": False,
        "gate": (_SUCCESS, ()),
    },
}

_CI = ("--strictness", "ci")
_RELAXED = ("--strictness", "relaxed")
_STRICT = ("--strictness", "strict")
_API_GATE = ("--api-surface", "--fail-on-api-break")

SCENARIOS: dict[str, _Scenario] = {
    "own": _Scenario(
        build=_own,
        gate=("--fail-on-new",),
        patch_verify={_CI: _accepted()},
    ),
    "foreign_without_gates": _Scenario(
        build=_foreign,
        patch_verify={
            _RELAXED: _unverified(_FOREIGN_BASELINE, *_FOREIGN_CLONES),
            _CI: _unverified(_FOREIGN_BASELINE, *_FOREIGN_CLONES, *_CLONE_LANES),
            _STRICT: _unverified(_FOREIGN_BASELINE, *_FOREIGN_CLONES, *_STRICT_LANES),
        },
    ),
    "foreign_with_gates": _Scenario(
        build=_foreign,
        gate=("--fail-on-new",),
        patch_verify={
            (*_CI, "--fail-on-new"): _unverified(
                _FOREIGN_BASELINE, *_FOREIGN_CLONES, *_CLONE_LANES
            )
        },
    ),
    "no_api_snapshot_without_api_gate": _Scenario(
        build=_own,
        api_surface=True,
        patch_verify={(*_CI, "--api-surface"): _accepted()},
    ),
    "no_api_snapshot_with_api_gate": _Scenario(
        build=_own,
        api_surface=True,
        gate=("--fail-on-api-break",),
        patch_verify={(*_CI, *_API_GATE): _unverified(*_API_LANE)},
    ),
    "opaque_clone_lanes": _Scenario(
        build=_opaque,
        patch_verify={
            _CI: _unverified(*_OPAQUE_CLONES, *_CLONE_LANES),
            _RELAXED: _unverified(*_OPAQUE_CLONES),
        },
    ),
    "new_clone_on_a_compared_lane": _Scenario(
        build=_new_clone,
        gate=("--fail-on-new",),
        patch_verify={
            _CI: _violated(
                ("structural_regressions", "gate_failures"),
                exit_line=_EXIT_VIOLATION,
                exit_code=_GATING_FAILURE,
                closing=_VIOLATED,
            )
        },
    ),
    "violation_beside_an_unavailable_lane": _Scenario(
        build=_new_clone,
        api_surface=True,
        gate=("--fail-on-new", "--fail-on-api-break"),
        patch_verify={
            # ``relaxed`` runs no gate, so nothing is left unverified: the
            # proven violation alone, advisory.
            (*_RELAXED, *_API_GATE): _violated(
                ("structural_regressions",),
                exit_line=_EXIT_ADVISORY,
                exit_code=_SUCCESS,
                closing=_ADVISORY,
            ),
            (*_CI, *_API_GATE): _violated(
                ("structural_regressions",),
                *_API_LANE,
                exit_line=_EXIT_UNAVAILABLE,
                exit_code=_CONTRACT_ERROR,
                closing=_VIOLATED_INCOMPLETE,
            ),
            (*_STRICT, *_API_GATE): _violated(
                ("structural_regressions",),
                *_API_LANE,
                exit_line=_EXIT_UNAVAILABLE,
                exit_code=_CONTRACT_ERROR,
                closing=_VIOLATED_INCOMPLETE,
            ),
        },
    ),
    "absent_baseline": _Scenario(
        build=_absent,
        # Without a baseline the CLI skips metrics unless asked, and the
        # metrics resolver is never reached; forced, it reads the absence.
        cli_flags=("--no-skip-metrics",),
        patch_verify={
            _CI: _unverified("baseline:missing", *_NO_CONTAINER_CLONES, *_CLONE_LANES)
        },
    ),
    "corrupted_baseline": _Scenario(
        build=_corrupted,
        patch_verify={
            _CI: _unverified(
                "baseline:integrity_failed", *_NO_CONTAINER_CLONES, *_CLONE_LANES
            )
        },
    ),
    # Patch verdicts only: the surfaces' novelty counts over these trees are
    # not held here (both state 0 where a lane went uncompared or nothing
    # was read -- a finding of its own, outside this table).
    "partially_opaque_clone_lanes": _Scenario(
        build=_partially_opaque,
        surfaces=False,
        patch_verify={
            _RELAXED: _unverified("clones.blocks:algorithm_revision"),
            _CI: _unverified(
                "clones.blocks:algorithm_revision", "lane:unavailable:clones.blocks"
            ),
        },
    ),
    "emptied_scope": _Scenario(
        build=_emptied,
        surfaces=False,
        patch_verify={
            _CI: _unverified(policy=(_EMPTY_SCOPE,)),
            _STRICT: _unverified(policy=(_EMPTY_SCOPE,)),
        },
    ),
    "unread_sources": _Scenario(
        build=_unread,
        surfaces=False,
        patch_verify={
            _CI: _unverified(policy=(_UNMEASURED,)),
            _STRICT: _unverified(policy=(_UNMEASURED,)),
        },
    ),
}


# -- the observations ----------------------------------------------------------------


def _status_line(text: str, label: str) -> str | None:
    found = re.search(rf"^\s*{label}\s+(.+)$", text, re.MULTILINE)
    return found.group(1).strip() if found else None


def _labelled_lines(text: str, label: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(f"{label}:")
    ]


def _labelled_line(text: str, label: str) -> str:
    """The one ``<label>: ...`` line of the verdict, verbatim -- or a marker
    no oracle value can match when the CLI printed none, or two."""
    found = _labelled_lines(text, label)
    return found[0] if len(found) == 1 else f"<{len(found)} lines labelled {label}>"


def _optional_line(text: str, label: str) -> str | None:
    """A labelled line the CLI prints only when it has something to say:
    ``None`` when absent, the marker when it printed two."""
    found = _labelled_lines(text, label)
    return None if not found else _labelled_line(text, label)


def _closing_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "<no output>"


def _novelty_of_line(line: str | None) -> int | str | None:
    """The CLI's regressions row: a count when the clone lanes were
    compared, ``None`` when it says so -- and the row itself, verbatim,
    when it says neither (or is missing), so no oracle value can match it."""
    if line == "not compared":
        return None
    count = re.fullmatch(r"(\d+) new clone groups?", line or "")
    return int(count.group(1)) if count else f"<row: {line!r}>"


def cli_observation(root: Path, scenario: _Scenario) -> dict[str, object]:
    api = ("--api-surface",) if scenario.api_surface else ()
    report = root / "parity-report.json"
    _code, _text = _cli(
        root, "--json", str(report), *api, *scenario.gate, *scenario.cli_flags
    )
    document = json.loads(report.read_text("utf-8"))
    meta = document["meta"]
    outcome = document["evaluation"]["outcome"]
    # The regressions and health rows of a patch verification under the
    # same request: the CLI's own spelling of "compared" and "not compared".
    _code, verify_text = _cli(
        root, "--patch-verify", *api, *scenario.gate, *scenario.cli_flags, *_CI
    )
    return {
        "baseline": (meta["baseline"]["loaded"], meta["baseline"]["status"]),
        "metrics_baseline": (
            meta["metrics_baseline"]["loaded"],
            meta["metrics_baseline"]["status"],
        ),
        "new_clones": _novelty_of_line(_status_line(verify_text, "Regressions")),
        "health_compared": "→" in str(_status_line(verify_text, "Health")),
        "gate": (outcome["exit_code"], tuple(outcome["reasons"])),
    }


def mcp_observation(root: Path, scenario: _Scenario) -> dict[str, object]:
    service = CodeCloneMCPService(history_limit=4)
    run: dict[str, Any] = service.analyze_repository(
        MCPAnalysisRequest(root=str(root), api_surface=scenario.api_surface or None)
    )
    gate: dict[str, Any] = service.evaluate_gates(
        MCPGateRequest(
            run_id=str(run["run_id"]),
            fail_on_new="--fail-on-new" in scenario.gate,
            fail_on_api_break="--fail-on-api-break" in scenario.gate,
        )
    )
    return {
        "baseline": (run["baseline"]["loaded"], run["baseline"]["status"]),
        "metrics_baseline": (
            run["metrics_baseline"]["loaded"],
            run["metrics_baseline"]["status"],
        ),
        "new_clones": run["diff"]["new_clones"],
        "health_compared": run["diff"]["health_delta"] is not None,
        "gate": (gate["exit_code"], tuple(gate["reasons"])),
    }


def _verdict_of(text: str, code: int) -> _Verdict:
    return _Verdict(
        _labelled_line(text, "Verdict"),
        _labelled_line(text, "Completeness"),
        _labelled_line(text, "Exit"),
        _labelled_line(text, "Proven violations"),
        _labelled_line(text, "Unverified lanes"),
        _optional_line(text, _POLICY_FAILURES),
        _closing_line(text),
        code,
    )


def patch_verify_outcomes(
    root: Path, scenario: _Scenario
) -> dict[tuple[str, ...], _Verdict]:
    outcomes: dict[tuple[str, ...], _Verdict] = {}
    for flags in scenario.patch_verify:
        code, text = _cli(root, "--patch-verify", *flags, *scenario.cli_flags)
        outcomes[flags] = _verdict_of(text, code)
    return outcomes


@dataclass(frozen=True)
class _Observed:
    cli: dict[str, object]
    mcp: dict[str, object]
    patch_verify: dict[tuple[str, ...], _Verdict]


@pytest.fixture(scope="module")
def observed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, _Observed]:
    base = tmp_path_factory.mktemp("cli_mcp_parity").resolve()
    answers: dict[str, _Observed] = {}
    for name, scenario in SCENARIOS.items():
        root = base / name
        scenario.build(root)
        answers[name] = _Observed(
            cli=cli_observation(root, scenario) if scenario.surfaces else {},
            mcp=mcp_observation(root, scenario) if scenario.surfaces else {},
            patch_verify=patch_verify_outcomes(root, scenario),
        )
    return answers


# -- each surface against the oracle ---------------------------------------------


@pytest.mark.parametrize("surface", ["cli", "mcp"])
@pytest.mark.parametrize("name", list(ORACLE))
def test_each_surface_answers_the_oracle(
    observed: dict[str, _Observed], name: str, surface: str
) -> None:
    assert getattr(observed[name], surface) == ORACLE[name], (name, surface)


@pytest.mark.parametrize(
    ("name", "flags"),
    [
        (name, flags)
        for name, scenario in SCENARIOS.items()
        for flags in scenario.patch_verify
    ],
)
def test_the_cli_patch_verdict_answers_the_oracle(
    observed: dict[str, _Observed], name: str, flags: tuple[str, ...]
) -> None:
    """Every labelled line and the exit code, entry for entry: a reason
    dropped from ``Unverified lanes``, a lane added to it, a lost
    ``Completeness`` line or the code of a proven failure spent on an
    incomplete verification each fail here."""
    assert observed[name].patch_verify[flags] == SCENARIOS[name].patch_verify[flags]


def test_the_exit_line_states_the_exit_code() -> None:
    """The oracle's own consistency: each ``Exit:`` line names the code the
    process returns."""
    for scenario in SCENARIOS.values():
        for verdict in scenario.patch_verify.values():
            assert verdict.exit_line.startswith(f"Exit: {verdict.exit_code}")


# -- probe validity: the table can tell a working surface from a constant one ----


def _all_verdicts() -> list[_Verdict]:
    return [
        verdict
        for scenario in SCENARIOS.values()
        for verdict in scenario.patch_verify.values()
    ]


def _reason_kind(entry: str) -> str:
    return (
        entry.split(":", 1)[0] if entry.startswith(("baseline:", "lane:")) else "clone"
    )


def _unverified_entries(verdict: _Verdict) -> list[str]:
    listed = verdict.unverified_lanes.removeprefix("Unverified lanes: [")
    return [entry for entry in listed.removesuffix("]").split(", ") if entry]


def test_the_surface_rows_reach_every_trust_comparison_and_gate_state() -> None:
    """The surfaces' table holds every trust state, every comparison state
    and every gate outcome the contracts distinguish -- and exactly the
    scenarios held to the surfaces."""
    assert (
        {answer["baseline"] for answer in ORACLE.values()},
        {answer["new_clones"] for answer in ORACLE.values()},
        {answer["gate"][0] for answer in ORACLE.values()},
        set(ORACLE),
    ) == (
        {_OK, _FOREIGN, _MISSING, _CORRUPTED},
        {0, 1, None},
        {_SUCCESS, _CONTRACT_ERROR, _GATING_FAILURE},
        {name for name, item in SCENARIOS.items() if item.surfaces},
    )


def test_the_patch_verdicts_reach_every_outcome_and_closing() -> None:
    """Every (verdict, completeness, exit) the matrix distinguishes, every
    closing sentence, and the policy-failure line both present and absent."""
    verdicts = _all_verdicts()
    assert (
        {(item.verdict, item.completeness, item.exit_code) for item in verdicts},
        {item.closing for item in verdicts},
        {item.policy_failures for item in verdicts},
    ) == (
        {
            ("Verdict: ACCEPTED", "Completeness: COMPLETE", _SUCCESS),
            ("Verdict: UNVERIFIED", "Completeness: INCOMPLETE", _CONTRACT_ERROR),
            ("Verdict: VIOLATED", "Completeness: COMPLETE", _GATING_FAILURE),
            ("Verdict: VIOLATED", "Completeness: COMPLETE", _SUCCESS),
            ("Verdict: VIOLATED", "Completeness: INCOMPLETE", _CONTRACT_ERROR),
        },
        {_ACCEPTED, _NOT_VERIFIED, _VIOLATED, _VIOLATED_INCOMPLETE, _ADVISORY},
        {
            None,
            f"{_POLICY_FAILURES}: [{_EMPTY_SCOPE}]",
            f"{_POLICY_FAILURES}: [{_UNMEASURED}]",
        },
    )


def test_the_unverified_reasons_reach_every_kind_beside_another() -> None:
    """Every kind of unverified reason, and lists long enough that a reason
    dropped beside another one is visible."""
    verdicts = _all_verdicts()
    kinds = {
        _reason_kind(entry) for item in verdicts for entry in _unverified_entries(item)
    }
    longest = max(len(_unverified_entries(item)) for item in verdicts)
    assert (kinds, longest >= 3) == ({"baseline", "clone", "lane"}, True)


# -- why the oracle and not each other ----------------------------------------------


def _context_blind_blocking_lanes(
    unavailable: Sequence[Any], *, required_lanes: frozenset[str]
) -> tuple[str, ...]:
    """The shared owner with its context rule deleted: only what a gate
    reads blocks -- the defect both surfaces would share."""
    return tuple(sorted({item.name for item in unavailable} & required_lanes))


@contextlib.contextmanager
def _shared_owner_broken() -> Iterator[None]:
    import codeclone.surfaces.cli.baseline_state as cli_baseline
    import codeclone.surfaces.mcp._session_baseline as mcp_baseline

    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(mcp_baseline, "blocking_lanes", _context_blind_blocking_lanes)
        patch.setattr(cli_baseline, "blocking_lanes", _context_blind_blocking_lanes)
        yield
    finally:
        patch.undo()


def test_the_oracle_sees_what_a_surface_to_surface_comparison_cannot(
    tmp_path: Path,
) -> None:
    """The positive control of the test design, on the path it guards: the
    one lane owner both surfaces consult, with its context rule removed.
    Both surfaces then trust a foreign baseline -- identically -- so a test
    comparing them with each other stays green, while the oracle names the
    defect on each of them."""
    scenario = SCENARIOS["foreign_without_gates"]
    root = tmp_path / "foreign"
    scenario.build(root)
    with _shared_owner_broken():
        cli = cli_observation(root, scenario)
        mcp = mcp_observation(root, scenario)
    assert cli["baseline"] == mcp["baseline"] == _OK
    assert cli["baseline"] != ORACLE["foreign_without_gates"]["baseline"]
    assert mcp["baseline"] != ORACLE["foreign_without_gates"]["baseline"]
