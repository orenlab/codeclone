# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A cached row this reader cannot rebuild refuses its file; it never vanishes.

Rehydration turned a cached row back into a model fact one row at a time, and
every family ended the same way: ``if parsed is not None: append``. A row it
could not rebuild was skipped and the file was still served off the cache, so
the run published a result in which that fact had simply never existed --
measured 2026-10-13 as the pydantic reachability fact on fastapi, and present
in six families of ``load_cached_metrics_extended``, the nested population,
the relationship records and the three optional per-module sections.

The law pinned here is the one the maintainer set for the cache (ruling
2026-10-13, invariant 2): a row the reader cannot rebuild is a typed refusal
of the file's dependent lane -- ``malformed_payload``, counted like every
other lane reason -- and the file is walked again, so the run equals the cold
one. Each family has its own case, because each skip was its own line of code
and each can come back on its own.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import codeclone.core.discovery as core_discovery
from codeclone.cache.backend import TABLE_DEPENDENT
from codeclone.cache.store import Cache
from codeclone.core._types import BootstrapResult, DiscoveryResult, ProcessingResult
from codeclone.core.parallelism import process
from codeclone.models import (
    CacheDependentPayload,
    ClassMetricsDict,
    DeadCandidateDict,
    FunctionRelationshipFactsDict,
    ModuleApiSurfaceDict,
    ModuleDepDict,
    ModuleDocstringCoverageDict,
    ModuleTypingCoverageDict,
    NestedDefinitionDict,
    RuntimeReachabilityFactDict,
    SecuritySurfaceDict,
)
from tests._pipeline_fixtures import analysis_boot, discover_and_process

_MODULE = '''"""Rows in every family a warm run rebuilds."""

import subprocess

from pydantic.json_schema import GenerateJsonSchema


class BytesAsText(GenerateJsonSchema):
    def bytes_schema(self, schema):
        return {"type": "string"}


def run(command):
    def render(value):
        return str(value)

    return subprocess.run(render(command), check=False)
'''

_REFUSED = "cache_lane_dependent_malformed_payload"

Tamper = Callable[[CacheDependentPayload], CacheDependentPayload]


def _first(rows: tuple[object, ...]) -> dict[str, object]:
    """A mutable copy of a family's first row: the source writes one in each."""

    assert rows, "the fixture module no longer writes a row in this family"
    first = rows[0]
    assert isinstance(first, dict)
    return dict(first)


def _class_metrics(payload: CacheDependentPayload) -> CacheDependentPayload:
    row = _first(payload.class_metrics) | {"risk_coupling": "extreme"}
    return replace(
        payload,
        class_metrics=(*payload.class_metrics, cast(ClassMetricsDict, row)),
    )


def _module_deps(payload: CacheDependentPayload) -> CacheDependentPayload:
    # A dependent-hit row without the detail block: the four-column shape the
    # encoder keeps only for a row whose dependent profile already missed.
    row = _first(payload.module_deps)
    del row["resolution"]
    return replace(
        payload, module_deps=(*payload.module_deps, cast(ModuleDepDict, row))
    )


def _dead_candidate_kind(payload: CacheDependentPayload) -> CacheDependentPayload:
    row = _first(payload.dead_candidates) | {"kind": "lambda"}
    return replace(
        payload,
        dead_candidates=(*payload.dead_candidates, cast(DeadCandidateDict, row)),
    )


def _dead_candidate_reason(payload: CacheDependentPayload) -> CacheDependentPayload:
    row = _first(payload.dead_candidates) | {"live_root_reason": "sorcery"}
    return replace(
        payload,
        dead_candidates=(cast(DeadCandidateDict, row), *payload.dead_candidates[1:]),
    )


def _dead_candidate_witness(payload: CacheDependentPayload) -> CacheDependentPayload:
    row = _first(payload.dead_candidates) | {"escape_witness": 7}
    return replace(
        payload,
        dead_candidates=(cast(DeadCandidateDict, row), *payload.dead_candidates[1:]),
    )


def _security_surfaces(payload: CacheDependentPayload) -> CacheDependentPayload:
    row = _first(payload.security_surfaces) | {"category": "telepathy"}
    return replace(
        payload,
        security_surfaces=(
            *payload.security_surfaces,
            cast(SecuritySurfaceDict, row),
        ),
    )


def _reachability_framework(framework: str) -> Tamper:
    """A copy of the module's reachability row, spelling ``framework``."""

    def _tamper(payload: CacheDependentPayload) -> CacheDependentPayload:
        row = _first(payload.runtime_reachability) | {"framework": framework}
        return replace(
            payload,
            runtime_reachability=(
                *payload.runtime_reachability,
                cast(RuntimeReachabilityFactDict, row),
            ),
        )

    return _tamper


def _nested_kind(payload: CacheDependentPayload) -> CacheDependentPayload:
    row = _first(payload.nested_definitions) | {"kind": "import"}
    return replace(
        payload,
        nested_definitions=(
            *payload.nested_definitions,
            cast(NestedDefinitionDict, row),
        ),
    )


def _nested_reason(payload: CacheDependentPayload) -> CacheDependentPayload:
    row = _first(payload.nested_definitions) | {"live_root_reason": "sorcery"}
    return replace(
        payload,
        nested_definitions=(
            cast(NestedDefinitionDict, row),
            *payload.nested_definitions[1:],
        ),
    )


def _relationship_record(**changes: object) -> Tamper:
    """A copy of the first relationship record, changed, filed beside it."""

    def _tamper(payload: CacheDependentPayload) -> CacheDependentPayload:
        facts = _first(payload.function_relationship_facts)
        records = facts["relationships"]
        assert isinstance(records, list) and records
        first_record = records[0]
        assert isinstance(first_record, dict)
        facts["relationships"] = [*records, first_record | changes]
        return replace(
            payload,
            function_relationship_facts=(
                cast(FunctionRelationshipFactsDict, facts),
                *payload.function_relationship_facts[1:],
            ),
        )

    return _tamper


def _typing_coverage(payload: CacheDependentPayload) -> CacheDependentPayload:
    assert payload.typing_coverage is not None
    row = dict(payload.typing_coverage) | {"callable_count": "many"}
    return replace(payload, typing_coverage=cast(ModuleTypingCoverageDict, row))


def _docstring_coverage(payload: CacheDependentPayload) -> CacheDependentPayload:
    assert payload.docstring_coverage is not None
    row = dict(payload.docstring_coverage) | {"public_symbol_total": None}
    return replace(payload, docstring_coverage=cast(ModuleDocstringCoverageDict, row))


def _api_surface(payload: CacheDependentPayload) -> CacheDependentPayload:
    surface = {
        "module": "pkg.mod",
        "filepath": "pkg/mod.py",
        "all_declared": [],
        "symbols": [
            {
                "qualname": "pkg.mod:run",
                "kind": "macro",
                "start_line": 14,
                "end_line": 18,
                "params": [],
                "returns_hash": "",
                "exported_via": "name",
            }
        ],
    }
    return replace(payload, api_surface=cast(ModuleApiSurfaceDict, surface))


#: One case per place a row used to be skipped or a field silently degraded.
_TAMPERS: dict[str, Tamper] = {
    "class_metrics": _class_metrics,
    "module_deps": _module_deps,
    "dead_candidates.kind": _dead_candidate_kind,
    "dead_candidates.live_root_reason": _dead_candidate_reason,
    "dead_candidates.escape_witness": _dead_candidate_witness,
    "security_surfaces": _security_surfaces,
    "runtime_reachability": _reachability_framework("quantum"),
    # A member's spelling, not a member: the case and the edges are the value.
    "runtime_reachability.case": _reachability_framework("Pydantic"),
    "runtime_reachability.padded": _reachability_framework("pydantic "),
    "nested_definitions.kind": _nested_kind,
    "nested_definitions.live_root_reason": _nested_reason,
    "function_relationship_facts": _relationship_record(relation_kind="teleport"),
    # A sound record filed under another function: the container's
    # ``source_qualname`` is the owner, and a record that names a different one
    # was written by a writer this reader does not understand.
    "function_relationship_facts.foreign_source": _relationship_record(
        source_qualname="pkg.mod:BytesAsText.bytes_schema"
    ),
    "typing_coverage": _typing_coverage,
    "docstring_coverage": _docstring_coverage,
    "api_surface": _api_surface,
}


def _boot(root: Path) -> BootstrapResult:
    return analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=False)


def _cold(tmp_path: Path) -> tuple[Path, Path, DiscoveryResult, ProcessingResult]:
    root = tmp_path / "tree"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", "utf-8")
    (root / "pkg" / "mod.py").write_text(_MODULE, "utf-8")
    cache_path = tmp_path / "cache.sqlite3"
    cache, discovery, processing = discover_and_process(
        _boot(root), cache_path, root=root, warm=False
    )
    cache.save()
    return root, cache_path, discovery, processing


def _warm(root: Path, cache_path: Path, tamper: Tamper | None) -> Cache:
    """A warm handle whose ``pkg/mod.py`` entry carries one tampered row.

    The entry goes straight into the handle's map, which is where a reader
    meets it: whatever the wire admitted is what rehydration is handed.
    """

    warm = Cache(cache_path, root=root)
    warm.load()
    runtime_path = str(root / "pkg" / "mod.py")
    entry = warm.get_file_entry(runtime_path)
    assert entry is not None
    if tamper is not None:
        entry = replace(entry, module_dependent=tamper(entry.module_dependent))
        dict.__setitem__(warm.data["files"], runtime_path, entry)
    return warm


class _SpanCounters:
    """What one discovery span published: its name and its counters."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.counters: dict[str, int] = {}

    def set_counter(self, key: str, value: int) -> None:
        self.counters[key] = value


def corrupt_cached_dependent_lane(
    cache: Path, needle: bytes, *, wire_path: str
) -> None:
    """Swap the last character of ``needle`` inside one module's dependent lane.

    The swap is asserted to land exactly once: a needle that matched nothing
    would leave the warm run reading a sound row, and the test would pass
    over a corruption that never happened.
    """

    with closing(sqlite3.connect(cache)) as connection:
        row = connection.execute(
            f"SELECT d.file_id, d.payload FROM {TABLE_DEPENDENT} d "
            "JOIN cache_entry e ON e.file_id = d.file_id "
            "WHERE e.wire_path = ?",
            (wire_path,),
        ).fetchone()
        assert row is not None
        file_id, payload = int(row[0]), bytes(row[1])
        assert payload.count(needle) == 1, (needle, payload)
        swapped = needle[:-2] + (b"q" if needle[-2:-1] != b"q" else b"z") + b'"'
        assert len(swapped) == len(needle)
        connection.execute(
            f"UPDATE {TABLE_DEPENDENT} SET payload = ? WHERE file_id = ?",
            (payload.replace(needle, swapped), file_id),
        )
        connection.commit()


def _discover(
    monkeypatch: pytest.MonkeyPatch, root: Path, cache: Cache
) -> tuple[DiscoveryResult, dict[str, int]]:
    observed: list[_SpanCounters] = []

    @contextmanager
    def _recording(*, name: str) -> Iterator[_SpanCounters]:
        observed.append(_SpanCounters(name))
        yield observed[-1]

    with monkeypatch.context() as patch:
        patch.setattr(core_discovery, "span", _recording)
        discovery = core_discovery.discover(boot=_boot(root), cache=cache)
    reuse = [span for span in observed if span.name == "cache.profile_reuse"]
    assert len(reuse) == 1
    return discovery, reuse[0].counters


def _facts(
    discovery: DiscoveryResult, processing: ProcessingResult
) -> dict[str, list[str]]:
    """What a run ends up holding per family: served off the cache or walked."""

    return {
        "class_metrics": sorted(
            map(repr, (*discovery.cached_class_metrics, *processing.class_metrics))
        ),
        "module_deps": sorted(
            map(repr, (*discovery.cached_module_deps, *processing.module_deps))
        ),
        "dead_candidates": sorted(
            map(repr, (*discovery.cached_dead_candidates, *processing.dead_candidates))
        ),
        "security_surfaces": sorted(
            map(
                repr,
                (*discovery.cached_security_surfaces, *processing.security_surfaces),
            )
        ),
        "runtime_reachability": sorted(
            map(
                repr,
                (
                    *discovery.cached_runtime_reachability,
                    *processing.runtime_reachability,
                ),
            )
        ),
        "nested_definitions": sorted(
            map(
                repr,
                (*discovery.cached_nested_definitions, *processing.nested_definitions),
            )
        ),
    }


def test_an_untampered_warm_entry_is_served_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: the same probe on a sound row sees a full hit.

    Without it a refusal below could be the refusal of every warm row, and
    the cases would prove that the probe always reprocesses, not that the
    tampered row is why.
    """

    root, cache_path, _cold_discovery, _cold_processing = _cold(tmp_path)
    discovery, counters = _discover(monkeypatch, root, _warm(root, cache_path, None))

    assert discovery.files_to_process == ()
    assert discovery.cache_hits == 2
    assert counters.get(_REFUSED, 0) == 0
    assert any(
        fact.framework == "pydantic" for fact in discovery.cached_runtime_reachability
    )


def test_a_relationship_record_under_its_own_function_is_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control for the foreign-owner case: same edit, same owner.

    The record copied beside the first one keeps its function's
    ``source_qualname``, so it is a sound row and the file comes off the
    cache; only the owner differs in the refused case, so the owner is why.
    """

    root, cache_path, _cold_discovery, _cold_processing = _cold(tmp_path)
    warm = _warm(root, cache_path, _relationship_record())
    discovery, counters = _discover(monkeypatch, root, warm)

    assert discovery.files_to_process == ()
    assert counters.get(_REFUSED, 0) == 0
    owners = {
        facts.source_qualname for facts in discovery.cached_function_relationship_facts
    }
    assert owners, "the fixture module wrote no relationship facts"
    assert all(
        record.source_qualname == facts.source_qualname
        for facts in discovery.cached_function_relationship_facts
        for record in facts.relationships
    )


@pytest.mark.parametrize("family", sorted(_TAMPERS))
def test_a_row_rehydration_cannot_rebuild_refuses_the_file_and_is_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: str
) -> None:
    root, cache_path, cold_discovery, cold_processing = _cold(tmp_path)
    warm = _warm(root, cache_path, _TAMPERS[family])
    discovery, counters = _discover(monkeypatch, root, warm)
    runtime_path = str(root / "pkg" / "mod.py")

    # Refused, typed and counted -- and the file is walked again.
    assert discovery.files_to_process == (runtime_path,)
    assert counters.get(_REFUSED, 0) == 1
    assert counters["cache_lane_dependent_hit"] == 1
    assert counters["cache_lane_neutral_hit"] == 2
    # Nothing of the refused row's file leaked in beside the refusal.
    served = _facts(
        discovery, process(boot=_boot(root), discovery=discovery, cache=warm)
    )
    assert served == _facts(cold_discovery, cold_processing)


@pytest.mark.parametrize(
    ("label", "skip_metrics", "near_miss", "add_module", "rebuilt"),
    [
        ("both lanes accept, metrics read", False, False, False, 2),
        ("metrics skipped: nothing is read", True, False, False, 0),
        ("neutral lane refuses (clone channels)", False, True, False, 0),
        ("dependent lane refuses (module manifest)", False, False, True, 0),
    ],
    ids=[
        "both-lanes-accept",
        "metrics-skipped",
        "neutral-refuses",
        "dependent-refuses",
    ],
)
def test_rehydration_runs_only_where_its_facts_would_be_served(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    label: str,
    skip_metrics: bool,
    near_miss: bool,
    add_module: bool,
    rebuilt: int,
) -> None:
    """A row is rebuilt only when both lanes accept it and the run reads it.

    A row a lane already refused is walked again whatever its payload holds,
    and a metrics-skipping run serves none of it; rebuilding it anyway would
    cost a decode for nothing and could put a ``malformed_payload`` on a row
    whose lane had already given its own reason.
    """

    root, cache_path, _discovery, _processing = _cold(tmp_path)
    if add_module:
        (root / "pkg" / "added.py").write_text("VALUE = 1\n", "utf-8")
    calls: list[str] = []
    rehydrate = core_discovery.load_cached_metrics_extended

    def _counting(*args: object, **kwargs: object) -> object:
        calls.append(str(kwargs.get("filepath")))
        return rehydrate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(core_discovery, "load_cached_metrics_extended", _counting)
    boot = analysis_boot(
        root, min_loc=1, min_stmt=1, skip_metrics=skip_metrics, near_miss=near_miss
    )
    core_discovery.discover(boot=boot, cache=_warm(root, cache_path, None))

    assert len(calls) == rebuilt, label
