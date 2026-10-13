# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A warm cache serves the runtime-reachability fact the cold walk found.

Measured 2026-10-13 on fastapi @0cb4a8e2 and on the two-file tree below: the
cold walk finds a pydantic ``GenerateJsonSchema`` hook and keeps
``bytes_schema`` alive through it, the cache stores that fact whole, and the
warm run threw it away on the way back -- the rehydration narrower knew eleven
frameworks and the model twelve. The method fell back to an abstention, the
unresolved-override count moved by one, every store run id moved, and
``--fail-on-unresolved-dead-code`` exited 0 cold and 3 warm on the same tree.

Every test here drives the real CLI over a real hook. The instrument is shown
to reach the cache before an equality is read (the warm run analysed nothing),
because two cold runs are trivially equal; and the hook is shown to be the
reason for the verdict (without the pydantic import it is not recognised), so
an equal verdict cannot come from a fact that never existed.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import orjson

from codeclone.cache._wire_decode import _decode_wire_file_entry
from codeclone.cache._wire_encode import _encode_wire_file_entry
from codeclone.core.discovery_cache import load_cached_metrics_extended
from tests._pipeline_fixtures import payload_mapping, payload_sequence
from tests.conftest import _run_codeclone_cli_exit
from tests.test_cache_rehydration_refusal import corrupt_cached_dependent_lane

_SCOPE = (
    '[tool.codeclone]\nbaseline_scope_id = "5b0e4f43-8f1d-4f4e-9a52-2f3b1c6d7e80"\n'
)

#: Byte for byte the module the pre-fix fixture entry was captured from.
_HOOK_SOURCE = (
    '"""A pydantic JSON-schema generator whose hook pydantic calls at '
    'runtime."""\n'
    "\n"
    "from pydantic.json_schema import GenerateJsonSchema\n"
    "\n"
    "\n"
    "class BytesAsText(GenerateJsonSchema):\n"
    "    def bytes_schema(self, schema):\n"
    '        return {"type": "string", "format": "binary"}\n'
)

#: The same class over a look-alike base pydantic does not own: the positive
#: control. Nothing calls ``bytes_schema`` here, so nothing may keep it alive.
_LOOKALIKE_SOURCE = _HOOK_SOURCE.replace(
    "from pydantic.json_schema", "from vendor.json_schema"
)

_HOOK = "pkg.schema:BytesAsText.bytes_schema"

#: (reachable, runtime markers, abstained) of one symbol, as the report says.
_LIVE_THROUGH_THE_HOOK = (True, 1, False)
_ABSTAINED = (False, 0, True)

_PRE_FIX_ENTRY = (
    Path(__file__).parent / "fixtures" / "cache_v3" / "pydantic_hook_entry_pre_fix.json"
)

_GATE = "--fail-on-unresolved-dead-code"


@dataclass(frozen=True, slots=True)
class _Reading:
    """One CLI analysis: its gate exit, its report and the runs it published."""

    exit_code: int
    report: dict[str, object]
    published_runs: tuple[str, ...]

    def files(self) -> dict[str, object]:
        inventory = payload_mapping(self.report["inventory"])
        return payload_mapping(inventory["files"])

    def liveness(self, entity: str) -> tuple[object, object, object]:
        source_facts = payload_mapping(self.report["source_facts"])
        families = payload_mapping(source_facts["source_fact_families"])
        rows = [
            payload_mapping(row)
            for row in payload_sequence(families["dead_code"])
            if payload_mapping(row)["entity"] == entity
            and payload_mapping(row)["observation_kind"] == "symbol"
        ]
        assert len(rows) == 1, (entity, rows)
        row = rows[0]
        return row["reachable"], row["runtime_marker_count"], row["abstained"]

    def unresolved_overrides(self) -> object:
        metrics = payload_mapping(self.report["metrics"])
        summary = payload_mapping(metrics["summary"])
        return payload_mapping(summary["dead_code"])["unresolved_external_override"]


def _tree(root: Path, schema_source: str) -> Path:
    package = root / "pkg"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text(_SCOPE, "utf-8")
    (package / "__init__.py").write_text("", "utf-8")
    (package / "schema.py").write_text(schema_source, "utf-8")
    return root


def _cli(root: Path, *args: str, store: Path | None) -> int:
    environment = {"CODECLONE_RUN_STORE_ENABLED": "0"}
    if store is not None:
        environment = {
            "CODECLONE_RUN_STORE_ENABLED": "1",
            "CODECLONE_RUN_STORE_FORCE": "1",
            "CODECLONE_RUN_STORE_PATH": str(store),
        }
    code = _run_codeclone_cli_exit(
        [
            str(root),
            "--no-progress",
            "--baseline",
            str(root / "codeclone.baseline.json"),
            *args,
        ],
        environment,
    )
    assert code in (None, 0, 3), code
    return int(code or 0)


def _with_baseline(root: Path, work: Path) -> Path:
    """The tree's own baseline, written by a run whose cache nobody reads."""

    _cli(
        root,
        "--update-baseline",
        "--cache-path",
        str(work / "baseline-run.cache.sqlite3"),
        store=None,
    )
    return root


def _published_runs(store: Path) -> tuple[str, ...]:
    """The run ids a store published, oldest first (our own temp store)."""

    with closing(sqlite3.connect(store)) as connection:
        rows = connection.execute(
            "SELECT run_id FROM runs WHERE published = 1 ORDER BY run_pk"
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _analyse(root: Path, work: Path, label: str, *, cache: Path) -> _Reading:
    report_path = work / f"{label}.json"
    store = work / f"{label}.runs.sqlite3"
    code = _cli(
        root,
        "--cache-path",
        str(cache),
        "--json",
        str(report_path),
        _GATE,
        store=store,
    )
    report = json.loads(report_path.read_text("utf-8"))
    assert isinstance(report, dict)
    return _Reading(
        exit_code=code,
        report=report,
        published_runs=_published_runs(store),
    )


def _cold_then_warm(
    root: Path, work: Path, *, between: bytes | None = None
) -> tuple[_Reading, _Reading]:
    """A cold reading, then a warm one off its cache -- the instrument proven.

    ``between`` names one byte sequence of the cached ``pkg/schema.py``
    dependent lane to corrupt in place before the warm run, length kept, so
    the row still passes the store's own integrity check and reaches the
    readers.
    """

    cache = work / "cache.sqlite3"
    cold = _analyse(root, work, "cold", cache=cache)
    assert cold.files()["cached"] == 0
    assert cold.files()["analyzed"] == 2
    if between is not None:
        corrupt_cached_dependent_lane(cache, between, wire_path="pkg/schema.py")
    return cold, _analyse(root, work, "warm", cache=cache)


def test_the_hook_is_recognised_only_through_the_pydantic_import(
    tmp_path: Path,
) -> None:
    """Positive control: the probe can see the hook missing.

    The same class over a look-alike base abstains, carries no runtime marker
    and fails the unresolved-override gate; over pydantic's own base it is
    live through one marker and passes it. Without this pair an equal warm
    verdict below could be the verdict of a hook nobody recognised.
    """

    hooked = _with_baseline(_tree(tmp_path / "hooked", _HOOK_SOURCE), tmp_path)
    lookalike = _with_baseline(
        _tree(tmp_path / "lookalike", _LOOKALIKE_SOURCE), tmp_path
    )

    with_hook = _analyse(hooked, tmp_path, "hooked", cache=tmp_path / "h.sqlite3")
    without = _analyse(lookalike, tmp_path, "lookalike", cache=tmp_path / "l.sqlite3")

    assert with_hook.liveness(_HOOK) == _LIVE_THROUGH_THE_HOOK
    assert (with_hook.unresolved_overrides(), with_hook.exit_code) == (0, 0)
    assert without.liveness(_HOOK) == _ABSTAINED
    assert (without.unresolved_overrides(), without.exit_code) == (1, 3)


def test_a_warm_run_serves_the_hook_and_publishes_the_cold_run(
    tmp_path: Path,
) -> None:
    """The fact comes back off the cache, so the warm run IS the cold run.

    ``analyzed == 0`` is half the claim, not a precondition: a reader that
    refused the row and re-walked the file would also reach the cold verdict,
    and would hide a decoder that still cannot read the fact behind a
    recompute nobody asked for.
    """

    root = _with_baseline(_tree(tmp_path / "tree", _HOOK_SOURCE), tmp_path)
    cold, warm = _cold_then_warm(root, tmp_path)

    assert warm.files()["analyzed"] == 0
    assert warm.files()["cached"] == 2
    assert cold.liveness(_HOOK) == _LIVE_THROUGH_THE_HOOK
    assert warm.liveness(_HOOK) == cold.liveness(_HOOK)
    assert warm.unresolved_overrides() == cold.unresolved_overrides() == 0
    assert len(cold.published_runs) == 1
    assert warm.published_runs == cold.published_runs


def test_the_unresolved_override_gate_does_not_depend_on_the_cache(
    tmp_path: Path,
) -> None:
    """Measured before the fix: exit 0 cold, exit 3 warm, one tree."""

    root = _with_baseline(_tree(tmp_path / "tree", _HOOK_SOURCE), tmp_path)
    cold, warm = _cold_then_warm(root, tmp_path)

    assert warm.files()["analyzed"] == 0
    assert (cold.exit_code, warm.exit_code) == (0, 0)


def test_a_row_the_wire_admits_and_rehydration_cannot_rebuild_is_recomputed(
    tmp_path: Path,
) -> None:
    """The row is refused and the file re-walked; nothing silently vanishes.

    The candidate kind is a field the wire carries as a plain string and only
    rehydration narrows, so this corruption reaches rehydration on a real
    cache. A reader that dropped the row would lose ``bytes_schema`` from the
    candidate population and publish a run without its verdict.
    """

    root = _with_baseline(_tree(tmp_path / "tree", _HOOK_SOURCE), tmp_path)
    cold, warm = _cold_then_warm(root, tmp_path, between=b'"bytes_schema",7,8,"method"')

    assert warm.files()["analyzed"] == 1
    assert warm.liveness(_HOOK) == cold.liveness(_HOOK) == _LIVE_THROUGH_THE_HOOK
    assert warm.published_runs == cold.published_runs
    assert warm.exit_code == cold.exit_code == 0


def test_an_unknown_framework_on_disk_is_recomputed_not_dropped(
    tmp_path: Path,
) -> None:
    """A framework this build does not know refuses the row; the file re-walks.

    The wire layer narrows the framework itself, so the refusal lands there
    and takes the whole entry with it; either layer may refuse, neither may
    serve the file without the fact.
    """

    root = _with_baseline(_tree(tmp_path / "tree", _HOOK_SOURCE), tmp_path)
    cold, warm = _cold_then_warm(root, tmp_path, between=b'"method","pydantic"')

    assert warm.files()["analyzed"] == 1
    assert warm.liveness(_HOOK) == cold.liveness(_HOOK) == _LIVE_THROUGH_THE_HOOK
    assert warm.published_runs == cold.published_runs


def _pre_fix_entry() -> dict[str, object]:
    wire = json.loads(_PRE_FIX_ENTRY.read_text("utf-8"))
    assert isinstance(wire, dict)
    return wire


def test_a_cache_row_written_before_the_fix_rehydrates_the_hook() -> None:
    """Compatibility is read off the old bytes, not assumed.

    The fixture is the wire entry the build at 08a61e40 stored for the hook
    module, read back from its sqlite cache exactly as a later reader gets it.
    No version moved, so an upgraded reader meets these rows on its first
    warm run; they must give the fact back.
    """

    wire = _pre_fix_entry()
    dependent = payload_mapping(wire["d"])
    assert [payload_sequence(row)[4] for row in payload_sequence(dependent["rr"])] == [
        "pydantic"
    ]
    entry = _decode_wire_file_entry(
        wire, "pkg/schema.py", analysed_filepath="pkg/schema.py"
    )
    assert entry is not None
    *_, reachability, _security = load_cached_metrics_extended(
        entry, filepath="pkg/schema.py"
    )
    assert [
        (fact.target_qualname, fact.framework, fact.edge_kind) for fact in reachability
    ] == [(_HOOK, "pydantic", "runtime_hook")]


def test_this_build_writes_the_pre_fix_bytes_back_unchanged() -> None:
    """The encoder did not move: the old row and a new row are one row.

    Decoding the stored entry and encoding it again must reproduce the stored
    bytes exactly, which is what lets a cache written before the fix and one
    written after it stand under one ``CACHE_VERSION``.
    """

    wire = _pre_fix_entry()
    entry = _decode_wire_file_entry(
        wire, "pkg/schema.py", analysed_filepath="pkg/schema.py"
    )
    assert entry is not None
    option = orjson.OPT_SORT_KEYS
    assert orjson.dumps(_encode_wire_file_entry(entry), option=option) == orjson.dumps(
        wire, option=option
    )
