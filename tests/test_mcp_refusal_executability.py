# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""A refusal may only prescribe what its own tool can accept.

A typed refusal that names a parameter is an instruction. The instruction is
executable only when that parameter exists in the input schema of the tool
that emitted the refusal — otherwise the caller is told to do something the
wire will reject, and the typed outcome has no next step at all.

The two halves of that predicate come from different places on purpose. The
prescription is read out of the refusal a live tool call produced; the
parameter vocabulary is read out of the FastMCP input schemas the client
actually sees. Neither side can vouch for the other.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

import codeclone

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server.fastmcp import FastMCP

pytest.importorskip("mcp.server.fastmcp")

from codeclone.surfaces.mcp._session_shared import MCPRunRootAmbiguityError
from codeclone.surfaces.mcp.server import build_mcp_server
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPGateRequest
from tests.test_mcp_service import (
    _paired_repo_roots,
    _patch_contract_run_record,
)

# "pass root", "provide run_id", "set limit" — a bare instruction to hand the
# tool a named value.
_BARE_PRESCRIPTION = re.compile(
    r"\b(?:pass|provide|supply|set)\s+(?:an?\s+|the\s+)?([a-z_][a-z0-9_]{2,})\b",
    re.IGNORECASE,
)
# "analyze_repository(root='...')" — an instruction to call a named tool with
# a named argument.
_CALL_PRESCRIPTION = re.compile(
    r"\b([a-z_][a-z0-9_]{2,})\s*\(\s*([a-z_][a-z0-9_]{2,})\s*=",
)

# Arguments a tool needs before it can reach run resolution at all. Kept
# explicit so a newly added tool fails loudly here instead of dropping out of
# the sweep unnoticed.
_REQUIRED_ARGUMENTS: dict[str, dict[str, object]] = {
    "check_patch_contract": {"mode": "verify", "changed_files": ["pkg/mod.py"]},
    "finish_controlled_change": {"intent_id": "no-such-intent"},
    "get_blast_radius": {"files": ["pkg/mod.py"]},
    "get_finding": {"finding_id": "no-such-finding"},
    "get_implementation_context_page": {
        "context_projection_digest": "0" * 64,
        "facet": "modules",
    },
    "get_remediation": {"finding_id": "no-such-finding"},
    "list_hotspots": {"kind": "highest_priority"},
    "manage_change_intent": {"action": "check", "changed_files": ["pkg/mod.py"]},
    "manage_engineering_memory": {"action": "validate_claims", "text": "a claim"},
    "mark_finding_reviewed": {"finding_id": "no-such-finding"},
    "validate_review_claims": {"text": "a claim about pkg/mod.py"},
}

# Tools measured to answer a collided run id with the multi-root refusal. The
# sweep asserts every one of them still reaches it: a probe that stopped
# reaching the refusal would otherwise report a clean run it never made.
_KNOWN_AMBIGUITY_EMITTERS = frozenset(
    {
        "check_authority",
        "check_clones",
        "check_cohesion",
        "check_complexity",
        "check_coupling",
        "check_dead_code",
        "compare_runs",
        "create_review_receipt",
        "evaluate_gates",
        "generate_pr_summary",
        "get_blast_radius",
        "get_finding",
        "get_production_triage",
        "get_remediation",
        "get_report_section",
        "get_run_summary",
        "list_findings",
        "list_hotspots",
        "list_reviewed_findings",
        "mark_finding_reviewed",
        "validate_review_claims",
    }
)

_AMBIGUITY_SIGNATURE = "exists under several repository roots"


def _tool_schemas(
    server: FastMCP,
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """Parameter names and required names per tool, as the MCP client sees them."""

    tools = asyncio.run(server.list_tools())
    properties = {
        tool.name: frozenset(
            cast("dict[str, object]", tool.inputSchema.get("properties") or {})
        )
        for tool in tools
    }
    required = {
        tool.name: frozenset(cast("list[str]", tool.inputSchema.get("required") or []))
        for tool in tools
    }
    return properties, required


def unexecutable_prescriptions(
    tool: str,
    message: str,
    schemas: dict[str, frozenset[str]],
) -> tuple[str, ...]:
    """Names this refusal tells the caller to use that the wire would reject.

    A name counts as a prescription when it is a parameter of *some* MCP tool,
    or when it is written as an identifier (``checkout_root``) rather than as
    prose. Renaming the prescribed parameter to something no tool has is the
    same defect as naming one this tool lacks, so both must be caught, while
    ordinary prose ("pass an exact qualname") stays out without a
    hand-maintained stop list.
    """

    vocabulary = frozenset().union(*schemas.values()) if schemas else frozenset()
    own = schemas.get(tool, frozenset())
    flagged: list[str] = []
    for match in _BARE_PRESCRIPTION.finditer(message):
        name = match.group(1).lower()
        prescribed = name in vocabulary or "_" in name
        if prescribed and name not in own:
            flagged.append(f"{tool} cannot accept '{name}'")
    for match in _CALL_PRESCRIPTION.finditer(message):
        callee, parameter = match.group(1), match.group(2)
        if callee in schemas and parameter not in schemas[callee]:
            flagged.append(f"{callee} cannot accept '{parameter}'")
    return tuple(dict.fromkeys(flagged))


def _write_identical_worktree(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(
        "def alpha(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )


def _collided_server(tmp_path: Path) -> tuple[FastMCP, str, Path]:
    """Two byte-identical checkouts, analyzed through the real MCP surface.

    Run ids are content-addressed, so this is the live collision rather than a
    hand-built store: both roots answer to one id.
    """

    server = build_mcp_server(history_limit=4)
    run_ids: list[str] = []
    for name in ("worktree-a", "worktree-b"):
        root = tmp_path / name
        _write_identical_worktree(root)
        result = asyncio.run(
            server.call_tool(
                "analyze_repository",
                {"root": str(root), "respect_pyproject": False},
            )
        )
        # FastMCP declares Sequence[ContentBlock] | dict, but a structured
        # tool answers with the (content, structured_payload) pair, and the
        # payload is what carries the run id.
        payload = cast("tuple[object, dict[str, object]]", result)[1]
        run_ids.append(str(payload["run_id"]))
    assert run_ids[0] == run_ids[1], (
        f"identical checkouts must produce one content-addressed run id; got {run_ids}"
    )
    return server, run_ids[0], tmp_path / "worktree-a"


def _probe(
    server: FastMCP,
    tool: str,
    *,
    run_id: str,
    schemas: dict[str, frozenset[str]],
    required: dict[str, frozenset[str]],
    root: Path,
) -> str | None:
    """Call one tool with the collided id; return its refusal text, if any.

    The root is supplied only where the schema demands it. Everywhere else the
    call stays rootless on purpose: that is the caller the refusal addresses,
    and handing the tool a root would resolve the collision the probe exists
    to observe.
    """

    arguments: dict[str, Any] = dict(_REQUIRED_ARGUMENTS.get(tool, {}))
    properties = schemas[tool]
    if "root" in required[tool]:
        arguments["root"] = str(root)
    for name in ("run_id", "before_run_id", "after_run_id"):
        if name in properties:
            arguments[name] = run_id
    try:
        asyncio.run(server.call_tool(tool, arguments))
    except Exception as exc:  # the refusal text is exactly the subject here
        return str(exc)
    return None


@pytest.fixture(scope="module")
def collided_sweep(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """Every run-id tool called once against a live two-root collision."""

    server, run_id, root = _collided_server(tmp_path_factory.mktemp("collision"))
    schemas, required = _tool_schemas(server)
    probed = sorted(
        name
        for name, properties in schemas.items()
        if any(item.endswith("run_id") for item in properties)
    )
    assert set(_REQUIRED_ARGUMENTS) <= set(probed), (
        "the required-argument table names tools that are not probed"
    )
    refusals: dict[str, str] = {}
    for tool in probed:
        message = _probe(
            server,
            tool,
            run_id=run_id,
            schemas=schemas,
            required=required,
            root=root,
        )
        if message is not None:
            refusals[tool] = message
    return refusals, schemas


def test_the_sweep_still_reaches_the_multi_root_refusal(
    collided_sweep: tuple[dict[str, str], dict[str, frozenset[str]]],
) -> None:
    """Witness before count: prove the instrument is on before reading it.

    Without this, a sweep that quietly stopped producing refusals would report
    a clean result it never measured.
    """

    refusals, _schemas = collided_sweep
    ambiguity = {
        tool for tool, text in refusals.items() if _AMBIGUITY_SIGNATURE in text
    }
    assert ambiguity >= _KNOWN_AMBIGUITY_EMITTERS, (
        "tools that no longer reach the multi-root refusal: "
        f"{sorted(_KNOWN_AMBIGUITY_EMITTERS - ambiguity)}"
    )


def test_refusals_prescribe_only_parameters_their_own_tool_accepts(
    collided_sweep: tuple[dict[str, str], dict[str, frozenset[str]]],
) -> None:
    """No tool may answer a collided run id with an instruction it would reject."""

    refusals, schemas = collided_sweep
    violations = {
        tool: found
        for tool, text in sorted(refusals.items())
        if (found := unexecutable_prescriptions(tool, text, schemas))
    }
    assert violations == {}, (
        f"refusals prescribe parameters their own tool cannot accept: {violations}"
    )


def test_predicate_flags_a_prescription_the_emitting_tool_cannot_accept() -> None:
    """The blind side: a name absent from the tool's own schema must be flagged."""

    schemas = {
        "get_report_section": frozenset({"run_id", "section"}),
        "check_clones": frozenset({"run_id", "root"}),
    }
    assert unexecutable_prescriptions(
        "get_report_section",
        "Run id 'abc' exists under several repository roots (a, b); "
        "pass root to select one.",
        schemas,
    ) == ("get_report_section cannot accept 'root'",)


def test_predicate_accepts_a_prescription_the_emitting_tool_can_honour() -> None:
    """The panicky side: the same words are executable where the parameter exists."""

    schemas = {
        "get_report_section": frozenset({"run_id", "section"}),
        "check_clones": frozenset({"run_id", "root"}),
    }
    assert (
        unexecutable_prescriptions(
            "check_clones",
            "Run id 'abc' exists under several repository roots (a, b); "
            "pass root to select one.",
            schemas,
        )
        == ()
    )


def test_predicate_ignores_prose_that_is_not_a_parameter_name() -> None:
    """Prose must not be read as a prescription, or the ratchet cries wolf."""

    schemas = {"get_implementation_context": frozenset({"run_id", "root"})}
    assert (
        unexecutable_prescriptions(
            "get_implementation_context",
            "Pass an exact qualname as module:symbol with a colon separator.",
            schemas,
        )
        == ()
    )


def test_predicate_flags_a_prescription_no_tool_at_all_would_accept() -> None:
    """Renaming the prescribed parameter must not launder it past the ratchet."""

    schemas = {
        "get_report_section": frozenset({"run_id", "section"}),
        "check_clones": frozenset({"run_id", "root"}),
    }
    assert unexecutable_prescriptions(
        "get_report_section",
        "Run id 'abc' exists under several repository roots (a, b); "
        "pass checkout_root to select one.",
        schemas,
    ) == ("get_report_section cannot accept 'checkout_root'",)


def test_predicate_flags_a_cross_tool_call_form_with_an_unknown_parameter() -> None:
    """A refusal may also prescribe another tool; that call must be valid too."""

    schemas = {
        "get_report_section": frozenset({"run_id"}),
        "analyze_repository": frozenset({"root"}),
    }
    assert unexecutable_prescriptions(
        "get_report_section",
        "Call analyze_repository(checkout='/repo') and retry.",
        schemas,
    ) == ("analyze_repository cannot accept 'checkout'",)


def test_predicate_accepts_a_valid_cross_tool_call_form() -> None:
    """The executable cross-tool prescription must stay unflagged."""

    schemas = {
        "get_report_section": frozenset({"run_id"}),
        "analyze_repository": frozenset({"root"}),
    }
    assert (
        unexecutable_prescriptions(
            "get_report_section",
            "Call analyze_repository(root='/repo') and retry.",
            schemas,
        )
        == ()
    )


# ---------------------------------------------------------------------------
# Rule 1: a declared root must actually select the record it names.
#
# Declaring `root` in the schema is a promise. The promise is only worth
# something if the value reaches the resolution that picks the run, and a
# helper shared by sixteen tools cannot testify for any single one of them:
# mutating the helper kills every test at once, so one tool quietly dropping
# its own `root` stays green. This drives every tool the schema commits.
# ---------------------------------------------------------------------------

_COLLIDED_RUN_ID = "before1234567890"

# Arguments a tool needs before it reaches run resolution. Kept explicit so a
# newly added tool fails loudly here rather than dropping out of the sweep.
_SELECTOR_ARGUMENTS: dict[str, dict[str, object]] = {
    "check_patch_contract": {
        "mode": "verify",
        "before_run_id": _COLLIDED_RUN_ID,
        "changed_files": ["pkg/a.py"],
    },
    "compare_runs": {"before_run_id": _COLLIDED_RUN_ID},
    "get_blast_radius": {"files": ["pkg/a.py"]},
    "get_finding": {"finding_id": "fn:g1"},
    "get_remediation": {"finding_id": "fn:g1"},
    "list_hotspots": {"kind": "highest_priority"},
    "manage_change_intent": {"action": "check", "changed_files": ["pkg/a.py"]},
    "mark_finding_reviewed": {"finding_id": "fn:g1"},
    "validate_review_claims": {"text": "a claim about pkg/a.py"},
}


def _root_selector_population(
    schemas: dict[str, frozenset[str]],
    required: dict[str, frozenset[str]],
) -> tuple[str, ...]:
    """Tools that declare an *optional* root beside a run id.

    A tool whose root is required cannot silently ignore it — there is no
    rootless call for it to fall back to — so it leaves the population by a
    property of its own schema rather than by being listed here.
    """

    return tuple(
        sorted(
            name
            for name, properties in schemas.items()
            if "root" in properties
            and "root" not in required[name]
            and any(item.endswith("run_id") for item in properties)
        )
    )


def _distinguishable_collision(
    tmp_path: Path,
) -> tuple[CodeCloneMCPService, Path, Path]:
    """One run id under two checkouts, whose records are told apart."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    root_a, root_b = _paired_repo_roots(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    # The two records must differ in more than one place, or a tool that picks
    # the wrong checkout can still answer identically and look correct.
    for root, health, complexity, path in (
        (root_a, 81, 6, "pkg/a.py"),
        (root_b, 42, 14, "pkg/zz.py"),
    ):
        service._runs.register(
            _patch_contract_run_record(
                root,
                run_id=_COLLIDED_RUN_ID,
                digest="shared-digest",
                include_regression=True,
                complexity=complexity,
                health=health,
                regression_path=path,
                complexity_path=path,
            )
        )
    return service, root_a, root_b


def _call_selector_tool(
    service: CodeCloneMCPService,
    tool: str,
    *,
    root: Path | None,
) -> object:
    arguments: dict[str, Any] = dict(_SELECTOR_ARGUMENTS.get(tool, {}))
    if root is not None:
        arguments["root"] = str(root)
    if tool != "compare_runs":
        arguments["run_id"] = _COLLIDED_RUN_ID
    if tool == "evaluate_gates":
        return service.evaluate_gates(
            MCPGateRequest(
                run_id=_COLLIDED_RUN_ID,
                root=None if root is None else str(root),
            )
        )
    return getattr(service, tool)(**arguments)


def _ambiguity_raised(
    service: CodeCloneMCPService,
    tool: str,
    *,
    root: Path | None,
) -> bool:
    """Did this call fail closed on the shared id?

    Any other outcome — a payload, a typed not-found, a contract error — means
    resolution did not stop on ambiguity, which is all this rule asks about.
    """

    try:
        _call_selector_tool(service, tool, root=root)
    except MCPRunRootAmbiguityError:
        return True
    except Exception:
        return False
    return False


def test_every_root_declaring_tool_honours_the_root_it_was_given(
    tmp_path: Path,
) -> None:
    """The population rule: a named root must select the run it names.

    Two halves per tool, and the first is the witness for the second. The
    rootless call must fail closed, proving this tool really does resolve a
    run by id and that the branch a dropped root would fall into is reachable.
    Only then does the rooted call mean anything.
    """

    server = build_mcp_server(history_limit=4)
    schemas, required = _tool_schemas(server)
    population = _root_selector_population(schemas, required)
    assert population, "no tool declares an optional root beside a run id"
    unknown = sorted(set(_SELECTOR_ARGUMENTS) - set(population))
    assert unknown == [], (
        f"argument table names tools outside the population: {unknown}"
    )

    unreachable: list[str] = []
    ignoring: list[str] = []
    for index, tool in enumerate(population):
        rootless_service, _a, _b = _distinguishable_collision(
            tmp_path / f"rootless{index}"
        )
        if not _ambiguity_raised(rootless_service, tool, root=None):
            unreachable.append(tool)
            continue
        rooted_service, root_a, _b2 = _distinguishable_collision(
            tmp_path / f"rooted{index}"
        )
        if _ambiguity_raised(rooted_service, tool, root=root_a):
            ignoring.append(tool)

    assert unreachable == [], (
        "these tools never reached the multi-root refusal, so this sweep cannot "
        f"testify about their root at all: {unreachable}"
    )
    assert ignoring == [], (
        f"these tools declare root and then resolve the run without it: {ignoring}"
    )


# ---------------------------------------------------------------------------
# Rule 2: an internal re-entry must stay bound to the record's own root.
#
# A tool that already resolved its record and then re-enters the resolver by
# bare id walks back into the very refusal it just escaped. The binding that
# prevents it is one keyword argument, invisible to every behavioural test
# that does not run on a shared id.
# ---------------------------------------------------------------------------


# The resolver names a re-entry must not walk back into by bare id.
_RUN_RESOLVERS = frozenset(
    {
        "resolve_any_root",
        "get_for_root",
        "_resolve_run_for_optional_root",
        "_run_bound_to_root",
    }
)


def _package_modules() -> tuple[Path, ...]:
    package_root = Path(codeclone.__file__).resolve().parent
    return tuple(sorted(package_root.rglob("*.py")))


def _parsed_package() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple(
        (path, ast.parse(path.read_text(encoding="utf-8")))
        for path in _package_modules()
    )


def _resolving_callees(
    parsed: tuple[tuple[Path, ast.Module], ...],
) -> frozenset[str]:
    """Names whose bodies can reach a run resolver, by transitive closure.

    Resolved by name rather than by import graph: a re-entry is dangerous
    because of what the callee eventually does, and this errs towards
    including a name rather than letting a resolving one slip out.
    """

    calls: dict[str, set[str]] = {}
    for _path, tree in parsed:

        def walk(node: ast.AST, enclosing: str | None) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    calls.setdefault(child.name, set())
                    walk(child, child.name)
                    continue
                if enclosing is not None and isinstance(child, ast.Call):
                    callee = child.func
                    if isinstance(callee, ast.Name):
                        calls[enclosing].add(callee.id)
                    elif isinstance(callee, ast.Attribute):
                        calls[enclosing].add(callee.attr)
                walk(child, enclosing)

        walk(tree, None)

    reaching = set(_RUN_RESOLVERS)
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            if name not in reaching and callees & reaching:
                reaching.add(name)
                changed = True
    return frozenset(reaching)


def _reentry_call_sites() -> tuple[tuple[str, int, str, str, str], ...]:
    """Every call that re-enters a resolver with an already-resolved run id.

    Read from the whole package, never one module: the rule is about where a
    resolved record is handed back to something that resolves again, and that
    can be written in any file. A sweep bounded to one file holds only the
    sites that file happens to contain.
    """

    parsed = _parsed_package()
    resolving = _resolving_callees(parsed)
    package_root = Path(codeclone.__file__).resolve().parent.parent
    sites: list[tuple[str, int, str, str, str]] = []
    for path, tree in parsed:
        module = str(path.relative_to(package_root))

        def walk(node: ast.AST, enclosing: str, module: str = module) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    walk(child, child.name)
                    continue
                if isinstance(child, ast.Call):
                    keywords = {kw.arg: kw.value for kw in child.keywords if kw.arg}
                    run_id = keywords.get("run_id")
                    callee = child.func
                    name = (
                        callee.attr
                        if isinstance(callee, ast.Attribute)
                        else callee.id
                        if isinstance(callee, ast.Name)
                        else ""
                    )
                    if (
                        isinstance(run_id, ast.Attribute)
                        and run_id.attr == "run_id"
                        and name in resolving
                    ):
                        root = keywords.get("root")
                        if root is None:
                            state = "missing"
                        elif isinstance(root, ast.Constant) and root.value is None:
                            state = "literal-none"
                        else:
                            state = "bound"
                        sites.append((module, child.lineno, enclosing, name, state))
                walk(child, enclosing)

        walk(tree, "<module>")
    return tuple(sites)


def test_every_record_reentry_is_bound_to_its_root() -> None:
    """A resolved record handed back to a resolver must carry its own root.

    Three assertions, and the first two exist so the third cannot pass on an
    empty sweep: the reachability closure must have found the real resolvers,
    and the sites must span more than one module — the exact way this rule
    was blind when it read a single file.
    """

    parsed = _parsed_package()
    resolving = _resolving_callees(parsed)
    assert {"_service_get_finding", "list_hotspots", "get_production_triage"} <= (
        resolving
    ), "the reachability closure lost the known resolving entry points"

    sites = _reentry_call_sites()
    modules = {module for module, _line, _encl, _callee, _state in sites}
    assert len(modules) >= 2, (
        f"the sweep collapsed to {sorted(modules)}; a package-wide rule that "
        "only ever finds one module is not holding its population"
    )

    unbound = [site for site in sites if site[4] != "bound"]
    assert unbound == [], (
        f"re-entry by bare run id, without the record's root: {unbound}"
    )


def _service_reentry_tools() -> tuple[str, ...]:
    """Re-entering methods that are themselves run-id-taking MCP tools.

    A re-entering method that is not a tool, or a tool that takes no run id,
    cannot be driven by a shared run id at all; it leaves this behavioural
    half by its own schema and stays covered by the static rule above.
    """

    server = build_mcp_server(history_limit=4)
    schemas, _required = _tool_schemas(server)
    return tuple(
        sorted(
            {
                enclosing
                for _module, _line, enclosing, _callee, _state in _reentry_call_sites()
                if enclosing in schemas and "run_id" in schemas[enclosing]
            }
        )
    )


@pytest.mark.parametrize("tool", _service_reentry_tools())
def test_internal_finding_reentry_survives_a_shared_run_id(
    tool: str,
    tmp_path: Path,
) -> None:
    """Each re-entering tool must still answer on a collision.

    Parameterised over the tools the package sweep found, so each fails under
    its own id and a new one arrives already covered.
    """

    service, root_a, _root_b = _distinguishable_collision(tmp_path)
    if tool == "list_reviewed_findings":
        service.mark_finding_reviewed(
            finding_id="fn:g1",
            run_id=_COLLIDED_RUN_ID,
            root=str(root_a),
        )
    try:
        _call_selector_tool(service, tool, root=root_a)
    except MCPRunRootAmbiguityError as exc:  # pragma: no cover - the defect path
        pytest.fail(f"{tool} re-entered a resolver by bare id: {exc}")


@pytest.mark.parametrize("suffix", ["triage", "overview", "findings/fn:g1"])
def test_latest_resource_rendering_stays_bound_to_its_record(
    suffix: str,
    tmp_path: Path,
) -> None:
    """The resource surface has no root to pass, so it must bind its own.

    ``codeclone://latest/...`` resolves the newest record without an id and
    then renders it. Rendering that re-entered by bare id walked straight into
    the multi-root refusal on any two checkouts sharing a run.
    """

    service, _root_a, _root_b = _distinguishable_collision(tmp_path)
    try:
        service.read_resource(f"codeclone://latest/{suffix}")
    except MCPRunRootAmbiguityError as exc:  # pragma: no cover - the defect path
        pytest.fail(f"codeclone://latest/{suffix} re-entered by bare run id: {exc}")
