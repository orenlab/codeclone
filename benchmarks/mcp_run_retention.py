#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Run-retention ladder: what the in-process MCP service holds, rung by rung.

Step 1 of the run-retention design (2026-09-02, section 9): the instrument
that makes every later retention claim measurable.  It analyses N distinct
copies of one source tree through ``CodeCloneMCPService.analyze_repository``
in THIS process and, after every rung, records:

* the physical footprint of the process and its peak, read from
  ``vmmap -summary`` ("Physical footprint").  Not ``ps`` RSS, which read
  622 MB at a 1,331 MB footprint when the design was measured;
* the pymalloc arenas and the free space inside them;
* the deep size of every retained run record, and of the newest record by
  field and by served section;
* the cache freshness the analysis itself reported, and its wall time.

Witnesses come before counts (the benchmark-witness law).  Every rung carries
``retained_runs``, ``run_id``, ``freshness``, ``scope_source``,
``footprint_source`` and ``service_dir_unchanged``, and the renderer refuses
a rung whose witness block is incomplete instead of printing a number nobody
can attribute.

Isolation is measured, not assumed: the service's audit trail goes to a null
writer, the canonical run store is forced off, and every copy's
``.codeclone/`` is hashed before and after its analysis.  The MCP path has
written its own analysis cache since 2026-09-02 (containment, not read-only),
so a cache write is not prevented here -- that would measure a server nobody
runs -- it is reported, path by path, as ``service_dir_changes``.
Copies are made under ``--roots-dir``, which must be empty and must lie
outside ``--source``; the harness never deletes anything.

Mode ``inproc`` only.  ``child`` -- the analysis in an isolated worker -- is
a later step of the design and is not implemented here.

Usage::

    uv run python benchmarks/mcp_run_retention.py \\
        --source <tree> --roots-dir <empty dir outside the tree> \\
        --copies 5 --json <out.json>
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import BuiltinFunctionType, FunctionType, MethodType, ModuleType
from typing import Final

from codeclone import __version__
from codeclone.audit.writer import NullAuditWriter
from codeclone.core.canonical_snapshot import (
    ENV_RUN_STORE_ENABLED,
    resolve_run_store_config,
)
from codeclone.observability import is_observability_enabled
from codeclone.surfaces.mcp._code_provenance import process_code_provenance
from codeclone.surfaces.mcp._session_shared import (
    DEFAULT_MCP_HISTORY_LIMIT,
    MCPRunRecord,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest

#: What one distinct root is made of (design Appendix A).
DEFAULT_ENTRIES: Final = (
    "codeclone",
    "tests",
    "pyproject.toml",
    "codeclone.baseline.json",
    ".codeclone/db/cache.sqlite3",
)
MODES: Final = ("inproc",)
SERVICE_DIR: Final = ".codeclone"

#: Printed before any count, in this order, on every rung.
WITNESS_KEYS: Final = (
    "rung",
    "retained_runs",
    "run_id",
    "freshness",
    "scope_source",
    "footprint_source",
    "service_dir_unchanged",
)
#: The measured values a rung reports once its witnesses are complete.
COUNT_KEYS: Final = (
    "footprint_mb",
    "peak_mb",
    "swapped_mb",
    "malloc_allocated_mb",
    "malloc_frag_mb",
    "malloc_empty_mb",
    "live_records_mb",
    "arenas_mb",
    "arenas_free_mb",
    "analysis_s",
    "files_analyzed",
    "files_cached",
    "load_1m",
)

_MIB: Final = 1024 * 1024
_HASH_CHUNK: Final = _MIB
_NOT_APPLICABLE: Final = "-"
_VMMAP_UNITS: Final = {
    "B": 1.0 / _MIB,
    "K": 1.0 / 1024,
    "M": 1.0,
    "G": 1024.0,
    "T": 1024.0 * 1024.0,
}
_VMMAP_LINE: Final = re.compile(
    r"^Physical footprint(?P<peak> \(peak\))?:\s+"
    r"(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>[BKMGT])\s*$",
    re.MULTILINE,
)
# The region table's TOTAL row: VIRTUAL RESIDENT DIRTY SWAPPED ...  A non-zero
# SWAPPED column means the kernel compressed or swapped this process's pages,
# so the footprint of that rung was read under memory pressure.
_VMMAP_TOTAL_ROW: Final = re.compile(
    r"^TOTAL\s+\S+\s+\S+\s+\S+\s+"
    r"(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>[BKMGT])\b",
    re.MULTILINE,
)
# The MALLOC ZONE table's TOTAL row: VIRTUAL RESIDENT DIRTY SWAPPED, then
# ALLOCATION COUNT, BYTES ALLOCATED and DIRTY+SWAP FRAG SIZE.  The frag column
# is memory the system allocator holds dirty for blocks already freed: slack
# outside the pymalloc arenas, which is where a large freed working set goes.
_VMMAP_MALLOC_TOTAL_ROW: Final = re.compile(
    r"^TOTAL(?:\s+\S+){4}\s+[0-9]+\s+"
    r"(?P<allocated>[0-9]+(?:\.[0-9]+)?)(?P<allocated_unit>[BKMGT])\s+"
    r"(?P<frag>[0-9]+(?:\.[0-9]+)?)(?P<frag_unit>[BKMGT])\s+[0-9]+%",
    re.MULTILINE,
)
# Region rows the system allocator marks ``(empty)`` -- ``Malloc Large
# (empty)`` above all -- are freed blocks it still holds dirty or compressed.
# Measured on this ladder they carry most of the footprint between rungs, so
# they are named rather than left inside the total.
_VMMAP_EMPTY_ROW: Final = re.compile(
    r"^(?P<name>\S.*?\(empty\))\s+\S+\s+\S+\s+"
    r"(?P<dirty>[0-9]+(?:\.[0-9]+)?)(?P<dirty_unit>[BKMGT])\s+"
    r"(?P<swapped>[0-9]+(?:\.[0-9]+)?)(?P<swapped_unit>[BKMGT])\b",
    re.MULTILINE,
)
_VMMAP_REGION_HEADER: Final = "REGION TYPE"
_ARENAS_LINE: Final = re.compile(
    r"^(?P<count>[0-9,]+) arenas \* (?P<size>[0-9,]+) bytes/arena\s*=",
    re.MULTILINE,
)
_AVAILABLE_LINE: Final = re.compile(
    r"^# bytes in available blocks\s*=\s*(?P<bytes>[0-9,]+)\s*$",
    re.MULTILINE,
)
_UNUSED_POOLS_LINE: Final = re.compile(
    r"^(?P<count>[0-9,]+) unused pools \* (?P<size>[0-9,]+) bytes\s*=",
    re.MULTILINE,
)
# Code and interpreter objects are shared by every record and belong to no
# run; walking into them would charge each record for the whole program.
_NOT_RETAINED_BY_A_RECORD: Final = (
    type,
    ModuleType,
    FunctionType,
    BuiltinFunctionType,
    MethodType,
)


class HarnessError(RuntimeError):
    """The harness refused to measure, or to print what it could not witness."""


@dataclasses.dataclass(frozen=True, slots=True)
class Footprint:
    """One ``vmmap`` reading; ``source`` says whether the numbers exist."""

    source: str
    current_mb: float | None
    peak_mb: float | None
    swapped_mb: float | None = None
    malloc_allocated_mb: float | None = None
    malloc_frag_mb: float | None = None
    malloc_empty_mb: float | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Arenas:
    """pymalloc arenas in use and the free space still inside them."""

    source: str
    arenas_mb: float | None
    free_mb: float | None


def parse_vmmap_summary(text: str) -> tuple[float, float] | None:
    """``(footprint, peak)`` in MiB, or ``None`` unless both lines parse."""

    values: dict[str, float] = {}
    for match in _VMMAP_LINE.finditer(text):
        key = "peak" if match.group("peak") else "current"
        values[key] = float(match.group("value")) * _VMMAP_UNITS[match.group("unit")]
    if set(values) != {"current", "peak"}:
        return None
    return values["current"], values["peak"]


def parse_vmmap_swapped(text: str) -> float | None:
    """MiB the region table reports as swapped or compressed, if it parses."""

    match = _VMMAP_TOTAL_ROW.search(text)
    if match is None:
        return None
    return float(match.group("value")) * _VMMAP_UNITS[match.group("unit")]


def parse_vmmap_malloc(text: str) -> tuple[float, float] | None:
    """``(allocated, frag)`` MiB of the system malloc zones, if they parse."""

    match = _VMMAP_MALLOC_TOTAL_ROW.search(text)
    if match is None:
        return None
    allocated = (
        float(match.group("allocated")) * _VMMAP_UNITS[match.group("allocated_unit")]
    )
    frag = float(match.group("frag")) * _VMMAP_UNITS[match.group("frag_unit")]
    return allocated, frag


def parse_vmmap_empty(text: str) -> float | None:
    """MiB dirty or swapped in ``(empty)`` allocator regions, if the table parses."""

    if _VMMAP_REGION_HEADER not in text:
        return None
    return sum(
        float(match.group("dirty")) * _VMMAP_UNITS[match.group("dirty_unit")]
        + float(match.group("swapped")) * _VMMAP_UNITS[match.group("swapped_unit")]
        for match in _VMMAP_EMPTY_ROW.finditer(text)
    )


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def read_footprint(pid: int) -> Footprint:
    executable = shutil.which("vmmap")
    if executable is None:
        return Footprint("unavailable:vmmap_not_found", None, None)
    try:
        completed = subprocess.run(
            [executable, "-summary", str(pid)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Footprint(f"unavailable:{type(exc).__name__}", None, None)
    if completed.returncode != 0:
        return Footprint(f"unavailable:vmmap_rc_{completed.returncode}", None, None)
    parsed = parse_vmmap_summary(completed.stdout)
    if parsed is None:
        return Footprint("unavailable:vmmap_unparsed", None, None)
    malloc = parse_vmmap_malloc(completed.stdout)
    return Footprint(
        "vmmap",
        round(parsed[0], 1),
        round(parsed[1], 1),
        _rounded(parse_vmmap_swapped(completed.stdout)),
        _rounded(None if malloc is None else malloc[0]),
        _rounded(None if malloc is None else malloc[1]),
        _rounded(parse_vmmap_empty(completed.stdout)),
    )


def _as_count(text: str) -> int:
    return int(text.replace(",", ""))


def parse_pymalloc_stats(text: str) -> Arenas:
    arenas = _ARENAS_LINE.search(text)
    available = _AVAILABLE_LINE.search(text)
    unused = _UNUSED_POOLS_LINE.search(text)
    if arenas is None or available is None or unused is None:
        return Arenas("unavailable:pymalloc_unparsed", None, None)
    arena_bytes = _as_count(arenas.group("count")) * _as_count(arenas.group("size"))
    free_bytes = _as_count(available.group("bytes")) + _as_count(
        unused.group("count")
    ) * _as_count(unused.group("size"))
    return Arenas(
        "pymalloc",
        round(arena_bytes / _MIB, 1),
        round(free_bytes / _MIB, 1),
    )


def read_pymalloc() -> Arenas:
    """Parse ``sys._debugmallocstats``, which writes to file descriptor 2."""

    dump = getattr(sys, "_debugmallocstats", None)
    if dump is None:
        return Arenas("unavailable:no_debugmallocstats", None, None)
    sys.stderr.flush()
    with tempfile.TemporaryFile() as sink:
        saved = os.dup(2)
        try:
            os.dup2(sink.fileno(), 2)
            dump()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        sink.seek(0)
        text = sink.read().decode("utf-8", "replace")
    return parse_pymalloc_stats(text)


def deep_size(root: object, seen: set[int]) -> int:
    """Bytes reachable from ``root`` that ``seen`` has not already charged."""

    total = 0
    pending = [root]
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in seen or isinstance(item, _NOT_RETAINED_BY_A_RECORD):
            continue
        seen.add(identity)
        total += sys.getsizeof(item)
        pending.extend(gc.get_referents(item))
    return total


def _mb(value: int) -> float:
    return round(value / _MIB, 2)


def _served_sections(record: MCPRunRecord) -> dict[str, float]:
    served = record.served_report
    sizes = {key: _mb(deep_size(served[key], set())) for key in sorted(served)}
    sizes["(contract)"] = _mb(deep_size(served.contract, set()))
    return sizes


def _metric_families(record: MCPRunRecord) -> dict[str, float]:
    metrics = record.served_report.get("metrics")
    families = metrics.get("families") if isinstance(metrics, Mapping) else None
    if not isinstance(families, Mapping):
        return {}
    return {
        str(name): _mb(deep_size(families[name], set()))
        for name in sorted(families, key=str)
    }


def record_anatomy(record: MCPRunRecord) -> dict[str, object]:
    """Deep size of one record by field (global and standalone) and section.

    ``global`` charges an object shared by two fields to the first field in
    declaration order, so the column sums to the record; ``standalone`` is
    what each field would hold on its own.
    """

    names = [field.name for field in dataclasses.fields(record)]
    shared: set[int] = set()
    by_field = {
        name: {
            "global_mb": _mb(deep_size(getattr(record, name), shared)),
            "standalone_mb": _mb(deep_size(getattr(record, name), set())),
        }
        for name in names
    }
    return {
        "run_id": record.run_id,
        "record_mb": _mb(deep_size(record, set())),
        "fields": by_field,
        "served_sections": _served_sections(record),
        "metric_families": _metric_families(record),
    }


def service_dir_changes(
    before: Mapping[str, str], after: Mapping[str, str]
) -> list[str]:
    """Paths under ``.codeclone`` created, removed or rewritten, sorted."""

    return sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )


def service_dir_state(root: Path) -> dict[str, str]:
    """Every file under ``root/.codeclone`` with the sha256 of its bytes."""

    base = root / SERVICE_DIR
    state: dict[str, str] = {}
    if not base.is_dir():
        return state
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
                digest.update(chunk)
        state[path.relative_to(root).as_posix()] = digest.hexdigest()
    return state


def materialize_roots(
    source: Path,
    roots_dir: Path,
    *,
    copies: int,
    entries: Sequence[str],
) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    """Copy ``entries`` of ``source`` into ``copies`` distinct roots.

    Returns the roots and the entries that were absent from the source, which
    are a witness of the run and never silently dropped.
    """

    source = source.resolve()
    roots_dir = roots_dir.resolve()
    if roots_dir == source or source in roots_dir.parents:
        raise HarnessError("--roots-dir must lie outside --source")
    if roots_dir.exists() and any(roots_dir.iterdir()):
        raise HarnessError("--roots-dir must be empty; the harness deletes nothing")
    present = tuple(entry for entry in entries if (source / entry).exists())
    missing = tuple(entry for entry in entries if entry not in present)
    if not present:
        raise HarnessError("none of the entries exists under --source")
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc")
    roots: list[Path] = []
    for index in range(1, copies + 1):
        root = roots_dir / f"root-{index}"
        for entry in present:
            origin = source / entry
            target = root / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            if origin.is_dir():
                shutil.copytree(origin, target, ignore=ignored)
            else:
                shutil.copy2(origin, target)
        roots.append(root)
    return tuple(roots), missing


def _summary_files(record: MCPRunRecord) -> tuple[int, int]:
    inventory = record.summary.get("inventory")
    files = inventory.get("files") if isinstance(inventory, Mapping) else None
    if not isinstance(files, Mapping):
        return 0, 0
    return int(files.get("analyzed", 0) or 0), int(files.get("cached", 0) or 0)


def _freshness(summary: Mapping[str, object]) -> str:
    cache = summary.get("cache")
    if not isinstance(cache, Mapping):
        return "absent"
    return str(cache.get("freshness", "absent"))


def _measure(
    rung: str,
    service: CodeCloneMCPService,
    *,
    anatomy: bool,
) -> dict[str, object]:
    footprint = read_footprint(os.getpid())
    arenas = read_pymalloc()
    records = service._runs.records()
    measured: dict[str, object] = {
        "rung": rung,
        "retained_runs": len(records),
        "footprint_source": footprint.source,
        "arenas_source": arenas.source,
        "footprint_mb": footprint.current_mb,
        "peak_mb": footprint.peak_mb,
        "swapped_mb": footprint.swapped_mb,
        "malloc_allocated_mb": footprint.malloc_allocated_mb,
        "malloc_frag_mb": footprint.malloc_frag_mb,
        "malloc_empty_mb": footprint.malloc_empty_mb,
        "load_1m": round(os.getloadavg()[0], 1),
        "arenas_mb": arenas.arenas_mb,
        "arenas_free_mb": arenas.free_mb,
        "live_records_mb": None,
    }
    if anatomy:
        measured["live_records_mb"] = _mb(deep_size(records, set()))
        after = read_footprint(os.getpid())
        measured["probe_footprint_after_mb"] = after.current_mb
        measured["probe_raised_peak"] = (
            after.peak_mb is not None
            and footprint.peak_mb is not None
            and after.peak_mb > footprint.peak_mb
        )
    return measured


def _analysis_rung(
    index: int,
    root: Path,
    service: CodeCloneMCPService,
    *,
    anatomy: bool,
) -> tuple[dict[str, object], dict[str, object] | None]:
    before = service_dir_state(root)
    started = time.perf_counter()
    summary = service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    elapsed = time.perf_counter() - started
    changes = service_dir_changes(before, service_dir_state(root))
    newest = service._runs.records()[-1]
    short_id = str(summary.get("run_id", ""))
    if not short_id or not newest.run_id.startswith(short_id):
        raise HarnessError(f"rung {index}: the newest record is not this analysis")
    if newest.root != root.resolve():
        raise HarnessError(f"rung {index}: the newest record is not this analysis")
    analyzed, cached = _summary_files(newest)
    rung = _measure(str(index), service, anatomy=anatomy)
    rung.update(
        {
            "run_id": newest.run_id,
            "freshness": _freshness(summary),
            "scope_source": newest.execution.scope_source or "unknown",
            "service_dir_unchanged": not changes,
            "service_dir_changes": changes,
            "analysis_s": round(elapsed, 2),
            "files_analyzed": analyzed,
            "files_cached": cached,
        }
    )
    return rung, (record_anatomy(newest) if anatomy else None)


def _idle_rung(
    rung: str, service: CodeCloneMCPService, *, anatomy: bool
) -> dict[str, object]:
    measured = _measure(rung, service, anatomy=anatomy)
    measured.update(
        {
            "run_id": _NOT_APPLICABLE,
            "freshness": _NOT_APPLICABLE,
            "scope_source": _NOT_APPLICABLE,
            "service_dir_unchanged": True,
            "service_dir_changes": [],
            "analysis_s": None,
            "files_analyzed": None,
            "files_cached": None,
        }
    )
    return measured


def _run_witnesses(history_limit: int, mode: str) -> dict[str, object]:
    import codeclone

    return {
        "mode": mode,
        "history_limit": history_limit,
        "codeclone_version": __version__,
        "code_digest": str(process_code_provenance().get("code_digest", "")),
        "loaded_from": str(Path(codeclone.__file__).resolve().parent),
        "python": sys.version.split()[0],
        "pymalloc": os.environ.get("PYTHONMALLOC", "default"),
        "observability_enabled": is_observability_enabled(),
        "audit_writer": NullAuditWriter.__name__,
        "forced_gc": False,
    }


@contextmanager
def _run_store_forced_off() -> Iterator[None]:
    """Hold the canonical run store off for the ladder, then restore the env."""

    previous = os.environ.get(ENV_RUN_STORE_ENABLED)
    os.environ[ENV_RUN_STORE_ENABLED] = "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(ENV_RUN_STORE_ENABLED, None)
        else:
            os.environ[ENV_RUN_STORE_ENABLED] = previous


def run_ladder(
    roots: Sequence[Path],
    *,
    history_limit: int,
    mode: str = "inproc",
    anatomy: bool = True,
) -> dict[str, object]:
    """Analyse each root in turn, holding every run the store keeps."""

    if mode not in MODES:
        raise HarnessError(f"mode {mode!r} is not implemented; available: {MODES}")
    with _run_store_forced_off():
        if any(resolve_run_store_config(root=root).enabled for root in roots):
            raise HarnessError("the canonical run store is enabled; refusing")
        return _ladder(roots, history_limit=history_limit, mode=mode, anatomy=anatomy)


def _ladder(
    roots: Sequence[Path],
    *,
    history_limit: int,
    mode: str,
    anatomy: bool,
) -> dict[str, object]:
    service = CodeCloneMCPService(history_limit=history_limit)
    # The session's own override seam; the production default would open the
    # audit database the copied pyproject enables, under each copy.
    service._audit_writer_override = NullAuditWriter()
    rungs = [_idle_rung("import", service, anatomy=anatomy)]
    anatomies: dict[str, object] = {}
    for index, root in enumerate(roots, start=1):
        rung, record = _analysis_rung(index, root, service, anatomy=anatomy)
        rungs.append(rung)
        if record is not None:
            anatomies[str(index)] = record
    service.clear_session_runs()
    rungs.append(_idle_rung("cleared", service, anatomy=anatomy))
    return {
        "witnesses": _run_witnesses(history_limit, mode),
        "rungs": rungs,
        "anatomy": anatomies,
    }


_RUN_ID_CELL: Final = 12


def _cell(key: str, value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "NO"
    if key == "run_id":
        return str(value)[:_RUN_ID_CELL]
    return str(value)


def render_table(result: Mapping[str, object]) -> str:
    """The ladder as text, witnesses first; a rung missing one is refused."""

    rungs = result.get("rungs")
    if not isinstance(rungs, Sequence) or not rungs:
        raise HarnessError("no rungs to render")
    header = [*WITNESS_KEYS, *COUNT_KEYS]
    lines = [" | ".join(header)]
    for rung in rungs:
        if not isinstance(rung, Mapping):
            raise HarnessError("a rung is not a mapping")
        absent = [key for key in WITNESS_KEYS if rung.get(key) is None]
        if absent:
            raise HarnessError(
                f"rung {rung.get('rung')!r} lacks witnesses {absent}; "
                "its counts are withheld"
            )
        lines.append(" | ".join(_cell(key, rung.get(key)) for key in header))
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--roots-dir", type=Path, required=True)
    parser.add_argument("--copies", type=int, default=5)
    parser.add_argument("--history-limit", type=int, default=DEFAULT_MCP_HISTORY_LIMIT)
    parser.add_argument("--mode", choices=MODES, default="inproc")
    parser.add_argument(
        "--entry",
        action="append",
        dest="entries",
        help="path under --source to copy into each root (repeatable)",
    )
    parser.add_argument("--no-anatomy", action="store_true")
    parser.add_argument("--json", type=Path, dest="json_path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.copies < 1:
        raise HarnessError("--copies must be at least 1")
    roots, missing = materialize_roots(
        args.source,
        args.roots_dir,
        copies=args.copies,
        entries=tuple(args.entries or DEFAULT_ENTRIES),
    )
    result = run_ladder(
        roots,
        history_limit=args.history_limit,
        mode=args.mode,
        anatomy=not args.no_anatomy,
    )
    witnesses = result["witnesses"]
    if isinstance(witnesses, dict):
        witnesses["missing_entries"] = list(missing)
    print(json.dumps(witnesses, indent=2, sort_keys=True))
    print(render_table(result))
    if args.json_path is not None:
        args.json_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
