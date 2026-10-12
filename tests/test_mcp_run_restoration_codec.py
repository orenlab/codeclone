# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The execution overlay codec: a resident run as canonical JSON, decoded by
a validating reader (RFC 2026-09-02 III.2).

The run store lives in the analysed repository, so an overlay's bytes are
input: no pickle, a bounded decompression, every key and type checked, and
the execution's witnesses re-derived by the event itself.
"""

from __future__ import annotations

import ast
import zlib
from dataclasses import fields, replace
from pathlib import Path

import orjson
import pytest

from codeclone.api.execution_event import ExecutionEvent
from codeclone.api.run_residence import RunSummaryResidue
from codeclone.api.run_restoration import RunSnapshotLink
from codeclone.surfaces.mcp import _run_restoration as codec
from codeclone.surfaces.mcp._run_restoration import (
    OverlayRefusal,
    decode_resident_run,
    encode_resident_run,
)
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunIdentity
from codeclone.surfaces.mcp._workspace_hygiene import DirtySnapshot, DirtySnapshotEntry


def _identity(**changes: object) -> MCPRunIdentity:
    execution = ExecutionEvent(
        execution_event_id="e" * 32,
        root=Path("/checkout/x"),
        semantic_report_id="a" * 64,
        manifest={"pkg/m.py": {"mtime_ns": 7, "size": 12}},
        content_manifest={"pkg/m.py": "c" * 64},
        dirty_snapshot=DirtySnapshot(
            git_available=True,
            captured_at_utc="2026-10-12T00:00:00Z",
            entries=(
                DirtySnapshotEntry(
                    path="pkg/m.py", status_xy=" M", digest="d" * 64, digest_status="ok"
                ),
            ),
        ),
        warnings=("w",),
        failures=(),
        analysis_started_at_utc="2026-10-12T00:00:00Z",
        scope_source="git",
        report_generated_at_utc="2026-10-12T00:00:01Z",
        code_digest="sha256:f",
        run_snapshot_link=RunSnapshotLink(
            state="linked",
            outcome="published",
            store_run_id="b" * 64,
            analysis_scope_digest="s" * 64,
            report_run_identity="a" * 64,
        ),
    )
    identity = MCPRunIdentity(
        run_id="a" * 64,
        root=Path("/checkout/x"),
        request=MCPAnalysisRequest(
            root="/checkout/x", changed_paths=("pkg/m.py",), min_loc=3
        ),
        comparison_settings=("full", 6, 4, 20, 8, 20, 10, 20, 10, 4),
        changed_paths=("pkg/m.py",),
        func_clones_count=2,
        block_clones_count=1,
        execution=execution,
        summary_residue=RunSummaryResidue(
            version="2.1.0a2",
            schema="3.6",
            cache={"used": False, "freshness": "fresh"},
            baseline_execution={"runtime_python_tag": "cp314"},
            entity_counts=None,
            security_presentation={"report_only": True, "note": "n"},
        ),
    )
    return replace(identity, **changes)  # type: ignore[arg-type]


def _payload(identity: MCPRunIdentity) -> dict[str, object]:
    loaded = orjson.loads(zlib.decompress(encode_resident_run(identity)))
    assert isinstance(loaded, dict)
    return loaded


def _overlay(payload: object) -> bytes:
    return zlib.compress(orjson.dumps(payload))


def test_a_resident_run_round_trips_exactly() -> None:
    identity = _identity()
    assert decode_resident_run(encode_resident_run(identity)) == identity
    bare = _identity(
        execution=replace(
            _identity().execution,
            manifest=None,
            dirty_snapshot=None,
            run_snapshot_link=None,
        )
    )
    assert decode_resident_run(encode_resident_run(bare)) == bare


def test_an_execution_without_a_content_witness_is_no_execution_of_ours() -> None:
    """Production never records an execution without what it read, and the
    intent registry's abstention rests on that: a stored one is refused."""
    blind = _identity(execution=replace(_identity().execution, content_manifest=None))
    with pytest.raises(OverlayRefusal, match="content witness"):
        decode_resident_run(encode_resident_run(blind))


def test_the_overlay_bytes_are_canonical() -> None:
    identity = _identity()
    first = zlib.decompress(encode_resident_run(identity))
    assert first == zlib.decompress(encode_resident_run(identity))
    assert first == orjson.dumps(orjson.loads(first), option=orjson.OPT_SORT_KEYS)


def test_every_request_field_has_a_reading() -> None:
    """A request field of an annotation the codec has no reading for would be
    refused at decode; this names it at test time instead."""
    for field in fields(MCPAnalysisRequest):
        if field.name == "changed_paths":
            continue
        assert str(field.type) in codec._REQUEST_READINGS, field.name


def test_the_codec_module_holds_no_pickle() -> None:
    tree = ast.parse(Path(codec.__file__).read_text("utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not {name for name in names if "pickle" in name}


def _mutated(path: tuple[str, ...], value: object) -> bytes:
    payload = _payload(_identity())
    target: dict[str, object] = payload
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value
    return _overlay(payload)


@pytest.mark.parametrize(
    "overlay",
    [
        pytest.param(b"not zlib", id="not-zlib"),
        pytest.param(zlib.compress(b"{not json"), id="not-json"),
        pytest.param(_overlay([1, 2]), id="not-an-object"),
        pytest.param(_mutated(("extra",), 1), id="unknown-key"),
        pytest.param(_mutated(("func_clones_count",), True), id="bool-as-int"),
        pytest.param(_mutated(("func_clones_count",), "2"), id="str-as-int"),
        pytest.param(_mutated(("request", "respect_pyproject"), 1), id="int-as-bool"),
        pytest.param(_mutated(("request", "min_loc"), "3"), id="request-type"),
        pytest.param(_mutated(("request", "unknown"), 1), id="request-key"),
        pytest.param(_mutated(("comparison_settings",), [1.5]), id="settings-type"),
        pytest.param(
            _mutated(("execution", "content_manifest"), {"pkg/m.py": "e" * 64}),
            id="witness-does-not-re-derive",
        ),
        pytest.param(
            _mutated(("execution", "manifest"), {"pkg/m.py": {"size": 1}}),
            id="manifest-entry",
        ),
        pytest.param(
            _mutated(("execution", "dirty_snapshot"), {"git_available": "yes"}),
            id="dirty-snapshot",
        ),
        pytest.param(
            _mutated(("execution", "run_snapshot_link", "state"), "bogus"),
            id="link-state",
        ),
        pytest.param(_mutated(("summary_residue", "cache"), [1]), id="residue-mapping"),
    ],
)
def test_an_overlay_the_codec_cannot_read_is_refused_never_guessed(
    overlay: bytes,
) -> None:
    with pytest.raises(OverlayRefusal):
        decode_resident_run(overlay)


def test_a_request_field_without_a_reading_is_refused_at_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard behind ``test_every_request_field_has_a_reading``: a field
    whose annotation the codec cannot read is refused, never passed raw."""
    overlay = encode_resident_run(_identity())
    readings = dict(codec._REQUEST_READINGS)
    del readings["int | None"]
    monkeypatch.setattr(codec, "_REQUEST_READINGS", readings)
    with pytest.raises(OverlayRefusal, match="has no reading"):
        decode_resident_run(overlay)


def test_a_decompression_past_the_bound_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay = encode_resident_run(_identity())
    assert decode_resident_run(overlay) == _identity()
    monkeypatch.setattr(codec, "_MAX_OVERLAY_BYTES", 64)
    with pytest.raises(OverlayRefusal, match="bound"):
        decode_resident_run(overlay)
