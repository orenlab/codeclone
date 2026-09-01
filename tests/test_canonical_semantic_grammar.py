# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The canonical identity grammar has exactly one owner.

Ratified 2026-08-31: the grammar that turns the producer's own string
spellings into canonical identity types moved out of the legacy ingest
oracle into ``codeclone.canonical.semantic_grammar``, and BOTH readings —
the oracle and the producer-native publication path — consume it.

Two things are pinned here that a green parse never proves on its own:

* **No second law.** The structural ratchet below reads the package's
  syntax trees and refuses a second definition of the root-family grammar,
  the operation-head resolution or the symbol/endpoint/entity rules
  anywhere outside the owner. A transplant that left a copy behind would
  drift the moment either copy was touched.
* **Both consumers really reach it.** Each consumer's import edge is read
  off its own syntax tree, so "the owner exists" cannot be mistaken for
  "the owner is used". The causal half of that claim — that breaking a
  rule in the owner reds BOTH consumers — is the shared-authority mutation
  in the wave's battery; one red would only prove one reader.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from codeclone.canonical import semantic_grammar as owner
from codeclone.canonical.errors import (
    CanonicalModelError,
    LegacyIngestError,
    SemanticGrammarError,
)
from codeclone.canonical.identity import (
    OPERATION_KINDS,
    AnalysisFile,
    EffectLabelRoot,
    FileId,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationRoot,
    ProducerRoot,
    SymbolId,
    UnresolvedRoot,
)
from codeclone.canonical.semantic_grammar import (
    ROOT_FAMILIES,
    IdentityIndex,
    build_identity_index,
    parse_dead_code_entity,
    parse_effect_root,
    parse_endpoint,
    parse_lane_symbol,
    parse_operation_head,
    parse_root_set,
    parse_symbol,
    parse_symbol_set,
    surface_head,
)

_ROOT = Path(__file__).resolve().parents[1]
_OWNER = "codeclone/canonical/semantic_grammar.py"
#: The two readings that must share the owner. Named, so a third consumer
#: appearing without an import edge is a visible change rather than a quiet
#: one.
_CONSUMERS = (
    "codeclone/canonical/ingest.py",
    "codeclone/core/canonical_snapshot.py",
)
#: Every rule that moved. A module other than the owner defining any of
#: these names is a second law by construction.
_MOVED_RULES = frozenset(
    {
        "parse_symbol",
        "parse_symbol_set",
        "parse_endpoint",
        "parse_lane_symbol",
        "parse_dead_code_entity",
        "parse_operation_head",
        "parse_effect_root",
        "parse_root_set",
        # Not a transplanted rule but a rule under the same law: the
        # location grammar has two consumers from birth, so a second
        # definition is the same defect the transplant existed to remove.
        "parse_source_location",
        "parse_source_locations",
        "surface_head",
        "build_identity_index",
        # The pre-transplant private spellings: a resurrected copy would
        # most naturally come back under its old name.
        "_symbol",
        "_endpoint",
        "_lane_symbol",
        "_dead_code_entity",
        "_operation_head",
        "_source_location",
        "_source_locations",
        "_effect_root",
        "_root_set",
        "_symbol_set",
        "_surface_head",
        "_registry_index",
    }
)


@pytest.fixture
def index() -> IdentityIndex:
    return build_identity_index(
        [("pkg/a.py", "pkg.a"), ("pkg/__init__.py", "pkg")],
        analyzed_paths=frozenset({"pkg/a.py", "loose.py"}),
    )


# -- one owner, read off the syntax trees ----------------------------------


def _tree(relative: str) -> ast.AST:
    return ast.parse((_ROOT / relative).read_text("utf-8"), filename=relative)


def _defined_names(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_no_module_outside_the_owner_defines_a_grammar_rule() -> None:
    """The structural ratchet: one law, one definition site.

    There is NO exemption list. The ingest oracle keeps readers that pull
    a path, a name or a string list out of a document — that is document
    shape, and it stays where the document is — but they are named
    ``_document_*`` precisely so this check needs no carve-out: a rule
    coming back under a grammar name is an offender, full stop.
    """
    offenders = [
        f"{relative}::{name}"
        for relative in (
            path.relative_to(_ROOT).as_posix()
            for path in sorted((_ROOT / "codeclone").rglob("*.py"))
        )
        if relative != _OWNER
        for name in sorted(_defined_names(_tree(relative)) & _MOVED_RULES)
    ]
    assert offenders == [], (
        "a second definition of the canonical identity grammar survived the "
        f"transplant: {offenders}"
    )


def test_both_readings_import_the_one_owner() -> None:
    """ "The owner exists" is not "the owner is used"."""
    for consumer in _CONSUMERS:
        modules = {
            node.module
            for node in ast.walk(_tree(consumer))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert any(
            module.endswith("canonical.semantic_grammar") for module in modules
        ), consumer


def test_the_owner_reaches_only_its_two_frozen_edges() -> None:
    """``canonical`` may not import ``codeclone.models`` (ring r2), which is
    exactly why the owner takes plain ``(path, module)`` pairs instead of a
    registry handle. A future edge here would close a cycle."""
    imports = {
        node.module
        for node in ast.walk(_tree(_OWNER))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert {module for module in imports if module.startswith("codeclone")} == {
        "codeclone.canonical.errors",
        "codeclone.canonical.identity",
    }


def test_one_typed_result_for_both_readings() -> None:
    """Grammar refusals are one type. ``LegacyIngestError`` narrows it for
    the document shapes only the oracle can be handed, so every existing
    handler keeps catching what it caught."""
    assert issubclass(LegacyIngestError, SemanticGrammarError)
    assert issubclass(SemanticGrammarError, CanonicalModelError)
    assert owner.SemanticGrammarError is SemanticGrammarError


# -- the rules themselves ---------------------------------------------------


def test_the_index_refuses_a_registry_at_war_with_itself() -> None:
    assert build_identity_index([], analyzed_paths=frozenset()).module_to_path == {}
    with pytest.raises(SemanticGrammarError, match="claims two files"):
        build_identity_index([("a.py", "m"), ("b.py", "m")], analyzed_paths=frozenset())
    with pytest.raises(SemanticGrammarError, match="claims two modules"):
        build_identity_index([("a.py", "m"), ("a.py", "n")], analyzed_paths=frozenset())
    # A repeated identical pair is not a conflict.
    assert build_identity_index(
        [("a.py", "m"), ("a.py", "m")], analyzed_paths=frozenset()
    ).path_to_module == {"a.py": "m"}


def test_the_symbol_rule_reaches_both_heads_and_both_refusals(
    index: IdentityIndex,
) -> None:
    assert parse_symbol(index, "pkg.a:fn", "w") == SymbolId(FileId("pkg/a.py"), "fn")
    assert parse_symbol(index, "loose.py:fn", "w") == SymbolId(FileId("loose.py"), "fn")
    with pytest.raises(SemanticGrammarError, match="ModuleKey-headed"):
        parse_symbol(index, "bare", "w")
    with pytest.raises(SemanticGrammarError, match="ModuleKey-headed"):
        parse_symbol(index, "head:", "w")
    with pytest.raises(SemanticGrammarError, match="refusing to guess"):
        parse_symbol(index, "nowhere:fn", "w")


def test_the_endpoint_rule_reaches_both_domains_and_its_refusal(
    index: IdentityIndex,
) -> None:
    assert parse_endpoint(index, "pkg.a", "w") == ModuleId("pkg.a")
    assert parse_endpoint(index, "loose.py", "w") == FileId("loose.py")
    with pytest.raises(SemanticGrammarError, match="neither a registry module"):
        parse_endpoint(index, "nowhere", "w")


def test_the_lane_rule_refuses_both_ways(index: IdentityIndex) -> None:
    assert parse_lane_symbol(index, "pkg/a.py", "fn", "risk") == SymbolId(
        FileId("pkg/a.py"), "fn"
    )
    with pytest.raises(SemanticGrammarError, match="not an analyzed path"):
        parse_lane_symbol(index, "pkg/gone.py", "fn", "risk")
    with pytest.raises(SemanticGrammarError, match="glued identity"):
        parse_lane_symbol(index, "pkg/a.py", "mod:fn", "risk")


def test_the_dead_code_rule_reaches_all_three_variants(index: IdentityIndex) -> None:
    assert parse_dead_code_entity(index, "pkg.a:fn") == ModuleSymbol(
        ModuleId("pkg.a"), "fn"
    )
    assert parse_dead_code_entity(index, "loose.py:fn") == SymbolId(
        FileId("loose.py"), "fn"
    )
    assert parse_dead_code_entity(index, "nowhere:fn") == OpaqueEntity("nowhere", "fn")
    for bad in ("nocolon", ":fn", "head:"):
        with pytest.raises(SemanticGrammarError, match="head:local"):
            parse_dead_code_entity(index, bad)
    with pytest.raises(SemanticGrammarError, match="second ModuleKey colon"):
        parse_dead_code_entity(index, "pkg.a:mod:fn")


def test_the_surface_head_rule_reaches_both_answers(index: IdentityIndex) -> None:
    assert surface_head(index, "pkg/a.py", "w") == "pkg.a"
    assert surface_head(index, "loose.py", "w") == "loose.py"
    with pytest.raises(SemanticGrammarError, match="not an analyzed path"):
        surface_head(index, "pkg/gone.py", "w")


def test_the_operation_head_rule_reaches_all_three_variants(
    index: IdentityIndex,
) -> None:
    """The opaque variant is the producer's own measured third case (21 of
    1 080 corpus targets), not a fallback: the string is carried verbatim
    rather than split at a dot, which would manufacture structure nobody
    asserted."""
    assert parse_operation_head(index, "pkg.a") == KnownModule(ModuleId("pkg.a"))
    assert parse_operation_head(index, "loose.py") == AnalysisFile(FileId("loose.py"))
    assert parse_operation_head(index, "json.dumps") == OpaqueDottedHead("json.dumps")


def test_the_root_family_rule_is_total_over_its_closed_vocabulary(
    index: IdentityIndex,
) -> None:
    """Every family reachable, every refusal reachable, and the vocabulary
    itself pinned — a set of relative assertions would stay green for any
    contents of ``ROOT_FAMILIES``."""
    kind = OPERATION_KINDS[0]
    assert ROOT_FAMILIES == ("effect", "operation", "producer")
    assert parse_effect_root(index, "unresolved", "w") == UnresolvedRoot()
    assert parse_effect_root(index, f"operation:{kind}:pkg.a:fn", "w") == OperationRoot(
        kind, owner.OperationTarget(KnownModule(ModuleId("pkg.a")), "fn")
    )
    opaque = parse_effect_root(index, f"operation:{kind}:json.dumps", "w")
    assert isinstance(opaque, OperationRoot)
    assert opaque.target.head == OpaqueDottedHead("json.dumps")
    assert opaque.target.local_name == ""
    assert parse_effect_root(index, "producer:pkg.a:fn", "w") == ProducerRoot(
        SymbolId(FileId("pkg/a.py"), "fn")
    )
    assert parse_effect_root(index, "effect:field_write:x", "w") == EffectLabelRoot(
        "field_write", "x"
    )
    for bad, message in (
        ("nofamily", "has no family tag"),
        ("operation:onlykind", "has no target"),
        (f"operation:{kind}:pkg.a:", "no local name"),
        ("effect:kind", "has no label"),
        ("wat:x", "unknown root family"),
    ):
        with pytest.raises(SemanticGrammarError, match=message):
            parse_effect_root(index, bad, "w")


def test_the_set_helpers_apply_the_same_rule(index: IdentityIndex) -> None:
    assert parse_root_set(index, ["unresolved"], "w") == frozenset({UnresolvedRoot()})
    assert parse_symbol_set(index, ["pkg.a:fn"], "w") == frozenset(
        {SymbolId(FileId("pkg/a.py"), "fn")}
    )
    with pytest.raises(SemanticGrammarError, match="unknown root family"):
        parse_root_set(index, ["wat:x"], "w")
    with pytest.raises(SemanticGrammarError, match="refusing to guess"):
        parse_symbol_set(index, ["nowhere:fn"], "w")
