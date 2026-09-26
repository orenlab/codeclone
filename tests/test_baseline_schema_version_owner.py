# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``BASELINE_SCHEMA_VERSION`` is the one owner of the baseline schema version.

The version used to be spelled twice: the constant gated the loaded baseline,
while a literal wrote the container, gated the container reader and targeted
the legacy transition. Moving the constant then produced a container the same
build refused as ``MISMATCH_SCHEMA_VERSION``. These tests move the owner in
both directions and require every writer, gate and report projection to follow
it, forbid the value from being spelled anywhere else in production, and pin
the type-level spellings -- which cannot name a runtime constant -- equal to it.
"""

from __future__ import annotations

import ast
import sys
import typing
from pathlib import Path
from types import ModuleType
from uuid import UUID

import orjson
import pytest

import codeclone.baseline.container as container_mod
import codeclone.baseline.publish as publish_mod
import codeclone.baseline.transition as transition_mod
import codeclone.contracts as contracts_mod
from codeclone.baseline._metrics_baseline_contract import MetricsBaselineStatus
from codeclone.baseline.clone_baseline import Baseline
from codeclone.baseline.container import read_container_v3
from codeclone.baseline.metrics_baseline import MetricsBaseline
from codeclone.baseline.trust import BaselineStatus, _compute_payload_sha256
from codeclone.contracts import BASELINE_SCHEMA_VERSION
from codeclone.contracts.errors import BaselineValidationError
from codeclone.models import (
    BaselineMeta,
    ContainerReadFailure,
    ContainerReadSuccess,
    EpochTransitionEvidence,
    EpochTransitionEvidenceInput,
    ObservationBundle,
)
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import module_registry_context

_SCOPE_ID = UUID("019f7fa1-8866-7242-b0bf-0ff282cafbcb")
_LIMIT = 5_000_000
_PYTHON_TAG = "cp314"
_FUNCTION_ID = f"{'a' * 64}|0-19"
_BLOCK_ID = "|".join(("b" * 64,) * 4)
# One value above the owner and one below, derived from it so that neither can
# ever coincide with the owner: a site that still spells the old version is
# wrong in either direction, and each direction is its own case.
_MAJOR, _MINOR = (int(part) for part in BASELINE_SCHEMA_VERSION.split("."))
_ABOVE = f"{_MAJOR}.{_MINOR + 1}"
_BELOW = f"{_MAJOR - 1}.9"
_MOVED_OWNER = pytest.mark.parametrize(
    "version",
    (_ABOVE, _BELOW),
    ids=("owner-above", "owner-below"),
)
# The only place the value may be written down: the contract home.
_OWNER_HOME = "codeclone/contracts/__init__.py"
# The type-level spellings. A ``Literal`` cannot reference the constant, so
# each one is named here and pinned equal to the owner below; any other
# spelling of the value in production is a second owner.
_TYPED_SPELLINGS = (
    ("codeclone/models.py", "BaselineMeta", "container_version"),
    ("codeclone/models.py", "EpochTransitionEvidence", "to_schema"),
    ("codeclone/models.py", "EpochTransitionEvidenceInput", "to_schema"),
)


@pytest.fixture(autouse=True)
def _stable_container_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "current_python_tag", lambda: _PYTHON_TAG)
    monkeypatch.setattr(container_mod, "_utc_now_z", lambda: "2026-07-20T00:00:00Z")


def _move_owner(monkeypatch: pytest.MonkeyPatch, version: str) -> tuple[str, ...]:
    """Rebind the owner in its home and in every module that imported it.

    A module holds the owner only if it bound the very contract object; a site
    that spells the value instead is not rebound here and so keeps writing the
    old version -- which is exactly what the assertions then catch.
    """

    owner = contracts_mod.BASELINE_SCHEMA_VERSION
    holders = tuple(
        (name, module)
        for name, module in sorted(sys.modules.items())
        if isinstance(module, ModuleType)
        and (name == "codeclone" or name.startswith("codeclone."))
        and vars(module).get("BASELINE_SCHEMA_VERSION") is owner
    )
    for _name, module in holders:
        monkeypatch.setattr(module, "BASELINE_SCHEMA_VERSION", version)
    return tuple(name for name, _module in holders)


def _bundle() -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=(_FUNCTION_ID,),
        block_clone_keys=(_BLOCK_ID,),
    )


def _publish(target: Path) -> dict[str, object]:
    publish_mod.publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=_LIMIT,
    )
    document = orjson.loads(target.read_bytes())
    assert isinstance(document, dict)
    return document


def _entry(document: dict[str, object], section: str, key: str) -> object:
    part = document[section]
    assert isinstance(part, dict)
    return part[key]


def _legacy_bytes() -> bytes:
    return orjson.dumps(
        {
            "meta": {
                "generator": {"name": "codeclone", "version": "2.1.0a2"},
                "schema_version": "2.1",
                "fingerprint_version": "2",
                "python_tag": _PYTHON_TAG,
                "created_at": "2026-07-19T00:00:00Z",
                "payload_sha256": _compute_payload_sha256(
                    functions=(_FUNCTION_ID,),
                    blocks=(_BLOCK_ID,),
                    fingerprint_version="2",
                    python_tag=_PYTHON_TAG,
                ),
            },
            "clones": {"functions": [_FUNCTION_ID], "blocks": [_BLOCK_ID]},
        },
        option=orjson.OPT_SORT_KEYS,
    )


def test_moving_the_owner_reaches_its_home_and_its_importers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control for the probe every other case here relies on."""

    moved = _move_owner(monkeypatch, _ABOVE)

    assert "codeclone.contracts" in moved
    assert "codeclone.baseline.clone_baseline" in moved
    assert "codeclone.baseline.metrics_baseline" in moved
    assert vars(contracts_mod)["BASELINE_SCHEMA_VERSION"] == _ABOVE


@pytest.mark.parametrize(
    "version",
    (BASELINE_SCHEMA_VERSION, _ABOVE, _BELOW),
    ids=("owner-in-place", "owner-above", "owner-below"),
)
def test_publication_writes_the_owner_and_every_reader_accepts_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    _move_owner(monkeypatch, version)
    target = tmp_path / "baseline.json"

    written = _publish(target)
    assert _entry(written, "meta", "container_version") == version

    result = read_container_v3(target, limit_bytes=_LIMIT)
    assert isinstance(result, ContainerReadSuccess), result
    assert result.container.meta.container_version == version

    clone_baseline = Baseline(target)
    clone_baseline.load()
    clone_baseline.verify_compatibility(
        current_python_tag=_PYTHON_TAG,
        baseline_scope_id=_SCOPE_ID,
    )
    metrics_baseline = MetricsBaseline(target)
    metrics_baseline.load()
    metrics_baseline.verify_compatibility(
        runtime_python_tag=_PYTHON_TAG,
        baseline_scope_id=_SCOPE_ID,
    )
    # The report copies these two attributes verbatim (report/meta.py).
    assert clone_baseline.schema_version == version
    assert metrics_baseline.schema_version == version


@_MOVED_OWNER
def test_a_legacy_transition_targets_the_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    _move_owner(monkeypatch, version)
    target = tmp_path / "baseline.json"
    raw = _legacy_bytes()
    target.write_bytes(raw)

    evidence = transition_mod.read_legacy_transition(
        target,
        raw=raw,
        regenerated_lanes=_bundle().contract.enabled_lanes,
    )
    assert (evidence.from_schema, evidence.to_schema) == ("2.1", version)

    written = _publish(target)
    assert _entry(written, "meta", "container_version") == version
    assert _entry(written, "transition", "to_schema") == version
    assert _entry(written, "transition", "from_schema") == "2.1"


@_MOVED_OWNER
def test_a_container_written_under_the_old_owner_is_refused_by_the_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    target = tmp_path / "baseline.json"
    written = _publish(target)
    assert _entry(written, "meta", "container_version") == BASELINE_SCHEMA_VERSION

    _move_owner(monkeypatch, version)

    result = read_container_v3(target, limit_bytes=_LIMIT)
    assert isinstance(result, ContainerReadFailure), result
    assert (result.reason, result.detail) == (
        "unsupported_format",
        "unsupported baseline container version",
    )
    with pytest.raises(BaselineValidationError) as clone_refusal:
        Baseline(target).load()
    assert clone_refusal.value.status == BaselineStatus.MISMATCH_SCHEMA_VERSION
    with pytest.raises(BaselineValidationError) as metrics_refusal:
        MetricsBaseline(target).load()
    assert metrics_refusal.value.status == MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION


@pytest.mark.parametrize(
    ("owner", "field"),
    ((BaselineMeta, "container_version"), (EpochTransitionEvidence, "to_schema")),
    ids=("BaselineMeta.container_version", "EpochTransitionEvidence.to_schema"),
)
def test_a_typed_spelling_equals_the_owner(owner: type, field: str) -> None:
    annotation = typing.get_type_hints(owner)[field]

    assert typing.get_origin(annotation) is typing.Literal
    assert typing.get_args(annotation) == (BASELINE_SCHEMA_VERSION,)


def test_the_wire_spelling_equals_the_owner() -> None:
    annotation = EpochTransitionEvidenceInput.model_fields["to_schema"].annotation

    assert typing.get_origin(annotation) is typing.Literal
    assert typing.get_args(annotation) == (BASELINE_SCHEMA_VERSION,)


def _typed_field(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    """Name the class field whose annotation holds ``node``, if any."""

    current: ast.AST | None = node
    while current is not None:
        parent = parents.get(current)
        if (
            isinstance(parent, ast.AnnAssign)
            and current is parent.annotation
            and isinstance(parent.target, ast.Name)
        ):
            owner = parents.get(parent)
            if isinstance(owner, ast.ClassDef):
                return f"{owner.name}.{parent.target.id}"
            return None
        current = parent
    return None


def _production_sources() -> list[tuple[str, Path]]:
    """Every production module except the owner's home, by repo-relative path."""

    package_root = Path(contracts_mod.__file__).resolve().parents[1]
    return [
        (relative, path)
        for path in sorted(package_root.rglob("*.py"))
        if (relative := path.relative_to(package_root.parent).as_posix()) != _OWNER_HOME
    ]


def _spellings_of_the_owner_value() -> tuple[list[str], list[tuple[str, ...]]]:
    stray: list[tuple[str, int]] = []
    typed: list[tuple[str, ...]] = []
    for relative, path in _production_sources():
        tree = ast.parse(path.read_text("utf-8"), filename=relative)
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        spellings = (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == BASELINE_SCHEMA_VERSION
        )
        for node in spellings:
            field = _typed_field(node, parents)
            if field is None:
                stray.append((relative, node.lineno))
            else:
                typed.append((relative, *field.split(".")))
    return [f"{path}:{line}" for path, line in sorted(stray)], sorted(typed)


def test_production_spells_the_baseline_schema_version_only_in_pinned_types() -> None:
    stray, typed = _spellings_of_the_owner_value()

    assert stray == [], (
        "the baseline schema version is spelled outside its owner; read "
        "BASELINE_SCHEMA_VERSION from codeclone.contracts instead"
    )
    assert tuple(typed) == _TYPED_SPELLINGS
