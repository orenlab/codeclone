# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The engine fence: a process must not answer for code the disk no longer holds.

Every probe here fakes exactly two things and nothing else: the *loaded*
generation (a process-start capture that no in-process test can honestly
produce) and the location of the package root. The digest itself is always the
real :func:`compute_code_provenance` reading real files off disk, so a fence
that silently stopped deriving content would not survive these tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from codeclone.api.execution_event import (
    ExecutionEvent,
    digest_source_state,
    digest_workspace,
)
from codeclone.surfaces.mcp import _engine_fence
from codeclone.surfaces.mcp._code_provenance import compute_code_provenance
from codeclone.surfaces.mcp._engine_fence import (
    ENGINE_CHANGED_DURING_OPERATION,
    STALE_ENGINE,
    EngineChangedDuringOperationError,
    StaleEngineError,
    disk_engine_generation,
    engine_fence,
    fenced_server_class,
)
from codeclone.surfaces.mcp.server import build_mcp_server

# ---------------------------------------------------------------------------
# Fixtures: a real, tiny package tree whose content digest is real.
# ---------------------------------------------------------------------------


def _write_engine_tree(root: Path, *, marker: str) -> Path:
    """A minimal package directory whose ``*.py`` content is under our control."""

    package = root / "codeclone"
    (package / "surfaces").mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(f'__version__ = "{marker}"\n')
    (package / "surfaces" / "__init__.py").write_text(f"MARKER = {marker!r}\n")
    return package


def _pin_engine(
    monkeypatch: pytest.MonkeyPatch,
    *,
    package_root: Path,
    loaded_generation: str,
) -> None:
    """Point the fence at ``package_root`` and pin what this process 'loaded'.

    ``package_source_root`` and ``process_code_provenance`` are the only two
    reads replaced. ``compute_code_provenance`` -- the derivation the whole
    contract rests on -- stays real and keeps hashing the bytes on disk.
    """

    provenance: Mapping[str, str] = MappingProxyType(
        {
            "code_digest": loaded_generation,
            "source": "source_tree",
            "source_root": str(package_root),
        }
    )
    monkeypatch.setattr(_engine_fence, "package_source_root", lambda: package_root)
    monkeypatch.setattr(_engine_fence, "process_code_provenance", lambda: provenance)


@pytest.fixture
def engine_tree(tmp_path: Path) -> Path:
    return _write_engine_tree(tmp_path / "loaded", marker="v1")


# ---------------------------------------------------------------------------
# 1. The entry fence fires, and the operation does not execute.
# ---------------------------------------------------------------------------


def test_stale_engine_refuses_and_the_body_never_runs(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """A refusal raised *after* the work ran is not this contract.

    The executed flag is the whole point: a fence that answered "stale" while
    having already produced the answer would have served the stale engine's
    result on every path that swallows the exception.
    """

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation="sha256:a-generation-this-tree-never-had",
    )
    executed: list[str] = []

    with pytest.raises(StaleEngineError) as raised, engine_fence("tool x"):
        executed.append("body")

    assert executed == []
    assert raised.value.code == STALE_ENGINE
    assert str(raised.value).startswith(f"{STALE_ENGINE}: ")


def test_stale_engine_refusal_names_both_generations_and_the_loaded_root(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """One digest cannot be checked by its reader; the pair is the evidence."""

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation="sha256:stale",
    )
    on_disk = compute_code_provenance(engine_tree)["code_digest"]

    with pytest.raises(StaleEngineError) as raised, engine_fence("tool get_finding"):
        pass

    message = str(raised.value)
    assert "sha256:stale" in message
    assert on_disk in message
    assert str(engine_tree) in message
    assert "Restart" in message


# ---------------------------------------------------------------------------
# 2. The entry fence does not over-fire.
# ---------------------------------------------------------------------------


def test_matching_generation_runs_the_operation_untouched(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """The opposite boundary: an engine that matches must not be refused."""

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation=compute_code_provenance(engine_tree)["code_digest"],
    )
    executed: list[str] = []

    with engine_fence("tool analyze_repository") as observed:
        executed.append("body")

    assert executed == ["body"]
    assert observed == compute_code_provenance(engine_tree)["code_digest"]


# ---------------------------------------------------------------------------
# 3. The during-operation fence.
# ---------------------------------------------------------------------------


def test_engine_change_during_the_operation_withholds_the_result(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """The checkout moved mid-flight: the result exists and is not published.

    The mutation is a real edit to a real file under the loaded root, so the
    second reading differs for the same reason a landed commit would make it
    differ -- content, not a stubbed return value.
    """

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation=compute_code_provenance(engine_tree)["code_digest"],
    )
    published: list[str] = []

    def _operation() -> str:
        with engine_fence("tool analyze_repository"):
            (engine_tree / "surfaces" / "__init__.py").write_text("MARKER = 'v2'\n")
            result = "analysis result"
        published.append(result)
        return result

    with pytest.raises(EngineChangedDuringOperationError) as raised:
        _operation()

    assert published == []
    assert raised.value.code == ENGINE_CHANGED_DURING_OPERATION
    assert str(raised.value).startswith(f"{ENGINE_CHANGED_DURING_OPERATION}: ")


def test_a_stable_engine_publishes_the_result(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """The other boundary of the during-operation check."""

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation=compute_code_provenance(engine_tree)["code_digest"],
    )
    published: list[str] = []

    with engine_fence("tool analyze_repository"):
        pass
    published.append("analysis result")

    assert published == ["analysis result"]


def test_a_same_size_edit_restored_within_one_second_is_still_seen(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """The generation is content-bound, so a stat-invisible edit is still seen.

    This is the exact shape that poisons a mutation battery in this repository:
    equal length, written and restored inside a single second, so ``(mtime,
    size)`` cannot tell the two trees apart. A stat-keyed generation would be
    blind here by construction.
    """

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation=compute_code_provenance(engine_tree)["code_digest"],
    )
    target = engine_tree / "surfaces" / "__init__.py"
    original = target.read_bytes()
    mutated = original.replace(b"'v1'", b"'v2'")
    assert len(mutated) == len(original)

    stat_before = target.stat()
    target.write_bytes(mutated)
    with pytest.raises(StaleEngineError), engine_fence("tool analyze_repository"):
        pass

    target.write_bytes(original)
    import os

    os.utime(target, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    assert target.stat().st_size == stat_before.st_size
    with engine_fence("tool analyze_repository"):
        pass


# ---------------------------------------------------------------------------
# 4. Coverage: every executing entry point, not the one the test was written on.
# ---------------------------------------------------------------------------


def _fenced_calls(monkeypatch: pytest.MonkeyPatch, *, generation: str) -> list[str]:
    """Replace the disk reading with a recorder returning ``generation``.

    Deliberately a stub *here and only here*: this probe asks whether the fence
    is consulted at each of the 47 entry points, and answering that 47 times
    over the real 584-file tree buys nothing the single-entry-point probes above
    do not already prove.
    """

    consulted: list[str] = []

    def _record() -> str:
        consulted.append("disk")
        return generation

    monkeypatch.setattr(_engine_fence, "disk_engine_generation", _record)
    monkeypatch.setattr(
        _engine_fence,
        "process_code_provenance",
        lambda: MappingProxyType(
            {
                "code_digest": "sha256:loaded-by-this-process",
                "source": "source_tree",
                "source_root": "/loaded/root",
            }
        ),
    )
    return consulted


def _entry_points(mcp: object) -> tuple[list[str], list[str]]:
    """Every published tool, and every resource URI a client can ask for.

    Templates are materialised with placeholder ids rather than skipped: a
    templated resource is an entry point a client can invoke, and a fence that
    covered only the static six would leave it open.
    """

    tools = [tool.name for tool in asyncio.run(mcp.list_tools())]  # type: ignore[attr-defined]
    resources = [str(res.uri) for res in asyncio.run(mcp.list_resources())]  # type: ignore[attr-defined]
    for template in asyncio.run(mcp.list_resource_templates()):  # type: ignore[attr-defined]
        uri = template.uriTemplate
        uri = uri.replace("{run_id}", "abcd1234").replace("{finding_id}", "f-1")
        resources.append(uri)
    return tools, resources


def _ran_without_fence_refusal(handler: object, *args: object) -> bool:
    """Did this entry point reach its handler and finish?

    Any other failure is fine and expected -- these calls carry no arguments.
    The one failure that must not happen is a stale-engine refusal, and it is
    checked by type *and* by message so a refusal re-raised as something else
    would still be caught.
    """

    try:
        asyncio.run(handler(*args))  # type: ignore[operator]
    except Exception as exc:
        assert not isinstance(exc, StaleEngineError), args
        assert STALE_ENGINE not in str(exc), args
        return False
    return True


def test_every_executing_entry_point_consults_the_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Population proof, reconciled by number rather than by a spot check.

    A guard wired at one call site, or keyed to a handler's name, is blind by
    construction -- measured twice in this repository. So the assertion runs
    over the *published* population: whatever ``list_tools`` and
    ``list_resources`` advertise is what a client can invoke, and every one of
    them must refuse.
    """

    mcp = build_mcp_server(ide_governance_channel=True)
    tools, resources = _entry_points(mcp)
    assert len(tools) + len(resources) > 40, (tools, resources)

    consulted = _fenced_calls(monkeypatch, generation="sha256:disk-has-moved-on")

    refused: list[str] = []
    for name in tools:
        with pytest.raises(StaleEngineError):
            asyncio.run(mcp.call_tool(name, {}))
        refused.append(name)
    for uri in resources:
        with pytest.raises(StaleEngineError):
            asyncio.run(mcp.read_resource(uri))
        refused.append(uri)

    assert refused == [*tools, *resources]
    assert len(consulted) == len(refused)


def test_no_entry_point_over_fires_when_the_engine_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same population, the other boundary.

    Calls with no arguments still fail -- on argument validation, on a missing
    run, on whatever each handler decides. What none of them may do is fail as
    a stale engine.
    """

    mcp = build_mcp_server(ide_governance_channel=True)
    tools, resources = _entry_points(mcp)
    consulted = _fenced_calls(monkeypatch, generation="sha256:loaded-by-this-process")

    completed = [
        *(
            name
            for name in tools
            if _ran_without_fence_refusal(mcp.call_tool, name, {})
        ),
        *(
            uri
            for uri in resources
            if _ran_without_fence_refusal(mcp.read_resource, uri)
        ),
    ]

    # Exact reconciliation rather than a lower bound: one entry reading for
    # every entry point, plus one closing reading for each handler that ran to
    # completion. A handler that raised has no result to withhold, so the
    # closing check is deliberately not taken for it.
    assert len(consulted) == len(tools) + len(resources) + len(completed)
    assert completed, "no handler completed; the over-fire direction is unproven"


def base_call_tool(mcp: object) -> object:
    """The ``call_tool`` the fence composed over, read off the class below it."""

    return type(mcp).__mro__[1].call_tool  # type: ignore[attr-defined]


def test_the_fence_is_the_outermost_layer_of_the_served_class() -> None:
    """Placement, not just presence: above the argument diagnosis, not below.

    A stale engine's reading of the caller's arguments is worth no more than
    its analysis, so the refusal must come first.
    """

    mcp = build_mcp_server()
    mro = [klass.__name__ for klass in type(mcp).__mro__]
    assert mro[0] == "_EngineFencedFastMCP"
    assert "_RunIdDiagnosingFastMCP" in mro
    assert mro.index("_EngineFencedFastMCP") < mro.index("_RunIdDiagnosingFastMCP")
    # Ownership, not a name: the two served entry points must come from the
    # fence module, whatever the wrapper factory happens to be called.
    fence_module = _engine_fence.__name__
    assert type(mcp).call_tool.__module__ == fence_module
    assert type(mcp).read_resource.__module__ == fence_module
    assert type(mcp).call_tool is not base_call_tool(mcp)


def test_fencing_covers_both_executing_methods_and_only_those() -> None:
    """The two request kinds that execute are overridden; catalogue reads are not.

    ``list_tools`` stays unfenced on purpose: the diagnosing layer calls it
    from *inside* a fenced ``call_tool`` to build a refusal.
    """

    class _Base:
        async def call_tool(self) -> None: ...
        async def read_resource(self) -> None: ...
        async def list_tools(self) -> None: ...
        async def list_resources(self) -> None: ...

    fenced = fenced_server_class(_Base)  # type: ignore[arg-type]
    overridden = {name for name in vars(fenced) if not name.startswith("__")}
    assert overridden == {"call_tool", "read_resource"}


# ---------------------------------------------------------------------------
# 5. The comparison is bound to the loaded package root.
# ---------------------------------------------------------------------------


def test_the_disk_reading_follows_the_loaded_root_not_the_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A sibling tree that still holds the loaded generation must not absolve it.

    The configuration is the measured one: an editable finder rooted at the
    main checkout while the request names a worktree, so "the code I am
    running" and "the tree I was pointed at" are different objects. ``loaded``
    is a copy of what this process imported; ``sibling`` still holds it, and
    the tree actually imported has moved on. A fence that measured the sibling
    would report all clear while the engine underneath had changed.
    """

    loaded = _write_engine_tree(tmp_path / "loaded", marker="v1")
    sibling = _write_engine_tree(tmp_path / "sibling", marker="v1")
    loaded_generation = compute_code_provenance(loaded)["code_digest"]
    assert compute_code_provenance(sibling)["code_digest"] == loaded_generation

    _pin_engine(
        monkeypatch,
        package_root=loaded,
        loaded_generation=loaded_generation,
    )
    (loaded / "surfaces" / "__init__.py").write_text("MARKER = 'v2'\n")
    monkeypatch.chdir(sibling.parent)

    assert disk_engine_generation() != loaded_generation
    assert compute_code_provenance(sibling)["code_digest"] == loaded_generation
    with pytest.raises(StaleEngineError), engine_fence("tool analyze_repository"):
        pass


def test_the_disk_reading_is_never_memoised(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """Two readings of a changed tree must differ; a cache would hide the change."""

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation=compute_code_provenance(engine_tree)["code_digest"],
    )
    first = disk_engine_generation()
    (engine_tree / "surfaces" / "__init__.py").write_text("MARKER = 'v2'\n")
    assert disk_engine_generation() != first


# ---------------------------------------------------------------------------
# Fail-closed, and the one configuration that cannot be fenced.
# ---------------------------------------------------------------------------


def test_an_unreadable_root_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    engine_tree: Path,
) -> None:
    """Sources that stop being readable refuse the call instead of guessing."""

    _pin_engine(
        monkeypatch,
        package_root=engine_tree,
        loaded_generation=compute_code_provenance(engine_tree)["code_digest"],
    )
    monkeypatch.setattr(
        _engine_fence,
        "package_source_root",
        lambda: engine_tree / "does-not-exist",
    )
    with pytest.raises(StaleEngineError), engine_fence("tool analyze_repository"):
        pass


def test_a_source_free_install_cannot_be_fenced_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A compiled-only install digests to ``unknown`` on both sides.

    Pinned so the hole stays deliberate: there is nothing to compare, the two
    honest unknowns agree, and the operation runs. This is a property of the
    install, not a defect of the gate.
    """

    empty = tmp_path / "compiled_only"
    empty.mkdir()
    _pin_engine(monkeypatch, package_root=empty, loaded_generation="unknown")
    executed: list[str] = []

    with engine_fence("tool analyze_repository"):
        executed.append("body")

    assert executed == ["body"]
    assert disk_engine_generation() == "unknown"


# ---------------------------------------------------------------------------
# Receipt provenance never becomes semantic truth.
# ---------------------------------------------------------------------------


def _event(*, code_digest: str, manifest: dict[str, str]) -> ExecutionEvent:
    return ExecutionEvent(
        execution_event_id="exec-1",
        root=Path("/repo"),
        semantic_report_id="run-1",
        content_manifest=manifest,
        code_digest=code_digest,
    )


def test_engine_provenance_does_not_enter_the_execution_witnesses() -> None:
    """The witnesses describe what a run READ, never what read it.

    Checked as the claim rather than through a proxy: two events over the same
    bytes, differing only in the engine that produced them, must witness
    identically -- otherwise two builds could never be compared. The second
    pair is the positive control, and it proves this probe can see a
    difference at all: change what the run read, and both witnesses move.
    """

    manifest = {"a.py": "sha256:aaa", "b.py": "sha256:bbb"}
    one_engine = _event(code_digest="sha256:engine-one", manifest=dict(manifest))
    other_engine = _event(code_digest="sha256:engine-two", manifest=dict(manifest))
    assert one_engine.code_digest != other_engine.code_digest
    assert one_engine.source_state_digest == other_engine.source_state_digest
    assert one_engine.workspace_witness == other_engine.workspace_witness

    other_bytes = _event(
        code_digest="sha256:engine-one",
        manifest={"a.py": "sha256:aaa", "b.py": "sha256:CHANGED"},
    )
    assert other_bytes.source_state_digest != one_engine.source_state_digest
    assert other_bytes.workspace_witness != one_engine.workspace_witness


def test_the_witness_helpers_are_reachable_and_agree_with_the_event() -> None:
    """The event derives its witnesses from the module-level rules, not beside them."""

    manifest = {"a.py": "sha256:aaa"}
    event = _event(code_digest="sha256:whatever", manifest=manifest)
    source_state = digest_source_state(manifest)
    assert event.source_state_digest == source_state
    assert event.workspace_witness == digest_workspace(
        source_state=source_state,
        dirty_snapshot=None,
    )


def test_receipt_engine_block_is_reported_and_rendered_not_recomputed() -> None:
    """The markdown form spends the value the typed receipt already carries."""

    from codeclone.surfaces.mcp._review_receipt import render_receipt_markdown

    rendered = render_receipt_markdown(
        {
            "provenance": {
                "report_digest": "sha256:report",
                "report_schema_version": "3.3",
                "baseline_status": "trusted",
                "run_id": "abcd1234",
                "root": "/repo",
                "engine": {
                    "generation": "sha256:engine-generation",
                    "loaded_package_root": "/loaded/codeclone",
                    "execution_event_id": "exec-1",
                },
            },
        }
    )
    assert "sha256:engine-generation" in rendered
    assert "/loaded/codeclone" in rendered
    assert "exec-1" in rendered


def test_an_execution_without_engine_provenance_is_named_not_blank() -> None:
    """Empty backticks read as a value; the absence must say it is one."""

    from codeclone.surfaces.mcp._review_receipt import render_receipt_markdown

    rendered = render_receipt_markdown(
        {
            "provenance": {
                "engine": {
                    "generation": "",
                    "loaded_package_root": "",
                    "execution_event_id": "",
                },
            },
        }
    )
    engine_line = next(
        line for line in rendered.splitlines() if line.startswith("**Engine:**")
    )
    assert "``" not in engine_line
    assert engine_line.count("unknown") == 3
