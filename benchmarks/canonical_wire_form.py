#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The columnar-vs-object frozen serialization benchmark of the wire.

Item 3 of the sanctioned wire-freeze closed list (``specs/canonical-model
-F3.md`` section 13.B) and the only one of the six that is a **measurement**
rather than a pin.  §7 of the same spec names it the single fork that
requires a number rather than an argument: the columnar table pays a key
name once per table, an array of objects pays it once per row, and the
difference is size, slope and the reader's peak memory.  ``specs/post-a2
-run-store-backend.md`` §15.2 fixes the protocol -- freeze the
repositories, **do not change the design after the results**, and measure
size · slope · peak memory · reader success · round-trip · byte
determinism.

The two arms differ in exactly one thing: table shape.

* the columnar arm IS :func:`encode_canonical_json`, unmodified;
* the object arm walks the SAME ``fact_family_rows`` output through the
  SAME lexeme layer, the SAME leading members and the SAME integrity
  construction, and emits ``[{col: v}, ...]`` where the wire emits
  ``{col: [v, ...]}``.

That is why this module imports the codec's own private emitter parts
instead of restating them: a re-implementation could differ from the wire
in some lexeme and quietly become the thing being measured.  This harness
READS the wire and never changes it.  Its own faithfulness is proved on
every population member -- the object bytes are parsed back, transposed to
columnar shape, re-emitted through this module's sealer, and required to
equal :func:`encode_canonical_json` byte for byte.

Peak-memory numbers only mean anything in a process that ran one arm, so
every one of them comes from a fresh child (``_child``) that also asserts
its own execution provenance: editable installs and stale bytecode have
poisoned measurements in this repository before.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import subprocess
import sys
import tracemalloc
from collections.abc import Sequence
from pathlib import Path
from typing import Final, cast

from codeclone.canonical import (
    canonical_model_from_legacy_document,
    decode_canonical_json,
    encode_canonical_json,
    is_record_family,
    sparse_bool_wire_columns,
    wire_columns,
    wire_fact_family_order,
)

# Deliberate reuse of the encoder's own parts -- see the module docstring.
# The arms must differ in table shape and in nothing else.
from codeclone.canonical.codec import (
    WirePlan,
    _family_member,
    _leading_members,
    _member_lexeme,
    _Obj,
    _wire_integrity_domain,
    _write,
    fact_family_rows,
    fact_producer_sets,
    fact_root_sets,
    plan_from_parts,
    referenced_symbols,
)
from codeclone.canonical.model import CanonicalModel
from codeclone.contracts import CANONICAL_WIRE_REVISION

#: Domain tables of the ``domains`` member, with their column order as
#: ``_domains_member`` spells it.  Stated here so the inverse transpose
#: takes nothing from the columnar arm; a wrong entry cannot hide, because
#: the losslessness proof compares whole documents byte for byte.
_DOMAIN_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "files": ("path",),
    "modules": ("module",),
    "symbols": ("file", "qualname"),
}

_PAD: Final = "xxxxxxxx"  # PC1: eight fixed characters, one per key


# ---------------------------------------------------------------------------
# Execution provenance
# ---------------------------------------------------------------------------


def _provenance(worktree: Path) -> dict[str, str]:
    """Map every loaded ``codeclone`` module to its file, or refuse."""
    root = worktree.resolve()
    located: dict[str, str] = {}
    for name, module in sorted(sys.modules.items()):
        owned = name == "codeclone" or name.startswith("codeclone.")
        origin = getattr(module, "__file__", None)
        if not owned or origin is None:
            continue
        resolved = Path(origin).resolve()
        located[name] = str(resolved)
        if not resolved.is_relative_to(root):
            raise SystemExit(
                f"provenance refusal: {name} resolves to {resolved}, "
                f"outside the measurement worktree {root}"
            )
    return located


def _peak_rss_bytes() -> int:
    """Process peak RSS in bytes, normalized across platforms."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak) if sys.platform == "darwin" else int(peak) * 1024


# ---------------------------------------------------------------------------
# The object arm
# ---------------------------------------------------------------------------


def _seal(members: list[tuple[str, object]]) -> bytes:
    """Emit one document and seal it exactly as the wire emitter does."""
    body = ",".join(_member_lexeme(key, value) for key, value in members)
    domain = _wire_integrity_domain(CANONICAL_WIRE_REVISION)
    digest = hashlib.sha256(domain + body.encode("utf-8")).hexdigest()
    tail = _Obj([("algorithm", "sha256"), ("value", digest)])
    return ("{" + body + ',"integrity":' + _write(tail) + "}").encode("utf-8")


def _table_to_objects(table: _Obj, pad: str) -> list[object]:
    """One columnar domain table as an array of row objects."""
    columns = [key for key, _ in table.items]
    lists = [cast("list[object]", value) for _, value in table.items]
    if not lists:
        return []
    height = len(lists[0])
    for column in lists:
        if len(column) != height:
            raise SystemExit("domain table columns disagree in length")
    return [
        _Obj([(pad + columns[j], lists[j][i]) for j in range(len(columns))])
        for i in range(height)
    ]


def _reprojected_domains(domains: _Obj, pad: str) -> _Obj:
    """``domains`` with its three tables re-projected, ``effect_roots``
    carried through untouched -- a region both arms pay alike."""
    members: list[tuple[str, object]] = []
    for key, value in domains.items:
        if key in _DOMAIN_TABLES:
            members.append((key, _table_to_objects(cast("_Obj", value), pad)))
        else:
            members.append((key, value))
    return _Obj(members)


def _object_family_member(
    family: str, rows: Sequence[dict[str, object]], pad: str
) -> object:
    """One fact family as an array of row objects.

    A record family repeats no key per row and is emitted identically in
    both arms.  A sparse boolean is carried as the member ``1`` on true
    rows and omitted on false rows -- the object rendering most favourable
    to this arm, so the comparison stays conservative against columnar.
    """
    if is_record_family(family):
        # A record family repeats no key per row, so it is one of the
        # regions both arms pay alike -- and therefore one the padding
        # control must leave alone, or PC1 would predict a delta the
        # object arm never pays.
        if not rows:
            return _Obj([])
        (record,) = rows
        return _Obj([(column, record[column]) for column in wire_columns(family)])
    sparse = set(sparse_bool_wire_columns(family))
    out: list[object] = []
    for row in rows:
        members: list[tuple[str, object]] = []
        for column in wire_columns(family):
            if column in sparse:
                if row[column]:
                    members.append((pad + column, 1))
            else:
                members.append((pad + column, row[column]))
        out.append(_Obj(members))
    return out


def _normalized_plan(model: CanonicalModel) -> tuple[CanonicalModel, WirePlan]:
    """The normalized model and its projection plan -- one spelling.

    Both arms and the shape counter go through here, so the plan a
    measurement encodes and the plan it counts cannot drift apart.
    """
    normalized = model.normalize()
    facts = normalized.facts.analysis
    return normalized, plan_from_parts(
        files=normalized.files,
        modules=normalized.modules,
        symbols=referenced_symbols(facts),
        root_sets=fact_root_sets(facts),
        producer_sets=fact_producer_sets(facts),
        coupled_sets=normalized.coupled_sets,
        analyzed_files=normalized.analyzed_files,
        file_modules=normalized.file_modules,
    )


def encode_object_json(model: CanonicalModel, *, pad: str = "") -> bytes:
    """Project a canonical model to the array-of-objects wire form.

    The mirror of :func:`encode_canonical_json`: same normalization, same
    plan, same rows, same lexemes, same seal -- different table shape.
    """
    model, plan = _normalized_plan(model)
    facts = model.facts.analysis
    members: list[tuple[str, object]] = []
    for key, value in _leading_members(plan):
        if key == "domains":
            members.append((key, _reprojected_domains(cast("_Obj", value), pad)))
        else:
            members.append((key, value))
    families: list[tuple[str, object]] = [
        (
            family,
            _object_family_member(family, fact_family_rows(family, facts, plan), pad),
        )
        for family in wire_fact_family_order()
    ]
    members.append(("facts", _Obj(families)))
    return _seal(members)


def wire_shape_counts(model: CanonicalModel) -> tuple[int, int]:
    """``(rows, key_occurrences)`` over every re-projected table.

    ``key_occurrences`` is what the object arm pays and the columnar arm
    does not: one key name per row per emitted column.
    """
    model, plan = _normalized_plan(model)
    facts = model.facts.analysis
    domains = dict(cast("_Obj", dict(_leading_members(plan))["domains"]).items)
    rows = 0
    keys = 0
    for name, columns in _DOMAIN_TABLES.items():
        height = len(cast("list[object]", cast("_Obj", domains[name]).items[0][1]))
        rows += height
        keys += height * len(columns)
    for family in wire_fact_family_order():
        if is_record_family(family):
            continue
        family_rows = fact_family_rows(family, facts, plan)
        sparse = set(sparse_bool_wire_columns(family))
        rows += len(family_rows)
        for row in family_rows:
            for column in wire_columns(family):
                if column not in sparse or row[column]:
                    keys += 1
    return rows, keys


# ---------------------------------------------------------------------------
# Losslessness: the object bytes must carry the identical rows
# ---------------------------------------------------------------------------


def _plain(value: object) -> object:
    """Parsed JSON back into the emitter's ordered representation."""
    if isinstance(value, dict):
        pairs = cast("dict[str, object]", value)
        return _Obj([(key, _plain(item)) for key, item in pairs.items()])
    if isinstance(value, list):
        return [_plain(item) for item in cast("list[object]", value)]
    return value


def _rows_from_object_family(
    family: str, entries: list[object]
) -> list[dict[str, object]]:
    sparse = set(sparse_bool_wire_columns(family))
    rows: list[dict[str, object]] = []
    for entry in entries:
        source = cast("dict[str, object]", entry)
        row: dict[str, object] = {}
        for column in wire_columns(family):
            row[column] = column in source if column in sparse else source[column]
        rows.append(row)
    return rows


def _columnar_domains(value: object) -> _Obj:
    """Rebuild the columnar ``domains`` member from object rows."""
    rebuilt: list[tuple[str, object]] = []
    for name, member in cast("dict[str, object]", value).items():
        columns = _DOMAIN_TABLES.get(name)
        if columns is None:
            rebuilt.append((name, _plain(member)))
            continue
        entries = [
            cast("dict[str, object]", item) for item in cast("list[object]", member)
        ]
        table = [(column, [entry[column] for entry in entries]) for column in columns]
        rebuilt.append((name, _Obj(table)))
    return _Obj(rebuilt)


def _columnar_facts(value: object) -> _Obj:
    """Rebuild the columnar ``facts`` member from object rows."""
    families: list[tuple[str, object]] = []
    for family, member in cast("dict[str, object]", value).items():
        if is_record_family(family):
            record = cast("dict[str, object]", member)
            rows = [record] if record else []
        else:
            rows = _rows_from_object_family(family, cast("list[object]", member))
        families.append((family, _family_member(family, rows)))
    return _Obj(families)


def columnar_bytes_from_object_document(data: bytes) -> bytes:
    """Transpose an object-form document back and re-emit it columnar."""
    document = cast("dict[str, object]", json.loads(data))
    members: list[tuple[str, object]] = []
    for key, value in document.items():
        if key == "integrity":
            continue
        if key == "domains":
            members.append((key, _columnar_domains(value)))
        elif key == "facts":
            members.append((key, _columnar_facts(value)))
        else:
            members.append((key, _plain(value)))
    return _seal(members)


# ---------------------------------------------------------------------------
# The reader probe
# ---------------------------------------------------------------------------


def _rows_from_columnar(
    member: object, columns: Sequence[str], sparse: set[str], where: str
) -> list[object]:
    """Build row dicts from one columnar table -- what a columnar reader
    must do to hold rows.  A sparse boolean column carries true positions,
    so a dense column is what sizes the table."""
    table = cast("dict[str, list[object]]", member)
    dense = [column for column in columns if column not in sparse]
    if not dense:
        raise SystemExit(f"{where} has no dense column to size it")
    height = len(table[dense[0]])
    positions = {
        column: set(table[column])
        for column in columns
        if column in sparse and column in table
    }
    return [
        {
            **{column: table[column][index] for column in dense},
            **{column: index in seen for column, seen in positions.items()},
        }
        for index in range(height)
    ]


def _read_rows(
    member: object, columns: Sequence[str], sparse: set[str], arm: str, where: str
) -> list[object]:
    """One table's rows, arm-appropriately: the columnar reader builds
    them from columns, the object reader already holds them."""
    if arm == "columnar":
        return _rows_from_columnar(member, columns, sparse, where)
    return list(cast("list[object]", member))


def materialize_rows(data: bytes, arm: str) -> tuple[int, list[object]]:
    """Parse one document and materialize its rows, arm-appropriately.

    Both arms end holding the same rows.  The retained list is returned so
    the caller's peak reflects the materialization.
    """
    document = cast("dict[str, object]", json.loads(data))
    held: list[object] = []
    total = 0
    domains = cast("dict[str, object]", document["domains"])
    for name, columns in _DOMAIN_TABLES.items():
        rows = _read_rows(domains[name], columns, set(), arm, f"domain {name}")
        held.append(rows)
        total += len(rows)
    facts = cast("dict[str, object]", document["facts"])
    for family in wire_fact_family_order():
        if is_record_family(family):
            continue
        rows = _read_rows(
            facts[family],
            wire_columns(family),
            set(sparse_bool_wire_columns(family)),
            arm,
            f"family {family}",
        )
        held.append(rows)
        total += len(rows)
    return total, held


# ---------------------------------------------------------------------------
# Children: one arm, one phase, one process
# ---------------------------------------------------------------------------


def _load_model(report: Path) -> CanonicalModel:
    document = cast("dict[str, object]", json.loads(report.read_text("utf-8")))
    return canonical_model_from_legacy_document(document)


def _encode_arm(model: CanonicalModel, arm: str) -> bytes:
    """One arm's bytes -- the single place an arm name becomes an encoder."""
    if arm == "columnar":
        return encode_canonical_json(model)
    if arm == "object":
        return encode_object_json(model)
    return encode_object_json(model, pad=_PAD)


def _child_encode(args: argparse.Namespace, worktree: Path) -> dict[str, object]:
    model = _load_model(Path(args.report))
    arm = str(args.arm)
    tracemalloc.start()
    first = _encode_arm(model, arm)
    _, step_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    second = _encode_arm(model, arm)
    rows, keys = wire_shape_counts(model)
    if args.bytes_out:
        Path(args.bytes_out).write_bytes(first)
    return {
        "arm": arm,
        "bytes": len(first),
        "sha256": hashlib.sha256(first).hexdigest(),
        "sha256_repeat_in_process": hashlib.sha256(second).hexdigest(),
        "rows": rows,
        "key_occurrences": keys,
        "encode_peak_rss_bytes": _peak_rss_bytes(),
        "encode_step_tracemalloc_peak_bytes": step_peak,
        "provenance_modules": len(_provenance(worktree)),
    }


def _child_decode(args: argparse.Namespace, worktree: Path) -> dict[str, object]:
    data = Path(args.bytes).read_bytes()
    megabytes = int(args.ballast_mib)
    ballast = bytearray(megabytes * 1024 * 1024) if megabytes else None
    tracemalloc.start()
    total, held = materialize_rows(data, str(args.arm))
    _, step_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak = _peak_rss_bytes()
    result = {
        "arm": str(args.arm),
        "rows_materialized": total,
        "decode_peak_rss_bytes": peak,
        "decode_step_tracemalloc_peak_bytes": step_peak,
        "ballast_mib": int(args.ballast_mib),
        "provenance_modules": len(_provenance(worktree)),
    }
    del held, ballast
    return result


def _child_verify(args: argparse.Namespace, worktree: Path) -> dict[str, object]:
    model = _load_model(Path(args.report))
    columnar = encode_canonical_json(model)
    obj = encode_object_json(model)
    padded = encode_object_json(model, pad=_PAD)
    rows, keys = wire_shape_counts(model)
    decoded_ok = False
    roundtrip_ok = False
    try:
        decoded_ok = True
        roundtrip_ok = decode_canonical_json(columnar) == model.normalize()
    except Exception as error:
        return {
            "columnar_decode_ok": False,
            "columnar_decode_error": repr(error),
            "provenance_modules": len(_provenance(worktree)),
        }
    rebuilt = columnar_bytes_from_object_document(obj)
    object_decode_ok = False
    object_roundtrip_ok = False
    try:
        object_decode_ok = True
        object_roundtrip_ok = decode_canonical_json(rebuilt) == model.normalize()
    except Exception as error:
        object_decode_ok = False
        object_roundtrip_ok = False
        _ = error
    return {
        "columnar_bytes": len(columnar),
        "object_bytes": len(obj),
        "object_padded_bytes": len(padded),
        "rows": rows,
        "key_occurrences": keys,
        "pc1_predicted_delta": len(_PAD) * keys,
        "pc1_observed_delta": len(padded) - len(obj),
        "pc1_holds": len(padded) - len(obj) == len(_PAD) * keys,
        "columnar_decode_ok": decoded_ok,
        "columnar_roundtrip_ok": roundtrip_ok,
        "object_lossless_bytes_equal": rebuilt == columnar,
        "object_decode_ok": object_decode_ok,
        "object_roundtrip_ok": object_roundtrip_ok,
        "provenance_modules": len(_provenance(worktree)),
    }


def _child(args: argparse.Namespace) -> int:
    worktree = Path(__file__).resolve().parent.parent
    _provenance(worktree)
    phase = str(args.phase)
    payload: dict[str, object]
    if phase == "encode":
        payload = _child_encode(args, worktree)
    elif phase == "decode":
        payload = _child_decode(args, worktree)
    elif phase == "verify":
        payload = _child_verify(args, worktree)
    else:
        payload = {"provenance": _provenance(worktree)}
    payload["platform"] = platform.platform()
    payload["python"] = sys.version.split()[0]
    print(json.dumps(payload, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------
# Parent: population preparation
# ---------------------------------------------------------------------------


def _cli(root: Path, extra: list[str]) -> None:
    """One spelling of a CodeClone CLI invocation for corpus preparation."""
    subprocess.run(
        [sys.executable, "-m", "codeclone.main", str(root), "--no-progress", *extra],
        check=False,
        capture_output=True,
    )


def _materialize_corpus(fixture: Path, target: Path, withhold: str | None) -> None:
    """Write the wire-freeze corpus from its inert ``*.txt`` carriers."""
    for carrier in sorted(fixture.rglob("*.txt")):
        relative = carrier.relative_to(fixture).with_suffix("")
        if withhold is not None and relative.as_posix() == withhold:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(carrier.read_text("utf-8"), "utf-8")


def _prepare_member(member: dict[str, object], lab: Path, repo: Path) -> Path:
    """Produce the frozen legacy report document of one member."""
    name = str(member["name"])
    recipe = str(member["report_recipe"])
    report = lab / "reports" / f"{name}.json"
    baseline = lab / "baselines" / f"{name}.json"
    common = ["--semantic-authority", "--api-surface"]
    if recipe == "two_stage_corpus":
        target = lab / "corpus"
        fixture = repo / "tests" / "fixtures" / "wire_freeze_corpus"
        _materialize_corpus(fixture, target, "pkg/clones_three.py")
        _cli(target, ["--baseline", str(baseline), "--update-baseline", *common])
        _materialize_corpus(fixture, target, None)
        _cli(target, ["--baseline", str(baseline), "--json", str(report), *common])
        return report
    root = Path(str(member["path"]))
    if recipe == "self_repo_existing_baseline":
        _cli(root, ["--json", str(report), *common])
        return report
    _cli(root, ["--baseline", str(baseline), "--update-baseline", *common])
    _cli(root, ["--baseline", str(baseline), "--json", str(report), *common])
    return report


# ---------------------------------------------------------------------------
# Parent: measurement
# ---------------------------------------------------------------------------


def _run_child(script: Path, argv: list[str]) -> dict[str, object]:
    """Run one measurement child and read its single JSON line."""
    finished = subprocess.run(
        [sys.executable, str(script), "_child", *argv],
        check=False,
        capture_output=True,
        text=True,
    )
    if finished.returncode != 0:
        raise SystemExit(
            f"child failed ({finished.returncode}): {' '.join(argv)}\n"
            f"{finished.stderr[-2000:]}"
        )
    line = finished.stdout.strip().splitlines()[-1]
    return cast("dict[str, object]", json.loads(line))


def _slope(points: list[tuple[float, float]]) -> dict[str, float]:
    """Ordinary least squares fit of ``bytes = a + b * rows``."""
    count = len(points)
    if count < 2:
        return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    total = sum((y - mean_y) ** 2 for _, y in points)
    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": 1.0 - residual / total if total else 0.0,
    }


def _measure_member(
    script: Path, name: str, report: Path, lab: Path
) -> dict[str, object]:
    """Every pre-registered quantity for one population member."""
    wire = lab / "wire"
    wire.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {"name": name}
    encodes: dict[str, dict[str, object]] = {}
    for arm in ("columnar", "object", "object_padded"):
        target = wire / f"{name}.{arm}.json"
        encodes[arm] = _run_child(
            script,
            [
                "--phase",
                "encode",
                "--arm",
                arm,
                "--report",
                str(report),
                "--bytes-out",
                str(target),
            ],
        )
        fresh = _run_child(
            script,
            ["--phase", "encode", "--arm", arm, "--report", str(report)],
        )
        encodes[arm]["sha256_fresh_process"] = fresh["sha256"]
        encodes[arm]["deterministic"] = (
            encodes[arm]["sha256"] == encodes[arm]["sha256_repeat_in_process"]
            and encodes[arm]["sha256"] == fresh["sha256"]
        )
        encodes[arm]["decode"] = _run_child(
            script,
            ["--phase", "decode", "--arm", arm, "--bytes", str(target)],
        )
    result["encode"] = encodes
    result["verify"] = _run_child(
        script, ["--phase", "verify", "--report", str(report)]
    )
    return result


def _controls(script: Path, lab: Path, witness: Path) -> dict[str, object]:
    """PC2 (memory instrument) and PC3 (noise floor) on one witness."""
    repeats = [
        _run_child(
            script, ["--phase", "decode", "--arm", "columnar", "--bytes", str(witness)]
        )
        for _ in range(5)
    ]
    peaks = [int(cast("int", run["decode_peak_rss_bytes"])) for run in repeats]
    ballasted = _run_child(
        script,
        [
            "--phase",
            "decode",
            "--arm",
            "columnar",
            "--bytes",
            str(witness),
            "--ballast-mib",
            "64",
        ],
    )
    ballast_peak = int(cast("int", ballasted["decode_peak_rss_bytes"]))
    rise = ballast_peak - max(peaks)
    _ = lab
    return {
        "pc3_noise_floor": {
            "peaks_bytes": peaks,
            "spread_bytes": max(peaks) - min(peaks),
            "witness": witness.name,
        },
        "pc2_memory_instrument": {
            "ballast_mib": 64,
            "peak_without_ballast_bytes": max(peaks),
            "peak_with_ballast_bytes": ballast_peak,
            "rise_bytes": rise,
            "holds": rise >= 60 * 1024 * 1024,
        },
    }


def _measure(lab: Path, script: Path, prereg: dict[str, object], digest: str) -> int:
    population = cast("list[dict[str, object]]", prereg["population"])
    results: list[dict[str, object]] = []
    incomplete: list[dict[str, str]] = []
    for member in population:
        name = str(member["name"])
        report = lab / "reports" / f"{name}.json"
        if not report.exists():
            incomplete.append({"name": name, "reason": "report document missing"})
            continue
        try:
            results.append(_measure_member(script, name, report, lab))
        except SystemExit as error:
            incomplete.append({"name": name, "reason": str(error)[:400]})
        print(f"measured {name}", flush=True)
    slopes: dict[str, object] = {}
    for arm in ("columnar", "object"):
        points = [
            (
                float(cast("int", cast("dict[str, object]", r["verify"])["rows"])),
                float(
                    cast(
                        "int",
                        cast("dict[str, dict[str, object]]", r["encode"])[arm]["bytes"],
                    )
                ),
            )
            for r in results
        ]
        slopes[arm] = _slope(points)
    witness = lab / "wire" / "self_codeclone.columnar.json"
    if not witness.exists() and results:
        witness = lab / "wire" / f"{results[0]['name']}.columnar.json"
    payload = {
        "preregistration_sha256": digest,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "members": results,
        "incomplete": incomplete,
        "slopes": slopes,
        "controls": _controls(script, lab, witness) if witness.exists() else {},
    }
    out = lab / "RESULTS.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"results: {out}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "measure"):
        step = sub.add_parser(name)
        step.add_argument("--lab", required=True)
    child = sub.add_parser("_child")
    child.add_argument("--phase", required=True)
    child.add_argument("--arm", default="columnar")
    child.add_argument("--report", default="")
    child.add_argument("--bytes", default="")
    child.add_argument("--bytes-out", default="")
    child.add_argument("--ballast-mib", default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Prepare the frozen population, or measure both arms over it."""
    args = _parser().parse_args(argv)
    if args.command == "_child":
        return _child(args)
    lab = Path(str(args.lab)).resolve()
    repo = Path(__file__).resolve().parent.parent
    _provenance(repo)
    prereg_path = lab / "PREREGISTRATION.json"
    text = prereg_path.read_text("utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    prereg = cast("dict[str, object]", json.loads(text))
    print(f"preregistration sha256: {digest}")
    if args.command == "prepare":
        for member in cast("list[dict[str, object]]", prereg["population"]):
            report = _prepare_member(member, lab, repo)
            state = "ok" if report.exists() else "MISSING"
            print(f"prepared {member['name']}: {state}", flush=True)
        return 0
    return _measure(lab, Path(__file__).resolve(), prereg, digest)


if __name__ == "__main__":
    raise SystemExit(main())
