# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every generation constant that keys the analysis cache, and what it owes.

A generation constant is a promise: bump it and the cache stops serving what
the old algorithm computed. The promise has two halves, and only the second
one is ever noticed when it breaks.

    at the CURRENT value  a warm run must utter exactly what a cold run uttered
    at a PREVIOUS value   a cache written then must MISS, not be served

The first half breaking is loud - a warm run says something different from a
cold one and a user sees two answers to one question. The second half breaking
is SILENT: the run is fast, the report looks fine, and it is the previous
algorithm's answer wearing this build's schema. That is the failure this
module exists to make impossible, and it is why the miss arm carries a
positive control rather than an assertion.

The constants are not a list somebody maintains. They are ENUMERATED from the
producer: every public constant of :mod:`codeclone.contracts` is perturbed in
turn and the two cache-lane digests are recomputed, so a constant that keys a
lane declares itself. The literal table below is therefore a RATCHET over that
enumeration, not its source - adding a keying constant without deciding what
its previous generation means reds here.

Known limitation, carried deliberately rather than fixed: ``MODULE_IDENTITY_
VERSION`` reaches the dependent profile only through ``module_manifest_digest``
which the enumeration supplies as a fixed stand-in, so it is outside this
enumeration by construction and outside this module's claim.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

import codeclone
from codeclone import contracts

#: The repository this test process imported. Every spawned run is required to
#: import the same one: a child that resolved ``codeclone`` from site-packages
#: or from another worktree would answer about a different build, and the
#: measurement would be about code nobody is reviewing.
REPO_ROOT: Final = Path(codeclone.__file__).resolve().parent.parent

#: The two cache lanes, and which constants key each of them. Measured by
#: :func:`_enumerate_cache_keying_constants`, pinned here so that a new keying
#: constant cannot arrive unnoticed. ``neutral+dependent`` is a constant the
#: neutral profile keys and the dependent profile therefore inherits.
_NEUTRAL: Final = "neutral+dependent"
_DEPENDENT: Final = "dependent"

CACHE_KEYING_CONSTANTS: Final[Mapping[str, str]] = {
    "ADOPTION_COVERAGE_POLICY_VERSION": _DEPENDENT,
    "API_SURFACE_SIGNATURE_VERSION": _DEPENDENT,
    "BASELINE_FINGERPRINT_VERSION": _NEUTRAL,
    "COHESION_RISK_MEDIUM_MAX": _DEPENDENT,
    "COMPLEXITY_ALGORITHM_REVISION": _NEUTRAL,
    "COMPLEXITY_RISK_LOW_MAX": _NEUTRAL,
    "COMPLEXITY_RISK_MEDIUM_MAX": _NEUTRAL,
    "COUPLING_RISK_LOW_MAX": _DEPENDENT,
    "COUPLING_RISK_MEDIUM_MAX": _DEPENDENT,
    "DESIGN_METRICS_ALGORITHM_REVISION": _DEPENDENT,
    "FUNCTION_RELATIONSHIP_ALGORITHM_REVISION": _DEPENDENT,
    "LIVENESS_POLICY_VERSION": _DEPENDENT,
    "RENAMED_STRUCTURE_ALGORITHM_REVISION": _NEUTRAL,
    "RUNTIME_REACHABILITY_CATALOG_VERSION": _DEPENDENT,
    "SECURITY_SURFACE_CATALOG_VERSION": _DEPENDENT,
    "SEMANTIC_EVENT_VERSION": _NEUTRAL,
    "STATEMENT_REACHABILITY_POLICY_VERSION": _NEUTRAL,
    "STRUCTURAL_FINDINGS_CATALOG_VERSION": _DEPENDENT,
    "WIRE_VERSION": _NEUTRAL,
}

#: The enumeration runs in a SPAWNED interpreter, and for two reasons that
#: happen to agree.
#:
#: The architectural one: a test module is ring 4 and the cache profile
#: builders are ring 2, so importing them here would open the phase-39S
#: boundary ratchet - a shrink-only allowlist - for a convenience.
#:
#: The methodological one, which would justify it on its own: the
#: enumeration rebinds a contracts constant in every module that already
#: bound it, and a leak would silently make every later measurement - in
#: this module and in every test after it - a statement about the wrong
#: build. A child process cannot leak into the parent, so the isolation is
#: structural rather than a promise made by a ``finally`` block.
_ENUMERATION_PROGRAM: Final = '''
"""Perturb every public contracts constant; report which move a cache lane."""

import json
import pathlib
import sys
import types

import codeclone
import codeclone.contracts as contracts
from codeclone.cache import reuse
from codeclone.models import DigestObject

assert pathlib.Path(codeclone.__file__).resolve().parent.parent == pathlib.Path(
    sys.argv[1]
), codeclone.__file__

STUB_MANIFEST = DigestObject(
    domain="codeclone.module-manifest.v1", algorithm="sha256", value="0" * 64
)
THRESHOLDS = dict(
    min_loc=5,
    min_stmt=3,
    block_min_loc=20,
    block_min_stmt=8,
    segment_min_loc=20,
    segment_min_stmt=10,
)


def lane_digests():
    neutral = reuse.build_module_neutral_profile(
        fingerprint_version=contracts.BASELINE_FINGERPRINT_VERSION, **THRESHOLDS
    )
    dependent = reuse.build_module_dependent_profile(
        neutral_profile=neutral,
        module_manifest_digest=STUB_MANIFEST,
        collect_api_surface=True,
    )
    return neutral.value, dependent.value


def perturbed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1000
    return f"{value}-perturbed"


def rebind_everywhere(name, value):
    """Set the constant the way a real bump lands: contracts AND every importer.

    Patching only ``contracts`` leaves every module that bound the value at
    import time holding the old number, and the enumeration under-reports.
    """
    current = getattr(contracts, name)
    undo = [(contracts, name, current)]
    setattr(contracts, name, value)
    for module in list(sys.modules.values()):
        if not isinstance(module, types.ModuleType):
            continue
        if not str(getattr(module, "__name__", "")).startswith("codeclone."):
            continue
        if getattr(module, name, object()) == current:
            undo.append((module, name, current))
            setattr(module, name, value)
    return undo


PUBLIC = sorted(n for n in dir(contracts) if n.isupper() and not n.startswith("_"))
baseline = lane_digests()
keying = {}
for name in PUBLIC:
    undo = rebind_everywhere(name, perturbed(getattr(contracts, name)))
    try:
        moved = lane_digests()
    finally:
        for holder, attribute, original in undo:
            setattr(holder, attribute, original)
    # Restoration is asserted per constant: a leak would make every later row
    # a measurement of the wrong build.
    assert lane_digests() == baseline, name
    if moved[0] != baseline[0]:
        keying[name] = "neutral+dependent"
    elif moved[1] != baseline[1]:
        keying[name] = "dependent"

json.dump({"scanned": len(PUBLIC), "keying": keying}, sys.stdout)
'''


def _enumerate_cache_keying_constants() -> dict[str, object]:
    """Ask the producer, in a process of its own, which constants key a lane."""

    completed = subprocess.run(
        [sys.executable, "-c", _ENUMERATION_PROGRAM, str(REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    enumerated = json.loads(completed.stdout)
    assert isinstance(enumerated, dict)
    return enumerated


def test_the_cache_keying_constants_are_exactly_the_enumerated_set() -> None:
    """The table is re-derived from the producer, never trusted.

    A constant that starts keying a lane arrives here as a red naming itself,
    which is the moment somebody has to say what its previous generation is
    and what a stale cache at that generation must do.
    """

    enumerated = _enumerate_cache_keying_constants()
    keying = enumerated["keying"]
    scanned = enumerated["scanned"]
    assert isinstance(keying, dict)
    assert isinstance(scanned, int)

    assert keying == dict(CACHE_KEYING_CONSTANTS)
    # Population witness: an enumeration that scanned nothing, or that failed
    # to perturb anything, would agree with an empty table and leave both
    # halves below measuring nothing.
    assert scanned >= 141
    assert len(keying) >= 19
    assert _NEUTRAL in set(keying.values())
    assert _DEPENDENT in set(keying.values())


def previous_generation(value: object) -> object:
    """The value one generation back, DERIVED rather than tabulated.

    Writing the previous values down would put nineteen magic numbers in this
    file and let them rot the day any of them is bumped. Deriving them keeps
    the rule - "whatever this constant said before" - as the thing under test.

    Six of these previous values really shipped and thirteen are synthetic. A
    synthetic member is the point: the law is that ANY earlier value must
    miss, and a class with no shipped member still has to be populated rather
    than excused.
    """

    if isinstance(value, bool):  # pragma: no cover - no boolean keys today
        raise AssertionError("a boolean generation has no previous value")
    if isinstance(value, int):
        assert value >= 1, value
        return value - 1
    assert isinstance(value, str) and value.isdigit(), value
    assert int(value) >= 1, value
    return str(int(value) - 1)


# --------------------------------------------------------------------------
# The spawned arm: what a real run does with a real cache file.

#: A corpus that leaves no cache lane empty: a public API surface, a class
#: with coupling and cohesion, branchy code, a security sink, an unreachable
#: tail, a private helper only a test calls, and a renamed twin.
_CORPUS: Final[Mapping[str, str]] = {
    "pkg/__init__.py": (
        "from .core import PublicWorker, public_helper\n\n"
        '__all__ = ["PublicWorker", "public_helper"]\n'
    ),
    "pkg/core.py": '''
"""Public module: api surface, adoption counters, classes, complexity."""

from __future__ import annotations

import os
import subprocess


class PublicWorker:
    """A class with coupling and cohesion to measure."""

    def __init__(self, name: str, size: int) -> None:
        self.name = name
        self.size = size
        self.cache: dict[str, int] = {}

    def compute(self, values: list[int]) -> int:
        """Branchy enough to carry a real cyclomatic count."""
        total = 0
        for value in values:
            if value > 10:
                total += value
            elif value > 5:
                total -= value
            elif value < 0:
                total *= 2
            else:
                total += 1
        while total > 1000:
            total //= 2
        try:
            total = total // self.size
        except ZeroDivisionError:
            total = 0
        return total

    def dispatch(self) -> int:
        return self._private_step()

    def _private_step(self) -> int:
        return self.size + 1


def public_helper(items: list[str], flag: bool = False) -> str:
    """Documented public helper; adoption counters see the annotations."""
    if flag:
        return ",".join(items)
    return ";".join(items)


def runs_a_command(argument: str) -> int:
    """A security-surface sink: subprocess with a non-literal argument."""
    return subprocess.call(argument, shell=True)


def reads_environment() -> str:
    return os.environ.get("CODECLONE_PROBE", "")


def has_unreachable_tail(value: int) -> int:
    """Statement reachability: the tail is provably unreachable."""
    return value
    value += 1
    return value
''',
    "pkg/_support.py": '''
def internal_only(value: int) -> int:
    return value * 3


def never_referenced_at_all(value: int) -> int:
    return value - 1


def only_tests_call_me(value: int) -> int:
    return value + 7
''',
    "pkg/consumer.py": '''
from .core import PublicWorker, public_helper
from ._support import internal_only


def drive(values: list[int]) -> int:
    worker = PublicWorker("probe", 2)
    joined = public_helper([str(v) for v in values])
    return worker.compute(values) + internal_only(len(joined))
''',
    "pkg/twin.py": '''
from .core import PublicWorker, public_helper
from ._support import internal_only


def steer(numbers: list[int]) -> int:
    engine = PublicWorker("probe", 2)
    text = public_helper([str(n) for n in numbers])
    return engine.compute(numbers) + internal_only(len(text))
''',
    "tests/__init__.py": "\n",
    "tests/test_support.py": '''
from pkg._support import only_tests_call_me


def test_only_tests_call_me() -> None:
    assert only_tests_call_me(1) == 8
''',
}

_SCOPE_ID: Final = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f4f"

#: Report paths a warm run may legitimately utter differently from a cold one
#: because they are WALL CLOCK, plus the one digest computed over the whole
#: document and therefore over them.
VOLATILE_PATHS: Final[frozenset[str]] = frozenset(
    {
        "meta.runtime.analysis_started_at_utc",
        "meta.runtime.report_generated_at_utc",
        "integrity.digests.envelope.value",
    }
)

#: The run's ACCOUNTING of how it was served: its own report ABOUT the cache,
#: not the semantics the cache serves. These MUST differ between a cold run
#: and a warm one, and asserting that they do is what proves the pair really
#: is one of each. Nothing else may differ - a sixth field is a finding.
CACHE_ACCOUNTING_PATHS: Final[frozenset[str]] = frozenset(
    {
        "inventory.files.analyzed",
        "inventory.files.cached",
        "meta.cache.used",
        "meta.cache.status",
        "meta.cache.schema_version",
    }
)


def _spawn(
    project: Path,
    cache_path: Path,
    report_path: Path,
    *,
    generation: tuple[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    """One analysis, in a fresh interpreter, optionally at another generation.

    ``generation`` is applied to ``codeclone.contracts`` BEFORE the pipeline is
    imported, which is where a real bump lands: any consumer that binds the
    value at import time then binds the injected one.
    """

    preamble = (
        "import pathlib, codeclone, codeclone.contracts as contracts\n"
        "assert pathlib.Path(codeclone.__file__).resolve().parent.parent == "
        f"pathlib.Path({str(REPO_ROOT)!r}), codeclone.__file__\n"
    )
    if generation is not None:
        name, value = generation
        preamble += (
            f"assert hasattr(contracts, {name!r}), {name!r}\n"
            f"contracts.{name} = {value!r}\n"
            f"assert contracts.{name} == {value!r}\n"
        )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            preamble + "from codeclone.surfaces.cli.workflow import main; main()",
            str(project),
            "--cache-path",
            str(cache_path),
            "--json",
            str(report_path),
            "--no-skip-metrics",
            "--no-skip-dead-code",
            "--api-surface",
            "--near-miss",
            "--renamed-structure",
            "--no-progress",
            "--processes",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


def _run(
    project: Path,
    cache_path: Path,
    report_path: Path,
    *,
    generation: tuple[str, object] | None = None,
) -> dict[str, object]:
    completed = _spawn(project, cache_path, report_path, generation=generation)
    assert report_path.exists(), completed.stdout + completed.stderr
    payload = json.loads(report_path.read_text("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _service(payload: dict[str, object]) -> dict[str, object]:
    """The run's own account of how the cache served it."""

    meta = payload["meta"]
    assert isinstance(meta, dict)
    cache = meta["cache"]
    assert isinstance(cache, dict)
    inventory = payload["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, dict)
    return {
        "used": cache.get("used"),
        "total_found": files["total_found"],
        "analyzed": files["analyzed"],
        "cached": files["cached"],
    }


def _differing_paths(
    left: object, right: object, path: tuple[str, ...] = ()
) -> set[str]:
    """Every leaf path at which two report documents disagree."""

    if isinstance(left, dict) and isinstance(right, dict):
        found: set[str] = set()
        for key in sorted(set(left) | set(right)):
            found |= _differing_paths(left.get(key), right.get(key), (*path, key))
        return found
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return {".".join((*path, "[len]"))}
        found = set()
        for item, other in zip(left, right, strict=True):
            found |= _differing_paths(item, other, (*path, "[]"))
        return found
    return set() if left == right else {".".join(path)}


def _projection_digest(payload: dict[str, object]) -> str:
    """A canonical digest of the report with the excluded paths removed."""

    excluded = VOLATILE_PATHS | CACHE_ACCOUNTING_PATHS

    def strip(node: object, path: tuple[str, ...]) -> object:
        if isinstance(node, dict):
            return {
                key: strip(value, (*path, key))
                for key, value in sorted(node.items())
                if ".".join((*path, key)) not in excluded
            }
        if isinstance(node, list):
            return [strip(value, (*path, "[]")) for value in node]
        return node

    canonical = json.dumps(strip(payload, ()), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _materialize(root: Path) -> Path:
    for name, source in _CORPUS.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.lstrip(), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n', encoding="utf-8"
    )
    return root


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One materialized corpus, shared by every arm in this module."""

    return _materialize(tmp_path_factory.mktemp("generation-keys") / "project")


def test_a_warm_run_at_the_current_generation_utters_the_cold_run(
    project: Path, tmp_path: Path
) -> None:
    """The loud half: at the CURRENT generation, warm equals cold.

    The two runs share ONE cache path, so the cache's own path fields cannot
    differ and need no exclusion. What remains is the accounting - and the
    accounting is asserted to move, because a pair that agreed everywhere
    would be two cold runs and would prove nothing about serving.
    """

    cache = tmp_path / "shared-cache.json"
    cold = _run(project, cache, tmp_path / "cold-report.json")
    warm = _run(project, cache, tmp_path / "warm-report.json")

    cold_service = {"used": False, "total_found": 7, "analyzed": 7, "cached": 0}
    warm_service = {"used": True, "total_found": 7, "analyzed": 0, "cached": 7}
    assert _service(cold) == cold_service
    assert _service(warm) == warm_service

    differences = _differing_paths(cold, warm)
    assert differences.issuperset(CACHE_ACCOUNTING_PATHS), (
        "the accounting did not move, so these are not a cold run and a warm "
        f"one: {sorted(differences)}"
    )
    unexplained = differences - CACHE_ACCOUNTING_PATHS - VOLATILE_PATHS
    assert unexplained == set(), (
        "a warm run said something a cold run did not, outside the named "
        f"accounting and wall-clock fields: {sorted(unexplained)}"
    )
    assert _projection_digest(cold) == _projection_digest(warm)


def test_the_projection_still_sees_a_change_the_cache_must_not_hide(
    project: Path, tmp_path: Path
) -> None:
    """Probe validity for the arm above: the projection is not blind.

    A projection with the wrong exclusions would report equality for two runs
    that differ in anything. Adding one definition to the corpus must move the
    digest; if it does not, the equality above is an artefact of the
    projection rather than a statement about the cache.
    """

    reference = _run(project, tmp_path / "ref-cache.json", tmp_path / "ref.json")

    support = project / "pkg/_support.py"
    original = support.read_text("utf-8")
    support.write_text(
        original + "\n\ndef control_a_new_definition(x: int) -> int:\n"
        "    if x:\n        return x\n    return 0\n",
        encoding="utf-8",
    )
    try:
        perturbed = _run(
            project, tmp_path / "ctrl-cache.json", tmp_path / "ctrl.json"
        )
    finally:
        support.write_text(original, encoding="utf-8")

    assert _projection_digest(perturbed) != _projection_digest(reference)


@pytest.mark.parametrize("constant", sorted(CACHE_KEYING_CONSTANTS))
def test_a_cache_written_at_a_previous_generation_is_not_served(
    project: Path, tmp_path: Path, constant: str
) -> None:
    """The silent half, with the control that makes the miss mean anything.

    Three runs:

    ``write``    cold, at the PREVIOUS generation - populates the cache
    ``read``     at the CURRENT generation - the law: it must MISS
    ``control``  the SAME cache, read again at the PREVIOUS generation - it
                 must HIT

    The control is the load-bearing one. Without it a miss is equally well
    explained by an injected value that never reached the profile builder, by
    a mistyped cache path, or by a corpus the cache never held. The control
    reads the same bytes on the same causal path and is served from them, so
    the only thing left to explain the miss is the generation key.
    """

    current = getattr(contracts, constant)
    previous = previous_generation(current)
    assert previous != current

    cache = tmp_path / "cache.json"
    written = _run(
        project, cache, tmp_path / "write.json", generation=(constant, previous)
    )
    assert _service(written)["cached"] == 0, "the write arm was itself served"

    control_cache = tmp_path / "control-cache.json"
    for suffix in ("", "-shm", "-wal"):
        source = Path(str(cache) + suffix)
        if source.exists():
            Path(str(control_cache) + suffix).write_bytes(source.read_bytes())

    read = _service(_run(project, cache, tmp_path / "read.json"))
    control = _service(
        _run(
            project,
            control_cache,
            tmp_path / "control.json",
            generation=(constant, previous),
        )
    )

    assert control == {
        "used": True,
        "total_found": 7,
        "analyzed": 0,
        "cached": 7,
    }, (
        f"the control did not hit, so the {constant} miss below explains "
        f"nothing: {control}"
    )

    # A previous generation is refused either at the ENVELOPE - the cache file
    # as a whole is rejected and ``used`` is False - or per entry, where the
    # file is opened and every row misses. Which one a constant triggers is a
    # property of the lane it keys; the law is about SERVING, so the counts are
    # what is asserted and ``used`` is deliberately left free.
    assert read["cached"] == 0 and read["analyzed"] == read["total_found"] == 7, (
        f"a cache written at {constant}={previous!r} was served to a run at "
        f"{constant}={current!r}: {read}"
    )
