# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The body of the MCP reference page must match the live server.

``tests/test_mcp_tools_doc_signatures.py`` holds the published *call shapes*
against ``list_tools()`` and names two things outside its jurisdiction: the
fenced Python examples, and the values prose offers as accepted. This module
holds those. Both are read for their shape and resolved against the live
registry and a measured session, never against a list of today's words.

Three claims a body line can make, and the owner each is resolved against:

1. A keyword in a fenced call names a parameter of that tool. Owner: the
   tool's ``inputSchema``. Measured before this guard existed: the example
   ``analyze_repository(root=..., cache_policy="reuse")`` published a
   parameter the server refuses by name.
2. A literal handed to a parameter is a value the server accepts. Owner: the
   schema ``enum`` where the parameter has one; for a run-id parameter the
   live run store, because run ids have no schema vocabulary and the store is
   the validator; for ``root`` the absolute-path rule the page itself states.
   Measured: ``get_production_triage(run_id="latest")`` and the prose
   ``run_id (..., or `latest` for the session-local run)`` -- the store reads
   ``latest`` as an id prefix and refuses it even while a latest run exists.
   ``latest`` *is* the live default of ``query_platform_observability.window``,
   so a registry-wide "does this word exist" lookup passes it; the check is
   bound to the parameter the page hands it to.
3. A subscript on a name bound to a tool's response reads a key that response
   carries. Owner: the measured response of that tool on a fixture session.
   Measured: ``result['health_score']`` (the payload carries ``health``, a
   dict with ``score`` and ``grade``), ``result['artifacts']['report_path']``
   (no such key), ``triage["hotspots"]`` (the key is ``top_hotspots``) and
   ``hotspot['path']`` (a card carries ``locations`` and ``kind``).

The prose form of claim 2 is read by shape, as the signature guard reads
``name=value``. A backticked disjunction ```a` or `b``` -- optionally with a
parenthetical after ``a`` -- offers both tokens as accepted values; a
backticked token inside a parenthetical that directly follows a backticked
parameter name, ```param` (... `token` ...)```, offers that token as a value
of that parameter. A disjunction is bound to the nearest backticked parameter
name before it on its line. A value offered under a parameter is checked
against that parameter's owner; a value offered under no parameter must be an
enum or default value of *some* tool, because a value no parameter accepts is
not a value. Measured: ```reuse` or `off``` at two places, with the parameter
never named -- which is why the signature guard, keyed on names, could not
see it.

That rule runs over the reference page only, for a measured reason: the
contract page offers *response* vocabularies in the same shape (``not_found``
or ``mismatch`` statuses at two places, ``run_store`` or ``memory`` and
``not_published`` or ``store_disabled`` under ``serving`` -- 7 tokens on 3
lines), and the shape cannot tell an offered input from a reported output
when neither names a parameter. The owner of an input value is the schema;
the owner of a response value is not, and this module does not invent one.
The example rule runs over both pages.

Population is read the way a reader reads: the fenced examples form one
narrative in document order, so ``result`` bound in the first block is what a
later ``run_id=result["run_id"]`` means. Every tool an example calls must have
a measured response in the session; a tool the session did not run is
reported, not skipped. A loop over a response list binds its variable to the
first element, and an empty list is reported, because a key check on no
element proves nothing.

Not inspected, measured rather than assumed:

- Prose values offered in other shapes: comma lists of statuses and actions,
  and parentheticals after a parameter whose schema is a free string with no
  run-id or root meaning (``section (...)``). Their owners are response and
  action vocabularies the schema does not carry.
- Free-form string literals for such parameters (``intent="..."``), and dict
  or list literals (``scope={...}``).
- A value offered as a default of one tool but presented under another; the
  disjunction rule accepts any live enum or default value.
"""

from __future__ import annotations

import ast
import asyncio
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final, NamedTuple

import pytest

from codeclone.surfaces.mcp import _session_shared as session_shared
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_REFERENCE_DOC: Final = _REPO_ROOT / "docs" / "reference" / "mcp-tools.md"
_CONTRACT_DOC: Final = _REPO_ROOT / "docs" / "internal" / "contracts" / "mcp-tools.md"
_DOC_PATHS: Final = (_REFERENCE_DOC, _CONTRACT_DOC)
# The prose value rule owns input vocabularies; see the module docstring for
# the measured reason the contract page is outside it.
_PROSE_VALUE_DOCS: Final = (_REFERENCE_DOC,)

_TOKEN: Final = r"[A-Za-z_][A-Za-z0-9_]*"
# ```a` or `b``` and ```a` (...) or `b```: both tokens are offered as values.
_DISJUNCTION: Final = re.compile(rf"`({_TOKEN})`(?:\s*\([^()]*\))?\s+or\s+`({_TOKEN})`")
# ```name` (...)```: the parenthetical qualifies ``name``.
_QUALIFIED: Final = re.compile(rf"`({_TOKEN})`\s*\(([^()]*)\)")
_BARE: Final = re.compile(rf"`({_TOKEN})`")
# The marker a loop binding leaves on a key path: "one element of this list".
_ELEMENT: Final = "[]"
# A parameter whose value is a stored run's id, whichever tool declares it.
_RUN_ID_SUFFIX: Final = "run_id"

RunIdResolver = Callable[[str], str | None]
"""Resolve one run-id literal on the live store: ``None``, or the refusal."""


class ToolSchema(NamedTuple):
    """The live input schema of one registered tool."""

    accepted: frozenset[str]
    enums: Mapping[str, frozenset[str]]
    defaults: Mapping[str, str]


class MeasuredSession(NamedTuple):
    """Responses one real session produced, keyed by the tool that answered."""

    root: str
    responses: Mapping[str, Mapping[str, object]]
    resolve_run_id: RunIdResolver


class Binding(NamedTuple):
    """What a name in the examples stands for: a path into a tool's response."""

    tool: str
    path: tuple[str, ...]


class ProseValueClaim(NamedTuple):
    """One token prose offers as an accepted value."""

    line: int
    value: str
    parameter: str | None


def _enum_values(spec: object) -> frozenset[str]:
    if not isinstance(spec, dict):
        return frozenset()
    values: set[str] = {v for v in spec.get("enum", ()) or () if isinstance(v, str)}
    for key in ("anyOf", "oneOf", "allOf"):
        for member in spec.get(key, ()) or ():
            values |= _enum_values(member)
    values |= _enum_values(spec.get("items"))
    return frozenset(values)


def _fenced_python(document: str) -> list[tuple[int, str]]:
    """``(first line number, source)`` for every ```python fence, in order."""
    blocks: list[tuple[int, str]] = []
    start: int | None = None
    lines: list[str] = []
    for number, line in enumerate(document.splitlines(), start=1):
        stripped = line.strip()
        if start is None:
            if stripped.startswith("```python"):
                start, lines = number + 1, []
        elif stripped.startswith("```"):
            blocks.append((start, "\n".join(lines)))
            start = None
        else:
            lines.append(line)
    return blocks


def _chain(node: ast.expr) -> tuple[str | None, tuple[str, ...]] | None:
    """``name, (key, ...)`` for ``name["key"]...``.

    ``None`` when a key is not a string literal (unreadable, so reported);
    ``(None, keys)`` when the chain is not rooted at a name (``f(x)["k"]``,
    ``os.environ["k"]``: not a response read, so not this guard's).
    """
    keys: list[str] = []
    while isinstance(node, ast.Subscript):
        index = node.slice
        if not (isinstance(index, ast.Constant) and isinstance(index.value, str)):
            return None
        keys.append(index.value)
        node = node.value
    root = node.id if isinstance(node, ast.Name) else None
    return root, tuple(reversed(keys))


def _outermost_subscripts(tree: ast.AST) -> list[ast.Subscript]:
    inner = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Subscript)
    }
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript) and id(node) not in inner
    ]


def _render(name: str, path: tuple[str, ...]) -> str:
    return name + "".join("[0]" if key == _ELEMENT else f"[{key!r}]" for key in path)


def _read(
    response: object, path: tuple[str, ...]
) -> tuple[object, tuple[str, ...], str | None]:
    """Walk ``path`` through a measured response; report the first miss."""
    node = response
    for depth, step in enumerate(path):
        where = path[:depth]
        if step == _ELEMENT:
            if not isinstance(node, list):
                return None, where, "is not a list"
            if not node:
                return (
                    None,
                    where,
                    (
                        "is an empty list on the measured session, so no element "
                        "key can be checked; grow the fixture until it is populated"
                    ),
                )
            node = node[0]
        else:
            if not isinstance(node, dict):
                return None, where, "is not a mapping"
            if step not in node:
                return (
                    None,
                    where,
                    (f"carries no key {step!r}; live keys: {sorted(node)}"),
                )
            node = node[step]
    return node, path, None


def _literal_failures(
    where: str,
    tool: str,
    parameter: str,
    literal: str,
    schema: ToolSchema,
    session: MeasuredSession,
) -> list[str]:
    """Claim 2 on one keyword literal, resolved against the parameter's owner."""
    enum = schema.enums.get(parameter)
    if enum:
        if literal in enum:
            return []
        return [
            f"{where} hands {tool}.{parameter} {literal!r}, which is not one of "
            f"its live values {sorted(enum)}"
        ]
    if parameter.endswith(_RUN_ID_SUFFIX):
        refusal = session.resolve_run_id(literal)
        if refusal is None:
            return []
        return [
            f"{where} hands {tool}.{parameter} {literal!r}, which the live run "
            f"store refuses while a latest run exists: {refusal}"
        ]
    if parameter == "root" and not Path(literal).is_absolute():
        return [f"{where} hands {tool}.root {literal!r}, which is not absolute"]
    return []


def example_failures(
    document: str,
    schemas: Mapping[str, ToolSchema],
    session: MeasuredSession,
) -> list[str]:
    """Claims 1-3 over every fenced Python example, read as one narrative."""
    failures: list[str] = []
    bindings: dict[str, Binding] = {}

    def resolve(node: ast.expr, line: int, *, report: bool) -> Binding | None:
        chain = _chain(node)
        if chain is None:
            return None
        name, keys = chain
        if name is None:
            return None
        bound = bindings.get(name)
        if bound is None:
            if report:
                failures.append(
                    f"line {line} reads `{_render(name, keys)}`, but no example "
                    f"bound `{name}` to a tool response"
                )
            return None
        return Binding(bound.tool, bound.path + keys)

    def check_read(bound: Binding, rendered: str, line: int) -> None:
        response = session.responses.get(bound.tool)
        if response is None:
            where: tuple[str, ...] = ()
            miss: str | None = "was not produced by the measured session; extend it"
        else:
            _, where, miss = _read(response, bound.path)
        if miss is not None:
            failures.append(
                f"line {line} reads `{rendered}`, but the {bound.tool} response "
                f"at `{_render(bound.tool, where)}` {miss}"
            )

    def check_call(node: ast.Call, line: int) -> None:
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in schemas):
            return
        tool, schema = func.id, schemas[func.id]
        where = f"line {line} `{tool}(...)`"
        if node.args:
            failures.append(
                f"{where} passes {len(node.args)} positional argument(s), which "
                f"cannot be attributed to a parameter"
            )
        for keyword in node.keywords:
            if keyword.arg is None:
                failures.append(f"{where} unpacks **kwargs, which is unreadable")
            elif keyword.arg not in schema.accepted:
                failures.append(
                    f"{where} names {keyword.arg!r}, which {tool} does not accept; "
                    f"live parameters: {sorted(schema.accepted)}"
                )
            elif isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, str
            ):
                failures.extend(
                    _literal_failures(
                        where, tool, keyword.arg, keyword.value.value, schema, session
                    )
                )

    def check_subscript(node: ast.Subscript, line: int) -> None:
        chain = _chain(node)
        if chain is None:
            failures.append(f"line {line} subscripts with a non-literal key")
            return
        root, keys = chain
        if root is None:
            return
        bound = resolve(node, line, report=True)
        if bound is not None:
            check_read(bound, _render(root, keys), line)

    def bind(name: str, node: ast.expr, *suffix: str) -> None:
        """Bind ``name`` to what ``node`` reads, plus an optional path suffix."""
        bound = resolve(node, 0, report=False)
        if bound is not None:
            bindings[name] = Binding(bound.tool, (*bound.path, *suffix))

    def visit(node: ast.AST, first_line: int, *, in_chain: bool) -> None:
        """In-order walk: a loop binds its variable before its body is read."""
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            bind(node.target.id, node.iter, _ELEMENT)
        if isinstance(node, ast.Call):
            check_call(node, first_line + node.lineno - 1)
        if isinstance(node, ast.Subscript) and not in_chain:
            check_subscript(node, first_line + node.lineno - 1)
        for child in ast.iter_child_nodes(node):
            visit(child, first_line, in_chain=isinstance(node, ast.Subscript))
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target, value = node.targets[0].id, node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                if value.func.id in schemas:
                    bindings[target] = Binding(value.func.id, ())
            elif isinstance(value, ast.Subscript):
                bind(target, value)

    for first_line, source in _fenced_python(document):
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            failures.append(
                f"line {first_line + (exc.lineno or 1) - 1} is a published "
                f"example nobody can run: {exc.msg}"
            )
            continue
        visit(tree, first_line, in_chain=False)
    return failures


def prose_lines(document: str) -> tuple[tuple[int, str], ...]:
    """Numbered lines outside fenced code blocks."""
    kept: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(document.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            kept.append((number, line))
    return tuple(kept)


def parse_prose_value_claims(
    document: str,
    schemas: Mapping[str, ToolSchema],
) -> tuple[ProseValueClaim, ...]:
    """Every token prose offers as an accepted value, by shape.

    A token that is itself a tool or a parameter name is a name, not a value,
    and is not a claim here; the signature guard owns names.
    """
    names = set(schemas) | {p for s in schemas.values() for p in s.accepted}
    parameters = {p for s in schemas.values() for p in s.accepted}
    claims: list[ProseValueClaim] = []
    for number, line in prose_lines(document):
        for match in _QUALIFIED.finditer(line):
            parameter = match.group(1)
            if parameter not in parameters:
                continue
            claims.extend(
                ProseValueClaim(number, token, parameter)
                for token in _BARE.findall(match.group(2))
                if token not in names
            )
        for match in _DISJUNCTION.finditer(line):
            preceding = [
                token
                for token in _BARE.findall(line[: match.start()])
                if token in parameters
            ]
            parameter = preceding[-1] if preceding else None
            claims.extend(
                ProseValueClaim(number, token, parameter)
                for token in match.groups()
                if token not in names
            )
    return tuple(claims)


def prose_value_failures(
    document: str,
    schemas: Mapping[str, ToolSchema],
    session: MeasuredSession,
) -> list[str]:
    """Claim 2 over prose: each offered value must have a live owner."""
    live_values = {
        value
        for schema in schemas.values()
        for values in (*schema.enums.values(), frozenset(schema.defaults.values()))
        for value in values
    }
    failures: list[str] = []
    for claim in parse_prose_value_claims(document, schemas):
        where = f"line {claim.line} offers `{claim.value}`"
        if claim.parameter is None:
            if claim.value not in live_values:
                failures.append(f"{where} as a value, but no tool accepts it")
            continue
        parameter = claim.parameter
        enum = frozenset[str]().union(
            *(s.enums.get(parameter, frozenset()) for s in schemas.values())
        )
        if enum:
            if claim.value not in enum:
                failures.append(
                    f"{where} for `{parameter}`, which accepts {sorted(enum)}"
                )
        elif parameter.endswith(_RUN_ID_SUFFIX):
            refusal = session.resolve_run_id(claim.value)
            if refusal is not None:
                failures.append(
                    f"{where} for `{parameter}`, which the live run store refuses "
                    f"while a latest run exists: {refusal}"
                )
        elif parameter == "root" and not Path(claim.value).is_absolute():
            failures.append(f"{where} for `root`, which is not absolute")
    return failures


def _complex_function(name: str, branches: int) -> str:
    body = "\n".join(
        f"    if x == {i}:\n        y += {i}\n    elif x > {i * 10}:\n        y -= {i}"
        for i in range(branches)
    )
    return f"def {name}(x, y):\n{body}\n    return y\n"


def _write_measured_repo(root: Path) -> None:
    """Enough clones and complexity that the triage hotspot list is populated."""
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for index in range(6):
        (package / f"mod{index}.py").write_text(
            "import json\nimport os\nimport sys\n"
            + _complex_function(f"f{index}", 14)
            + "\n"
            + _complex_function(f"g{index}", 14)
            + "\ndef h(a, b):\n    total = 0\n    for k in range(a):\n"
            "        total += k * b\n    return total\n",
            encoding="utf-8",
        )


@pytest.fixture(scope="module")
def live_schemas() -> dict[str, ToolSchema]:
    """Read every registered tool's input schema from ``list_tools()``."""
    pytest.importorskip("mcp.server.fastmcp")

    from codeclone.surfaces.mcp.server import build_mcp_server

    server = build_mcp_server(history_limit=4)
    schemas: dict[str, ToolSchema] = {}
    for tool in asyncio.run(server.list_tools()):
        properties = (tool.inputSchema or {}).get("properties") or {}
        schemas[tool.name] = ToolSchema(
            accepted=frozenset(properties),
            enums={
                name: values
                for name, spec in properties.items()
                if (values := _enum_values(spec))
            },
            defaults={
                name: str(spec["default"])
                for name, spec in properties.items()
                if isinstance(spec, dict) and isinstance(spec.get("default"), str)
            },
        )
    return schemas


@pytest.fixture(scope="module")
def measured_session(tmp_path_factory: pytest.TempPathFactory) -> MeasuredSession:
    """One real session on a fixture repository: analyze, triage, start, finish.

    The tools here are the ones the reference page's examples call. An
    example calling another tool is reported by ``example_failures`` with the
    instruction to extend this session, never passed over.
    """
    root = tmp_path_factory.mktemp("measured") / "repo"
    _write_measured_repo(root)
    resolved = str(root.resolve())
    service = CodeCloneMCPService(history_limit=4)
    request = MCPAnalysisRequest(root=resolved, respect_pyproject=False)
    analyzed = service.analyze_repository(request)
    run_id = str(analyzed["run_id"])
    triage = service.get_production_triage(run_id=run_id, root=resolved)
    started = service.start_controlled_change(
        root=resolved,
        scope={"allowed_files": ["pkg/mod0.py"]},
        intent="measure the response shapes the reference page reads",
    )
    touched = root / "pkg" / "mod0.py"
    touched.write_text(
        touched.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8"
    )
    after = service.analyze_repository(request)
    finished = service.finish_controlled_change(
        intent_id=started["intent_id"],
        changed_files=["pkg/mod0.py"],
        after_run_id=str(after["run_id"]),
    )

    def resolve_run_id(literal: str) -> str | None:
        try:
            service.get_run_summary(literal, root=resolved)
        except (
            session_shared.MCPRunNotFoundError,
            session_shared.MCPRunRootMismatchError,
            session_shared.MCPRunRootAmbiguityError,
            session_shared.MCPServiceContractError,
        ) as exc:
            return str(exc)
        return None

    return MeasuredSession(
        root=resolved,
        responses={
            "analyze_repository": analyzed,
            "get_production_triage": triage,
            "start_controlled_change": started,
            "finish_controlled_change": finished,
        },
        resolve_run_id=resolve_run_id,
    )


def _name(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _prefixed(path: Path, failures: list[str]) -> str:
    return "\n".join(f"{_name(path)}:{failure}" for failure in failures)


@pytest.mark.parametrize("doc_path", _DOC_PATHS, ids=_name)
def test_fenced_examples_match_the_live_server_and_its_responses(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
    measured_session: MeasuredSession,
) -> None:
    failures = example_failures(
        doc_path.read_text(encoding="utf-8"), live_schemas, measured_session
    )
    assert not failures, _prefixed(doc_path, failures)


@pytest.mark.parametrize("doc_path", _PROSE_VALUE_DOCS, ids=_name)
def test_prose_offers_only_values_the_server_accepts(
    doc_path: Path,
    live_schemas: dict[str, ToolSchema],
    measured_session: MeasuredSession,
) -> None:
    failures = prose_value_failures(
        doc_path.read_text(encoding="utf-8"), live_schemas, measured_session
    )
    assert not failures, _prefixed(doc_path, failures)


def test_the_reference_page_examples_are_a_real_population(
    live_schemas: dict[str, ToolSchema],
) -> None:
    """The example guard must have read calls and reads, not an empty page."""
    document = _REFERENCE_DOC.read_text(encoding="utf-8")
    blocks = _fenced_python(document)
    assert blocks, "the reference page publishes no fenced Python example"
    calls = 0
    reads = 0
    for _, source in blocks:
        tree = ast.parse(source)
        calls += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in live_schemas
        )
        reads += len(_outermost_subscripts(tree))
    assert calls >= 4, f"only {calls} tool calls were read from the examples"
    assert reads >= 4, f"only {reads} response reads were read from the examples"


def test_the_measured_session_hotspot_list_is_populated(
    measured_session: MeasuredSession,
) -> None:
    """The element checks below run on a real card, not on an empty list."""
    _, _, miss = _read(
        measured_session.responses["get_production_triage"],
        ("top_hotspots", "items", _ELEMENT),
    )
    assert miss is None, miss


def _synthetic_session(
    responses: Mapping[str, Mapping[str, object]],
    refused: frozenset[str] = frozenset(),
) -> MeasuredSession:
    return MeasuredSession(
        root="/synthetic",
        responses=responses,
        resolve_run_id=lambda literal: (
            f"No matching MCP analysis run is available for {literal!r}."
            if literal in refused
            else None
        ),
    )


def _fence(*lines: str) -> str:
    return "```python\n" + "\n".join(lines) + "\n```\n"


def test_an_invented_keyword_in_an_example_is_reported(
    live_schemas: dict[str, ToolSchema],
    measured_session: MeasuredSession,
) -> None:
    document = _fence('r = analyze_repository(root="/repo", cache_policy="reuse")')
    failures = example_failures(document, live_schemas, measured_session)
    assert failures == [
        "line 2 `analyze_repository(...)` names 'cache_policy', which "
        "analyze_repository does not accept; live parameters: "
        f"{sorted(live_schemas['analyze_repository'].accepted)}"
    ]


def test_a_run_id_literal_the_store_refuses_is_reported(
    live_schemas: dict[str, ToolSchema],
    measured_session: MeasuredSession,
) -> None:
    """The store is the validator: ``latest`` is refused, a real id is not.

    Both directions are held. Reverting the resolver check makes the first
    assertion pass vacuously; a resolver that refuses everything makes the
    second fail. The real id comes from the measured session itself.
    """
    refused = example_failures(
        _fence('t = get_production_triage(run_id="latest")'),
        live_schemas,
        measured_session,
    )
    assert len(refused) == 1
    assert refused[0].startswith(
        "line 2 `get_production_triage(...)` hands get_production_triage.run_id "
        "'latest', which the live run store refuses while a latest run exists: "
    )
    real = str(measured_session.responses["analyze_repository"]["run_id"])
    accepted = example_failures(
        _fence(f't = get_production_triage(run_id="{real}")'),
        live_schemas,
        measured_session,
    )
    assert accepted == []


def test_an_enum_literal_outside_the_live_values_is_reported(
    live_schemas: dict[str, ToolSchema],
) -> None:
    session = _synthetic_session({})
    enum_tool = next(
        (name, parameter, values)
        for name, schema in sorted(live_schemas.items())
        for parameter, values in sorted(schema.enums.items())
    )
    name, parameter, values = enum_tool
    wrong = example_failures(
        _fence(f'x = {name}({parameter}="no_such_value")'), live_schemas, session
    )
    assert wrong == [
        f"line 2 `{name}(...)` hands {name}.{parameter} 'no_such_value', which is "
        f"not one of its live values {sorted(values)}"
    ]
    right = example_failures(
        _fence(f'x = {name}({parameter}="{sorted(values)[0]}")'),
        live_schemas,
        session,
    )
    assert right == []


def test_a_response_key_the_tool_does_not_carry_is_reported(
    live_schemas: dict[str, ToolSchema],
) -> None:
    session = _synthetic_session(
        {"analyze_repository": {"run_id": "ab12cd34", "health": {"score": 81}}}
    )
    document = _fence(
        'result = analyze_repository(root="/repo")',
        "print(result['health_score'])",
        "print(result['health']['grade'])",
    )
    assert example_failures(document, live_schemas, session) == [
        "line 3 reads `result['health_score']`, but the analyze_repository "
        "response at `analyze_repository` carries no key 'health_score'; live "
        "keys: ['health', 'run_id']",
        "line 4 reads `result['health']['grade']`, but the analyze_repository "
        "response at `analyze_repository['health']` carries no key 'grade'; "
        "live keys: ['score']",
    ]
    fine = _fence(
        'result = analyze_repository(root="/repo")',
        "print(result['health']['score'])",
    )
    assert example_failures(fine, live_schemas, session) == []


def test_a_loop_over_an_empty_list_is_reported_not_passed(
    live_schemas: dict[str, ToolSchema],
) -> None:
    """No element, no evidence: an empty population must not pass a key check."""
    empty = _synthetic_session(
        {"get_production_triage": {"top_hotspots": {"items": []}}}
    )
    document = _fence(
        'triage = get_production_triage(root="/repo")',
        'for card in triage["top_hotspots"]["items"]:',
        "    print(card['kind'])",
    )
    failures = example_failures(document, live_schemas, empty)
    assert len(failures) == 1
    assert failures[0].startswith(
        "line 4 reads `card['kind']`, but the get_production_triage response at "
        "`get_production_triage['top_hotspots']['items']` is an empty list"
    )
    populated = _synthetic_session(
        {"get_production_triage": {"top_hotspots": {"items": [{"kind": "x"}]}}}
    )
    assert example_failures(document, live_schemas, populated) == []


def test_examples_are_read_as_one_narrative_in_document_order(
    live_schemas: dict[str, ToolSchema],
) -> None:
    """A name bound in one block is what a later block means by it."""
    session = _synthetic_session(
        {
            "analyze_repository": {"run_id": "ab12cd34"},
            "get_production_triage": {"run_id": "ab12cd34"},
        }
    )
    document = (
        _fence('result = analyze_repository(root="/repo")')
        + "Prose between the examples.\n"
        + _fence('triage = get_production_triage(run_id=result["run_id"])')
    )
    assert example_failures(document, live_schemas, session) == []
    unbound = _fence('triage = get_production_triage(run_id=result["run_id"])')
    assert example_failures(unbound, live_schemas, session) == [
        "line 2 reads `result['run_id']`, but no example bound `result` to a "
        "tool response"
    ]


def test_a_tool_the_session_did_not_run_is_reported_not_skipped(
    live_schemas: dict[str, ToolSchema],
) -> None:
    session = _synthetic_session({})
    document = _fence('gates = evaluate_gates(root="/repo")', "print(gates['status'])")
    assert example_failures(document, live_schemas, session) == [
        "line 3 reads `gates['status']`, but the evaluate_gates response at "
        "`evaluate_gates` was not produced by the measured session; extend it"
    ]


def test_a_prose_value_no_parameter_accepts_is_reported(
    live_schemas: dict[str, ToolSchema],
) -> None:
    session = _synthetic_session({})
    offered = "MCP respects cache policy settings (`reuse` or `off`)."
    assert prose_value_failures(offered, live_schemas, session) == [
        "line 1 offers `reuse` as a value, but no tool accepts it",
        "line 1 offers `off` as a value, but no tool accepts it",
    ]
    qualified = (
        "Analysis tools accept a cache policy: `reuse` (use cached results if "
        "fresh) or `off` (ignore cache)."
    )
    assert prose_value_failures(qualified, live_schemas, session) == [
        "line 1 offers `reuse` as a value, but no tool accepts it",
        "line 1 offers `off` as a value, but no tool accepts it",
    ]
    live = "A candidate is typed `risk_note` or `change_rationale`."
    assert prose_value_failures(live, live_schemas, session) == []
    names = "Pass `changed_paths` or `git_diff_ref`, never both."
    assert prose_value_failures(names, live_schemas, session) == []


def test_a_prose_value_offered_under_run_id_is_resolved_by_the_store(
    live_schemas: dict[str, ToolSchema],
) -> None:
    session = _synthetic_session({}, refused=frozenset({"latest"}))
    offered = (
        "Inspection tools take a `run_id` (8-char short id or full digest, or "
        "`latest` for the session-local run)."
    )
    assert prose_value_failures(offered, live_schemas, session) == [
        "line 1 offers `latest` for `run_id`, which the live run store refuses "
        "while a latest run exists: No matching MCP analysis run is available "
        "for 'latest'."
    ]
    accepted = "Inspection tools take a `run_id` (`ab12cd34` or the full digest)."
    assert prose_value_failures(accepted, live_schemas, session) == []
    other = "Sections: `inventory` (file registry), `findings` (grouped)."
    assert parse_prose_value_claims(other, live_schemas) == ()
