# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from codeclone.api import config_delivery as delivery
from codeclone.config import resolver as config_resolver
from codeclone.contracts import REPORT_RUN_IDENTITY_TIER
from tests._import_graph import (
    _iter_import_edges,
    _iter_local_imports,
    _module_name_from_path,
    _resolve_import,
)

_BOUNDARY_ALLOWLIST_PATH = Path(__file__).with_name(
    "architecture_boundary_allowlist.json"
)
_BOUNDARY_ALLOWLIST_POLICY = "phase39s-s0-observe-shrink-only"

_RING_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("codeclone.observability.store", "r2p"),
    ("codeclone.observability.analysis_phases", "r2p"),
    ("codeclone.observability.db_fingerprint", "r2p"),
    ("codeclone.observability.models", "r2p"),
    ("codeclone.observability.profile", "r2p"),
    ("codeclone.observability.query", "r2p"),
    ("codeclone.observability.render_html", "r2p"),
    ("codeclone.observability.render_json", "r2p"),
    ("codeclone.observability.sqlite_access", "r2p"),
    ("codeclone.observability.views", "r2p"),
    ("codeclone.observability", "r1"),
    ("codeclone.observations", "r2"),
    ("codeclone.report.renderers", "r4"),
    ("codeclone.report.html", "r4"),
    ("codeclone.report.messages", "r4"),
    ("codeclone.report", "r2"),
    ("codeclone.controller_insights", "r2p"),
    ("codeclone.workspace_intent", "r2p"),
    ("codeclone.analytics", "r2p"),
    ("codeclone.audit", "r2p"),
    ("codeclone.memory", "r2p"),
    ("codeclone.surfaces", "r4"),
    ("codeclone.ui_messages", "r4"),
    ("codeclone.main", "r4"),
    ("codeclone.__init__", "r4"),
    ("codeclone.contracts.compatibility", "r2"),
    ("codeclone.contracts", "r0"),
    ("codeclone.utils", "r1"),
    ("codeclone.api", "r3"),
    ("codeclone.analysis", "r2"),
    ("codeclone.baseline", "r2"),
    ("codeclone.blocks", "r2"),
    ("codeclone.budget", "r2"),
    ("codeclone.cache", "r2"),
    ("codeclone.canonical", "r2"),
    ("codeclone.config", "r2"),
    ("codeclone.core", "r2"),
    ("codeclone.domain", "r2"),
    ("codeclone.findings", "r2"),
    ("codeclone.meta_markers", "r2"),
    ("codeclone.metrics", "r2"),
    ("codeclone.models", "r2"),
    ("codeclone.paths", "r2"),
    ("codeclone.qualnames", "r2"),
    ("codeclone.scanner", "r2"),
    ("codeclone.semantics", "r2"),
    ("codeclone", "r4"),
    ("extensions", "r4"),
    ("plugins", "r4"),
)

_ALLOWED_IMPORT_RINGS: dict[str, frozenset[str]] = {
    "r0": frozenset({"r0"}),
    "r1": frozenset({"r0", "r1"}),
    "r2": frozenset({"r0", "r1", "r2"}),
    "r2p": frozenset({"r0", "r1", "r2p"}),
    "r3": frozenset({"r0", "r1", "r2", "r2p", "r3"}),
    "r4": frozenset({"r0", "r1", "r3", "r4"}),
}

_R2P_DTO_PREFIXES = (
    "codeclone.models",
    "codeclone.report.document",
)

_GENERATED_DIRECTORY_NAMES = frozenset(
    {
        ".gradle",
        ".idea",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
_PHASE39H_LEGACY_SYMBOLS = frozenset(
    {
        "_internal_roots",
        "_module_names_from_units",
        "_resolve_import_target",
        "module_name_from_path",
    }
)
_PHASE39H_OWNER_PREFIXES = (
    "codeclone.analysis",
    "codeclone.core",
    "codeclone.metrics",
    "codeclone.scanner",
)


def _iter_codeclone_modules(root: Path) -> list[tuple[str, Path]]:
    return [
        (_module_name_from_path(path.relative_to(root)), path)
        for path in sorted((root / "codeclone").rglob("*.py"))
    ]


def _iter_production_modules(root: Path) -> list[tuple[str, Path]]:
    modules: list[tuple[str, Path]] = []
    for package in ("codeclone", "extensions", "plugins"):
        package_root = root / package
        if not package_root.exists():
            continue
        modules.extend(
            (_module_name_from_path(path.relative_to(root)), path)
            for path in sorted(package_root.rglob("*.py"))
            if not _GENERATED_DIRECTORY_NAMES.intersection(path.relative_to(root).parts)
        )
    return modules


def _ring_for_module(module_name: str) -> str | None:
    for prefix, ring in _RING_BY_PREFIX:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return ring
    return None


def _is_r2p_dto_import(import_name: str) -> bool:
    return any(
        import_name == prefix or import_name.startswith(prefix + ".")
        for prefix in _R2P_DTO_PREFIXES
    )


def _is_ring_import_allowed(
    source_ring: str,
    target_ring: str,
    import_name: str,
) -> bool:
    if target_ring in _ALLOWED_IMPORT_RINGS[source_ring]:
        return True
    return (
        source_ring == "r2p" and target_ring == "r2" and _is_r2p_dto_import(import_name)
    )


def _add_violation(
    violations: dict[str, set[str]],
    family: str,
    violation: str,
) -> None:
    violations.setdefault(family, set()).add(violation)


def _production_import_violations(
    root: Path,
    violations: dict[str, set[str]],
) -> None:
    for module_name, path in _iter_production_modules(root):
        source_ring = _ring_for_module(module_name)
        if source_ring is None:
            _add_violation(
                violations,
                "ring_assignment:unassigned",
                module_name,
            )
            continue
        for import_name, _line in _iter_import_edges(
            module_name, path.read_text("utf-8")
        ):
            if not import_name.startswith("codeclone"):
                continue
            target_ring = _ring_for_module(import_name)
            if target_ring is None:
                _add_violation(
                    violations,
                    "ring_assignment:unassigned_target",
                    f"{module_name} -> {import_name}",
                )
            elif not _is_ring_import_allowed(source_ring, target_ring, import_name):
                _add_violation(
                    violations,
                    f"production_import:{source_ring}->{target_ring}",
                    f"{module_name} -> {import_name}",
                )


def _test_subject_ring(imports: list[tuple[str, int]]) -> str | None:
    rings = {
        ring
        for import_name, _line in imports
        if (ring := _ring_for_module(import_name)) is not None
    }
    for ring in ("r4", "r3", "r2p", "r2", "r1", "r0"):
        if ring in rings:
            return ring
    return None


def _test_import_violations(
    root: Path,
    violations: dict[str, set[str]],
) -> None:
    for path in sorted((root / "tests").glob("test_*.py")):
        module_name = _module_name_from_path(path.relative_to(root))
        imports = [
            edge
            for edge in _iter_import_edges(module_name, path.read_text("utf-8"))
            if edge[0].startswith("codeclone")
        ]
        source_ring = _test_subject_ring(imports)
        if source_ring is None:
            continue
        for import_name, _line in imports:
            target_ring = _ring_for_module(import_name)
            if target_ring is None:
                _add_violation(
                    violations,
                    "test_ring:unassigned_target",
                    f"{module_name} -> {import_name}",
                )
            elif not _is_ring_import_allowed(source_ring, target_ring, import_name):
                _add_violation(
                    violations,
                    f"test_import:{source_ring}->{target_ring}",
                    f"{module_name} -> {import_name}",
                )


def _expression_name(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            prefix = _expression_name(value)
            return f"{prefix}.{attr}" if prefix else attr
        case ast.Call(func=func):
            return _expression_name(func)
        case _:
            return ""


def _model_store_violations(
    root: Path,
    violations: dict[str, set[str]],
) -> None:
    for module_name, path in _iter_codeclone_modules(root):
        # codeclone.canonical is the ratified canonical semantic model layer
        # (F-3, 2026-08-13): a model store by design, on the same footing as
        # codeclone.models — its typed identity/fact definitions live there
        # and nowhere else.
        if module_name == "codeclone.models" or module_name.startswith(
            ("codeclone.models.", "codeclone.canonical")
        ):
            continue
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "pydantic" or alias.name.startswith("pydantic."):
                        _add_violation(
                            violations,
                            "model_store:pydantic_dependency",
                            f"{module_name} -> {alias.name}",
                        )
            elif isinstance(node, ast.ImportFrom):
                imported_module = node.module or ""
                if imported_module == "pydantic" or imported_module.startswith(
                    "pydantic."
                ):
                    _add_violation(
                        violations,
                        "model_store:pydantic_dependency",
                        f"{module_name} -> {imported_module}",
                    )
            elif isinstance(node, ast.ClassDef):
                if any(
                    _expression_name(base).split(".")[-1] == "BaseModel"
                    for base in node.bases
                ):
                    _add_violation(
                        violations,
                        "model_store:base_model_definition",
                        f"{module_name}::{node.name}",
                    )
                is_facade_dto = (
                    module_name == "codeclone.api"
                    or module_name.startswith("codeclone.api.")
                )
                if not is_facade_dto and any(
                    _expression_name(decorator).split(".")[-1] == "dataclass"
                    for decorator in node.decorator_list
                ):
                    _add_violation(
                        violations,
                        "model_store:dataclass_definition",
                        f"{module_name}::{node.name}",
                    )


def _phase39h_legacy_symbol_violations(
    root: Path,
    violations: dict[str, set[str]],
) -> None:
    for module_name, path in _iter_codeclone_modules(root):
        if not module_name.startswith(_PHASE39H_OWNER_PREFIXES):
            continue
        tree = ast.parse(path.read_text("utf-8"))
        symbols: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                symbols.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Name):
                symbols.add(node.id)
            elif isinstance(node, ast.Attribute):
                symbols.add(node.attr)
        for symbol in sorted(symbols & _PHASE39H_LEGACY_SYMBOLS):
            _add_violation(
                violations,
                "phase39h:legacy_identity_symbol",
                f"{module_name}::{symbol}",
            )


def _architecture_boundary_violations(root: Path) -> dict[str, tuple[str, ...]]:
    violations: dict[str, set[str]] = {}
    _production_import_violations(root, violations)
    _test_import_violations(root, violations)
    _model_store_violations(root, violations)
    _phase39h_legacy_symbol_violations(root, violations)
    return {
        family: tuple(sorted(items))
        for family, items in sorted(violations.items())
        if items
    }


def _assert_phase39_models_have_exact_owner(
    *,
    root: Path,
    model_names: set[str],
    behavior_path: Path,
    reexport_name: str,
    contract_declaration: str,
) -> None:
    models_tree = ast.parse((root / "codeclone/models.py").read_text("utf-8"))
    behavior_tree = ast.parse(behavior_path.read_text("utf-8"))
    model_definitions = {
        node.name for node in models_tree.body if isinstance(node, ast.ClassDef)
    }
    behavior_definitions = {
        node.name for node in behavior_tree.body if isinstance(node, ast.ClassDef)
    }

    assert model_names <= model_definitions
    assert not model_names & behavior_definitions
    assert reexport_name not in (root / "codeclone/semantics/__init__.py").read_text(
        "utf-8"
    )
    contracts_text = (root / "codeclone/contracts/__init__.py").read_text("utf-8")
    assert contract_declaration in contracts_text


def test_phase39d3_contract_ir_has_exact_owners_and_no_reexports() -> None:
    root = Path(__file__).resolve().parents[1]
    _assert_phase39_models_have_exact_owner(
        root=root,
        model_names={
            "ContractIRBuildResult",
            "ContractIRDocument",
            "ContractIRFailureState",
            "ContractIRSideEffect",
            "ContractIRTransformation",
            "FunctionContractIR",
        },
        behavior_path=root / "codeclone/semantics/ir.py",
        reexport_name="ContractIR",
        contract_declaration='CONTRACT_IR_VERSION: Final = "1"',
    )


def test_phase39d5_authority_has_one_behavior_owner_and_one_gate_reader() -> None:
    root = Path(__file__).resolve().parents[1]
    _assert_phase39_models_have_exact_owner(
        root=root,
        model_names={
            "AuthorityCandidate",
            "AuthorityGraph",
            "AuthorityGraphEdge",
            "AuthorityGraphNode",
            "AuthoritySinkResult",
            "SemanticAuthorityResult",
        },
        behavior_path=root / "codeclone/semantics/authority.py",
        reexport_name="SemanticAuthorityResult",
        contract_declaration='AUTHORITY_ANALYSIS_REVISION: Final = "1"',
    )

    forbidden_readers = (
        root / "codeclone/report/gates",
        root / "codeclone/metrics/health.py",
        root / "codeclone/surfaces/cli/workflow.py",
        root / "codeclone/surfaces/cli/execution.py",
        root / "codeclone/surfaces/cli/post_run.py",
        root / "codeclone/surfaces/cli/baseline_state.py",
        root / "codeclone/surfaces/cli/summary.py",
    )
    violations = [
        str(path.relative_to(root))
        for owner in forbidden_readers
        for path in ([owner] if owner.is_file() else sorted(owner.glob("*.py")))
        if "semantic_authority" in path.read_text("utf-8")
        or "AuthorityStatus" in path.read_text("utf-8")
    ]
    assert violations == ["codeclone/report/gates/evaluator.py"]


def _string_mapping(value: object, *, field: str) -> dict[str, object]:
    assert isinstance(value, dict), f"{field} must be an object"
    result: dict[str, object] = {}
    for key, item in value.items():
        assert isinstance(key, str), f"{field} keys must be strings"
        result[key] = item
    return result


def _load_boundary_allowlist(
    path: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    document = _string_mapping(json.loads(path.read_text("utf-8")), field="root")
    assert document.get("schema_version") == 1
    assert document.get("policy") == _BOUNDARY_ALLOWLIST_POLICY
    raw_violations = _string_mapping(document.get("violations"), field="violations")
    violations: dict[str, tuple[str, ...]] = {}
    for family, raw_items in raw_violations.items():
        assert isinstance(raw_items, list), f"{family} must be an array"
        validated_items: list[str] = []
        for item in raw_items:
            assert isinstance(item, str), f"{family} entries must be strings"
            validated_items.append(item)
        items = tuple(validated_items)
        assert items == tuple(sorted(set(items))), f"{family} must be sorted/unique"
        violations[family] = items

    raw_counts = _string_mapping(document.get("counts"), field="counts")
    counts: dict[str, int] = {}
    for family, raw_count in raw_counts.items():
        assert isinstance(raw_count, int), f"{family} count must be an integer"
        counts[family] = raw_count
    return violations, counts


def _ratchet_delta(
    current: dict[str, tuple[str, ...]],
    allowed: dict[str, tuple[str, ...]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    unexpected = {
        family: tuple(sorted(set(items) - set(allowed.get(family, ()))))
        for family, items in current.items()
        if set(items) - set(allowed.get(family, ()))
    }
    resolved = {
        family: tuple(sorted(set(items) - set(current.get(family, ()))))
        for family, items in allowed.items()
        if set(items) - set(current.get(family, ()))
    }
    return unexpected, resolved


def test_phase39s_ratchet_detects_growth_and_stale_entries() -> None:
    unexpected, resolved = _ratchet_delta(
        {"edge": ("kept", "new")},
        {"edge": ("kept", "resolved")},
    )
    assert unexpected == {"edge": ("new",)}
    assert resolved == {"edge": ("resolved",)}


def test_phase39s_api_ring_registration_is_specific_before_general() -> None:
    assert _ring_for_module("codeclone.api.memory") == "r3"
    assert _ring_for_module("codeclone.surfaces.mcp") == "r4"


def test_phase39s_architecture_boundary_ratchet() -> None:
    root = Path(__file__).resolve().parents[1]
    current = _architecture_boundary_violations(root)
    allowed, counts = _load_boundary_allowlist(_BOUNDARY_ALLOWLIST_PATH)

    expected_counts = {family: len(items) for family, items in sorted(allowed.items())}
    assert counts == expected_counts

    unexpected, resolved = _ratchet_delta(current, allowed)
    assert unexpected == {}, (
        "Phase 39S boundary ratchet found new violations; do not grow the "
        f"allowlist: {unexpected}"
    )
    assert resolved == {}, (
        f"Phase 39S boundary violations were resolved; shrink the allowlist: {resolved}"
    )


def _violates(import_name: str, forbidden_prefixes: tuple[str, ...]) -> bool:
    return any(
        import_name == prefix or import_name.startswith(prefix + ".")
        for prefix in forbidden_prefixes
    )


def _matches_module_prefix(module_name: str, module_prefix: str) -> bool:
    return module_name.startswith((module_prefix, module_prefix + "."))


def _is_allowed_import(import_name: str, allowed_prefixes: tuple[str, ...]) -> bool:
    return any(
        import_name == prefix or import_name.startswith(prefix + ".")
        for prefix in allowed_prefixes
    )


def test_architecture_layer_violations() -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []

    forbidden_by_module_prefix: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "codeclone.report.",
            (
                "codeclone.ui_messages",
                "codeclone.report.html",
                "codeclone.surfaces.cli",
                "codeclone._html_",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.extractor",
            (
                "codeclone.report",
                "codeclone.surfaces.cli",
                "codeclone.baseline",
            ),
        ),
        (
            "codeclone.grouping",
            (
                "codeclone.surfaces.cli",
                "codeclone.baseline",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.baseline",
            (
                "codeclone.surfaces.cli",
                "codeclone.ui_messages",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.cache",
            (
                "codeclone.surfaces.cli",
                "codeclone.ui_messages",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.core",
            (
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.analysis",
            (
                "codeclone.report",
                "codeclone.surfaces",
                "codeclone.config",
                "codeclone.observability",
            ),
        ),
        (
            "codeclone.metrics",
            (
                "codeclone.report.document",
                "codeclone.report.renderers",
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.findings",
            (
                "codeclone.report",
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.report.document",
            (
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.report.renderers",
            (
                "codeclone.core",
                "codeclone.analysis",
                "codeclone.metrics",
                "codeclone.findings",
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.domain.",
            (
                "codeclone.surfaces.cli",
                "codeclone.pipeline",
                "codeclone.report",
                "codeclone.report.html",
                "codeclone.ui_messages",
                "codeclone.baseline",
                "codeclone.cache",
            ),
        ),
    )

    for module_name, path in _iter_codeclone_modules(root):
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))

        for module_prefix, forbidden_prefixes in forbidden_by_module_prefix:
            if _matches_module_prefix(module_name, module_prefix):
                if module_prefix == "codeclone.report." and module_name.startswith(
                    "codeclone.report.html"
                ):
                    continue
                violations.extend(
                    [
                        (
                            f"{module_name} -> {import_name} "
                            f"(forbidden: {forbidden_prefixes})"
                        )
                        for import_name in imports
                        if _violates(import_name, forbidden_prefixes)
                    ]
                )

        if module_name == "codeclone.models":
            allowed_prefixes = ("codeclone.contracts",)
            unexpected_imports = [
                import_name
                for import_name in imports
                if not _is_allowed_import(import_name, allowed_prefixes)
            ]
            violations.extend(
                [
                    f"codeclone.models imports unexpected local module: {import_name}"
                    for import_name in unexpected_imports
                ]
            )

        if (
            module_name.startswith("codeclone.domain.")
            and module_name != "codeclone.domain.__init__"
        ):
            violations.extend(
                [
                    "codeclone.domain submodule imports unexpected local module: "
                    f"{module_name} -> {import_name}"
                    for import_name in imports
                ]
            )

    assert violations == []


def test_non_mcp_surfaces_do_not_import_mcp_blast_radius_module() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = "codeclone.surfaces.mcp._blast_radius"
    violations: list[str] = []
    for module_name, path in _iter_codeclone_modules(root):
        if module_name.startswith("codeclone.surfaces.mcp"):
            continue
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))
        violations.extend(
            f"{module_name} -> {import_name}"
            for import_name in imports
            if import_name == forbidden or import_name.startswith(forbidden + ".")
        )
    assert violations == []


_FORBIDDEN_SURFACE_PREFIXES = (
    "codeclone.surfaces.",
    "codeclone.ui_messages",
    "codeclone.report.html",
)


def _assert_no_forbidden_surface_imports(package_prefix: str) -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for module_name, path in _iter_codeclone_modules(root):
        if not module_name.startswith(package_prefix):
            continue
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))
        violations.extend(
            f"{module_name} -> {import_name}"
            for import_name in imports
            if any(
                import_name == prefix.rstrip(".") or import_name.startswith(prefix)
                for prefix in _FORBIDDEN_SURFACE_PREFIXES
            )
        )
    assert violations == []


def test_analytics_package_does_not_import_forbidden_surfaces() -> None:
    _assert_no_forbidden_surface_imports("codeclone.analytics")


def test_memory_package_does_not_import_forbidden_surfaces() -> None:
    _assert_no_forbidden_surface_imports("codeclone.memory")


def test_phase39i_legacy_content_hit_and_git_owners_are_absent() -> None:
    root = Path(__file__).resolve().parents[1]
    worker_source = (root / "codeclone/core/worker.py").read_text("utf-8")
    parallel_source = (root / "codeclone/core/parallelism.py").read_text("utf-8")
    discovery_source = (root / "codeclone/core/discovery.py").read_text("utf-8")
    hygiene_source = (root / "codeclone/surfaces/mcp/_workspace_hygiene.py").read_text(
        "utf-8"
    )

    assert "read_text(" not in worker_source
    assert "inspect.signature" not in worker_source
    assert "except TypeError" not in parallel_source
    assert '["stat"] == stat' not in discovery_source
    assert "_dirty_paths_from_porcelain" not in hygiene_source
    assert "subprocess.run" not in hygiene_source


def test_phase39l_observations_package_is_an_r2_fact_owner() -> None:
    assert _ring_for_module("codeclone.observations") == "r2"
    assert _ring_for_module("codeclone.observations.lanes") == "r2"


#: The two modules allowed to spell the run-identity tier as a literal, and the
#: reason each one is not a reader.
#:
#: ``report/document/integrity.py`` is the value's producer: ``pyproject.toml``
#: registers ``codeclone.report.document.integrity:_build_integrity_payload`` as
#: the canonical owner of ``report.run_identity/v1``, and the wire keys it emits
#: are the document schema itself, not a lookup into someone else's document.
#: ``models.py`` declares ``ReportDigestKind``, the closed vocabulary of tier
#: names; a ``Literal`` member is a type, and a type cannot be imported as a
#: value by a module that has to navigate to one.
_RUN_IDENTITY_TIER_LITERAL_OWNERS = (
    "codeclone/models.py",
    "codeclone/report/document/integrity.py",
)


def _module_address_tokens(path: Path) -> frozenset[str]:
    """Every string constant in a module, plus its dotted-path segments.

    Segments matter because a reader does not have to spell ``"digests"`` on
    its own: ``utils.mapping_paths.section`` is addressed by one dotted string,
    so ``f"integrity.digests.{tier}"`` hides both the navigation and, when the
    tier is inlined, the duplicated answer inside a single constant. Splitting
    on ``.`` is what makes those two spellings the same fact to this scan --
    without it the guard silently skipped the very module that owned the
    duplicate.
    """

    tree = ast.parse(path.read_text("utf-8"))
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.add(node.value)
            tokens.update(node.value.split("."))
    return frozenset(tokens)


def test_the_run_identity_tier_is_named_by_the_contract_in_every_reader() -> None:
    """A module that navigates report digests takes the tier from r0.

    The tier that names a run was owned by ``surfaces.cli.run_identity`` (r4),
    which ``controller_insights`` (r2p) cannot import: the two rings share only
    r0 and r1, so the controller plane could not reach the ratified answer and
    spelled its own address instead. Moving the name into ``contracts`` makes
    the answer reachable; this keeps it single.

    The rule is stated over readers, not over the word: ``"evaluation"`` also
    names an unrelated workflow phase and the document section the tier seals,
    and neither of those modules navigates ``digests``. A module is a reader
    here exactly when it spells ``digests``, and a reader may not also spell
    the tier -- it has to import ``REPORT_RUN_IDENTITY_TIER``.

    The discovered reader set is asserted non-empty and named, because a
    detector that matches nothing would let this pass over an empty scan.
    """

    root = Path(__file__).resolve().parents[1]
    readers: list[str] = []
    offenders: list[str] = []
    for module_name, path in _iter_codeclone_modules(root):
        assert module_name  # every production module is ring-registered
        relative = str(path.relative_to(root))
        tokens = _module_address_tokens(path)
        if "digests" not in tokens:
            continue
        readers.append(relative)
        restates_the_tier = REPORT_RUN_IDENTITY_TIER in tokens
        if restates_the_tier and relative not in _RUN_IDENTITY_TIER_LITERAL_OWNERS:
            offenders.append(relative)

    assert offenders == [], (
        "these modules read report digests and still spell the run identity "
        f"tier instead of importing REPORT_RUN_IDENTITY_TIER: {offenders}"
    )
    assert "codeclone/utils/run_identity.py" in readers
    assert "codeclone/surfaces/mcp/_session_helpers.py" in readers


# --------------------------------------------------------------------------------------
# The configuration-delivery ratchet
#
# ``api/config_delivery.py`` declares which surfaces deliver repository
# configuration into an analysis run and how. A declaration nothing checks is a
# claim about coverage, not coverage: the door shipped with a surface that was
# declared, named in the door's own docstring, and wired past it on both edges,
# and nothing went red because no withholding existed for it yet. These tests
# make non-participation impossible to reach silently, in both directions.
#
# The predicate is computed, never listed. A module is a *delivery site* exactly
# when it reaches one of the resolver's entry points that write repository
# configuration onto an ``args`` namespace. That is what separates delivery from
# the many modules that merely read ``pyproject.toml`` for their own purposes --
# analytics, memory, the pyproject writer, controller insights, the audit
# runtime and setup discovery all load configuration and none of them deliver
# it into a run.
# --------------------------------------------------------------------------------------

_CONFIG_DELIVERY_DOOR_MODULE = "codeclone.api.config_delivery"
_CANONICAL_CONFIG_PACKAGE = "codeclone.config"

#: What a surface routed through the door must spell to actually use it: read
#: through the door, project through its own declaration, apply through the
#: door. Dropping the projection is the failure that leaves a declared
#: withholding inert while every other edge still looks wired.
_DOOR_EDGES = frozenset(
    {
        "load_repository_config",
        "delivered_config_values",
        "apply_repository_config",
    }
)


def _resolver_delivery_entry_points() -> frozenset[str]:
    """Resolver entry points that write repository configuration onto a namespace.

    Derived from the producer's published signatures, never restated. Listing
    the names here would move the magic constant into the guard and leave it
    green after the resolver grew a fourth way in; taking them from
    ``__all__`` plus the ``args`` parameter re-derives the rule every run.
    """

    return frozenset(
        name
        for name in config_resolver.__all__
        if "args" in inspect.signature(getattr(config_resolver, name)).parameters
    )


def _imported_symbols(path: Path) -> frozenset[str]:
    """Every symbol a module reaches from outside itself, however it spelled it.

    Text search is blind here by construction: ``workflow`` binds the resolver
    through an attribute assignment, ``_session_state_mixin`` imports the door
    through a sibling's re-export, and ``session_stats`` imports inside function
    bodies. Import aliases, attribute access and re-exported names all reach the
    same symbol, so all three shapes are collected.

    Bare ``Name`` nodes are deliberately **not** collected. Reaching a symbol
    defined elsewhere requires an import or an attribute, so a bare name is a
    local binding -- and ``memory.application`` binds a local ``resolve_config``
    for an unrelated function, which a name-only scan reports as a delivery site
    that does not exist.
    """

    tree = ast.parse(path.read_text("utf-8"))
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                symbols.add(alias.name.rsplit(".", 1)[-1])
                if alias.asname:
                    symbols.add(alias.asname)
        elif isinstance(node, ast.Attribute):
            symbols.add(node.attr)
    return frozenset(symbols)


def _modules_reaching_the_resolver(root: Path) -> frozenset[str]:
    """Every production module that delivers configuration onto a namespace.

    The canonical ``config`` package is excluded whole, not just the resolver
    module: it is the producer. Its own ``__init__`` re-exports ``resolve_config``
    as package API, which is publication, not delivery, and a surface cannot hide
    inside it -- r2 cannot import a surface at all.
    """

    entry_points = _resolver_delivery_entry_points()
    return frozenset(
        module_name
        for module_name, path in _iter_codeclone_modules(root)
        if not module_name.startswith(f"{_CANONICAL_CONFIG_PACKAGE}.")
        and _imported_symbols(path) & entry_points
    )


def _module_path(root: Path, module_name: str) -> Path:
    return root / Path(*module_name.split(".")).with_suffix(".py")


def test_delivery_sites_are_exactly_the_door_and_its_declared_exemptions() -> None:
    """The ratchet: a delivery surface may not reach the resolver past the door.

    Red in both directions on purpose. A module that reaches the resolver
    without being declared is a surface delivering configuration nobody
    governs; a declared resolver-direct module that stops reaching it is a
    declaration that has outlived its subject. Both are lies about coverage,
    so both fail the same equality.
    """

    root = Path(__file__).resolve().parents[1]
    entry_points = _resolver_delivery_entry_points()

    # A detector that matches nothing would pass this over an empty scan.
    assert "apply_pyproject_config_overrides" in entry_points
    assert "collect_explicit_cli_dests" not in entry_points

    reaching = _modules_reaching_the_resolver(root)
    declared = delivery.delivery_modules(delivery.DeliveryRoute.RESOLVER_DIRECT)
    expected = declared | {_CONFIG_DELIVERY_DOOR_MODULE}

    assert reaching == expected, (
        "modules delivering repository configuration must be the door plus its "
        f"declared resolver-direct surfaces: expected {sorted(expected)}, "
        f"reached {sorted(reaching)}"
    )


def test_every_door_routed_surface_spells_all_three_door_edges() -> None:
    """A surface declared to use the door must use it to read, project and apply.

    Reaching the door for one edge and the canonical owner for another is how
    a declaration stays green while its withholdings never apply: the door's
    projection is the only place a surface's declared withholding is enforced,
    so a site that skips it delivers everything and still looks wired.
    """

    root = Path(__file__).resolve().parents[1]
    entry_points = _resolver_delivery_entry_points()
    routed = delivery.delivery_modules(delivery.DeliveryRoute.THROUGH_THE_DOOR)

    assert routed, "no surface is declared to use the door"

    missing: dict[str, list[str]] = {}
    bypassing: dict[str, list[str]] = {}
    for module_name in sorted(routed):
        symbols = _imported_symbols(_module_path(root, module_name))
        if absent := sorted(_DOOR_EDGES - symbols):
            missing[module_name] = absent
        if past := sorted(symbols & (entry_points | {"load_pyproject_config"})):
            bypassing[module_name] = past

    assert missing == {}, f"door-routed surfaces missing a door edge: {missing}"
    assert bypassing == {}, (
        f"door-routed surfaces reaching a canonical owner directly: {bypassing}"
    )


def _explicit_dests_arguments(path: Path, entry_points: frozenset[str]) -> list[str]:
    """How each resolver call in ``path`` spells its ``explicit_cli_dests``."""

    tree = ast.parse(path.read_text("utf-8"))
    return [
        _expression_name(keyword.value) or ast.dump(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _expression_name(node.func).split(".")[-1] in entry_points
        for keyword in node.keywords
        if keyword.arg == "explicit_cli_dests"
    ]


def test_a_resolver_direct_surface_passes_its_own_explicit_cli_dests() -> None:
    """The exemption is a rule, so it has to be kept, not merely declared.

    ``explicit_cli_dests`` is the entire reason the CLI does not use the door.
    A resolver-direct surface that hands the resolver an empty set has taken
    the exemption without the obligation, and repository configuration then
    overwrites the flags the user typed -- the exact outcome the exemption
    exists to prevent.
    """

    root = Path(__file__).resolve().parents[1]
    entry_points = _resolver_delivery_entry_points()
    empty = {"set", "frozenset"}

    inert: dict[str, list[str]] = {}
    for module_name in sorted(
        delivery.delivery_modules(delivery.DeliveryRoute.RESOLVER_DIRECT)
    ):
        arguments = _explicit_dests_arguments(
            _module_path(root, module_name), entry_points
        )
        assert arguments, f"{module_name} declares resolver_direct and calls nothing"
        if supplied := [value for value in arguments if value in empty]:
            inert[module_name] = supplied

    assert inert == {}, (
        "resolver-direct surfaces passing an empty explicit_cli_dests, which "
        f"lets repository configuration beat a command-line flag: {inert}"
    )


def _called_symbols(path: Path) -> frozenset[str]:
    """Every symbol a module actually calls.

    Importing a name is not using it. ``_session_shared`` re-exports the whole
    door for its siblings, so an import-level scan counts that re-export as a
    consumer and a wrapper whose only real caller went back to the canonical
    owner still looks wired -- the sibling doing the work while the mechanism
    under test does nothing.
    """

    tree = ast.parse(path.read_text("utf-8"))
    return frozenset(
        _expression_name(node.func).split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    )


def _door_wrappers(module_name: str, path: Path) -> frozenset[str]:
    """Door functions that call a canonical ``config`` owner on the way through.

    These are the door's two-sided halves. A half whose production side is not
    wired keeps working in tests against the door while production takes the
    canonical owner directly, and the two paths then drift with nothing red.
    """

    tree = ast.parse(path.read_text("utf-8"))
    canonical: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and _resolve_import(
            module_name, node
        ).startswith(_CANONICAL_CONFIG_PACKAGE):
            canonical.update(alias.asname or alias.name for alias in node.names)

    wrappers: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and _expression_name(inner.func).split(".")[-1] in canonical
            ):
                wrappers.add(node.name)
    return frozenset(wrappers)


def test_no_door_wrapper_lives_only_on_its_tests() -> None:
    """Every half of the door has a production caller, or it is a second path.

    ``load_repository_config`` was a pure pass-through to the canonical loader
    with three test callers and no production caller, while production loaded
    through the canonical owner directly. Behaviour identical today, so nothing
    could see it -- and behaviour added to either side afterwards would have
    reached only one of them.
    """

    root = Path(__file__).resolve().parents[1]
    door = _module_path(root, _CONFIG_DELIVERY_DOOR_MODULE)
    wrappers = _door_wrappers(_CONFIG_DELIVERY_DOOR_MODULE, door)

    assert "apply_repository_config" in wrappers

    orphans = sorted(
        wrapper
        for wrapper in wrappers
        if not any(
            module_name != _CONFIG_DELIVERY_DOOR_MODULE
            and wrapper in _called_symbols(path)
            for module_name, path in _iter_codeclone_modules(root)
        )
    )

    assert orphans == [], (
        "these door halves wrap a canonical config owner and have no production "
        f"caller, so only tests take the door's path: {orphans}"
    )
