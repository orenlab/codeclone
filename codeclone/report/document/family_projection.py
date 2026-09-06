# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of a semantic family's identity projection (identity v3).

Generation 2 digested ``findings.groups[family]`` — a FINDINGS projection —
and called the result the family digest, while the ratified contract
(RULING-2026-08-31, amendment 1: ``producer → canonical semantic family →
family_digest``) asks for the digest of the SEMANTIC FAMILY.  Measured
consequence: two documents stating a different ``reason``, ``reachability``
and ``witness`` for one dead-code abstention received one ``run_id`` — the
nine-field ``unresolved`` row reached no preimage — and ``coupled_classes``
below the design threshold, the ``cfg_cyclomatic_complexity`` of every
function, the ``coverage_join`` rows without a hotspot and three more
dead-code lanes were represented at no tier at all.

This module fixes the authority boundary, not the symptoms:

* **Membership comes from the producer contract.**  The registry declares,
  per family, the canonical document sections its producer writes or draws
  its verdicts from (``document_sections``).  The projection is the WHOLE
  content of those sections — the working precedent is the ``authority``
  family, clean because the report dumps its entire result object — never
  a hand-assembled field list.  A field a producer adds to its container
  enters the identity by construction; nobody has to remember a digest
  function.
* **Exclusion is a conscious, classified declaration.**  What leaves the
  analysis projection is named in the registry with one of the ratified
  classes — presentation, navigation provenance, configuration provenance,
  evaluation-policy output — or ``comparison``, which is never dropped but
  ROUTED to the comparison-tier projection of the same family, addressed by
  the entity's identity keys.  Nothing is dropped silently: the census
  below names every key the projection met and how it was classified, so a
  new field surfaces where it can be acknowledged or classified.

* **Ownership is total over the producers, not over one projection.**  The
  ratchet first quantified over ``findings.groups`` alone, and the user's
  analysis semantics live outside it: measured 2026-09-05 on a real
  document, five whole metric families (``api_surface``,
  ``coverage_adoption``, ``overloaded_modules``, ``security_surfaces`` and
  the ``semantic_authority`` container) differed on the wire while every
  tier stayed the same.  :func:`unowned_report_sections` therefore
  quantifies over every ``findings.groups`` container the document carries
  and every report section the metric-family registry names, and the
  integrity builder refuses to seal a document while any of them has no
  registered owner — a producer that grows a new user-visible section
  cannot ship it into the identity unowned.

The law both projections carry:

    Every user-visible analysis-semantic assertion must be represented in
    exactly one identity-bearing semantic-family projection at its natural
    tier.

    If CodeClone can show two semantically different analysis statements to
    the user, their analysis-semantic identity must differ — unless the
    difference is explicitly classified as non-semantic representation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from ...contracts.report_identity import (
    KEY_CLASS_COMPARISON,
    KEY_CLASS_SEMANTIC,
    REPORT_SEMANTIC_PRODUCERS,
    SCOPED_KEY_CLASSES,
    SCOPED_ROW_CLASSES,
    UNIVERSAL_KEY_CLASSES,
    ReportIdentityRegistryError,
    all_identity_keys,
    producer_spec,
    spec_document_sections,
    spec_family,
)
from ...metrics.registry import METRIC_FAMILIES
from ...utils.coerce import as_mapping as _as_mapping

#: Keys carried beside a routed comparison statement so it stays addressable
#: to its entity once the analysis content is gone: the group id every
#: findings family utters, plus every key a producer glues entity identity
#: into.  Derived from the registry, never spelled here.
_COMPARISON_ADDRESS_KEYS: Final[frozenset[str]] = (
    frozenset({"id"}) | all_identity_keys()
)

_SECTION_ROOTS: Final = ("findings", "metrics")

#: The census one walk accumulates: every key it classified out of the
#: analysis projection (``section/path => class``) and every semantic leaf it
#: kept (``section/path``), plus the scoped declarations it actually hit.
_CensusEntries = set[str]
_ObservedDeclarations = set[tuple[str, str]]


def family_document_sections(family: str) -> tuple[str, ...]:
    """The canonical document sections that compose one family's identity.

    An evaluation family, or any family the registry gives no sections,
    has no projection here: a typed refusal, never an empty digest that
    would read as a completed measurement of nothing.
    """

    sections = spec_document_sections(producer_spec(family))
    if not sections:
        raise ReportIdentityRegistryError(
            f"semantic family {family!r} declares no document sections; it "
            "has no identity projection"
        )
    return sections


def _resolve_section(
    section_path: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> object:
    """The raw container at one dotted document path, or ``None`` when absent.

    Absence and emptiness are different statements: a family whose section
    never reached the document projects as ``None``; one that ran and holds
    nothing projects as its own empty container.
    """

    head, _dot, rest = section_path.partition(".")
    if head not in _SECTION_ROOTS:
        raise ReportIdentityRegistryError(
            f"semantic family section {section_path!r} is outside the report "
            f"body (roots: {', '.join(_SECTION_ROOTS)})"
        )
    current: object = findings if head == "findings" else metrics
    for key in rest.split(".") if rest else ():
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _key_class(
    *,
    family: str,
    section: str,
    key_path: str,
    key: str,
    observed: _ObservedDeclarations,
) -> str:
    """Classify one key: a scoped declaration beats a universal one, and the
    default for everything undeclared is SEMANTIC."""

    declared = SCOPED_KEY_CLASSES.get(family, {}).get((section, key_path))
    if declared is not None:
        observed.add((section, key_path))
        return declared
    return UNIVERSAL_KEY_CLASSES.get(key, KEY_CLASS_SEMANTIC)


def _row_class(
    item: object,
    *,
    family: str,
    section: str,
    path: str,
    entries: _CensusEntries,
    observed: _ObservedDeclarations,
) -> str | None:
    """The class a row route gives one sequence element as a WHOLE, or
    ``None`` when no route applies and the row is walked key by key.  A
    routed row is one statement of another tier and is named as such."""

    row_route = SCOPED_ROW_CLASSES.get(family, {}).get((section, path))
    if row_route is None or not isinstance(item, Mapping):
        return None
    discriminator, row_classes = row_route
    row_class = row_classes.get(str(item.get(discriminator)))
    if row_class is None:
        return None
    observed.add((section, path))
    entries.add(
        f"{section}/{path[:-2]}[{discriminator}={item.get(discriminator)}] "
        f"=> {row_class}"
    )
    return row_class


def _split_mapping(
    mapping: Mapping[str, object],
    *,
    family: str,
    section: str,
    path: str,
    entries: _CensusEntries,
    observed: _ObservedDeclarations,
) -> tuple[dict[str, object], dict[str, object] | None]:
    analysis: dict[str, object] = {}
    comparison: dict[str, object] = {}
    for key in sorted(mapping):
        item = mapping[key]
        key_path = f"{path}.{key}" if path else key
        key_class = _key_class(
            family=family,
            section=section,
            key_path=key_path,
            key=key,
            observed=observed,
        )
        if key_class == KEY_CLASS_SEMANTIC:
            projected, routed = _split(
                item,
                family=family,
                section=section,
                path=key_path,
                entries=entries,
                observed=observed,
            )
            analysis[key] = projected
            if routed is not None:
                comparison[key] = routed
            continue
        entries.add(f"{section}/{key_path} => {key_class}")
        if key_class == KEY_CLASS_COMPARISON:
            comparison[key] = item
    if comparison:
        for key in sorted(_COMPARISON_ADDRESS_KEYS.intersection(mapping)):
            comparison.setdefault(key, mapping[key])
    return analysis, (comparison or None)


def _split_sequence(
    items: Sequence[object],
    *,
    family: str,
    section: str,
    path: str,
    entries: _CensusEntries,
    observed: _ObservedDeclarations,
) -> tuple[list[object], list[object] | None]:
    projected_items: list[object] = []
    routed_items: list[object] = []
    element_path = f"{path}[]"
    for item in items:
        row_class = _row_class(
            item,
            family=family,
            section=section,
            path=element_path,
            entries=entries,
            observed=observed,
        )
        if row_class is not None:
            if row_class == KEY_CLASS_COMPARISON:
                routed_items.append(dict(_as_mapping(item)))
            continue
        projected, routed = _split(
            item,
            family=family,
            section=section,
            path=element_path,
            entries=entries,
            observed=observed,
        )
        projected_items.append(projected)
        if routed is not None:
            routed_items.append(routed)
    return projected_items, (routed_items or None)


def _split(
    value: object,
    *,
    family: str,
    section: str,
    path: str,
    entries: _CensusEntries,
    observed: _ObservedDeclarations,
) -> tuple[object, object | None]:
    """One walk, two projections: the analysis content and the routed
    comparison content of ``value``, recursively."""

    if isinstance(value, Mapping) and value:
        return _split_mapping(
            _as_mapping(value),
            family=family,
            section=section,
            path=path,
            entries=entries,
            observed=observed,
        )
    if isinstance(value, Sequence) and not isinstance(value, str) and value:
        return _split_sequence(
            value,
            family=family,
            section=section,
            path=path,
            entries=entries,
            observed=observed,
        )
    entries.add(f"{section}/{path}" if path else section)
    return value, None


def _project(
    family: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], _CensusEntries, _ObservedDeclarations]:
    entries: _CensusEntries = set()
    observed: _ObservedDeclarations = set()
    analysis: dict[str, object] = {}
    comparison: dict[str, object] = {}
    for section_path in family_document_sections(family):
        container = _resolve_section(section_path, findings=findings, metrics=metrics)
        projected, routed = _split(
            container,
            family=family,
            section=section_path,
            path="",
            entries=entries,
            observed=observed,
        )
        analysis[section_path] = projected
        if routed is not None:
            comparison[section_path] = routed
    return analysis, comparison, entries, observed


def analysis_semantic_projection(
    family: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    """The analysis-tier identity projection of one family: every declared
    section, whole, minus the classified exclusions."""

    return _project(family, findings=findings, metrics=metrics)[0]


def comparison_semantic_projection(
    family: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object] | None:
    """The comparison-tier identity projection of one family: the routed
    comparison statements with their entity addresses, or ``None`` when the
    family utters no comparison statement."""

    return _project(family, findings=findings, metrics=metrics)[1] or None


def semantic_member_census(
    family: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> tuple[str, ...]:
    """Every key path the projection met, with the class of each key that
    did not stay semantic (``section/path => class``).  A new producer field
    appears here as a new semantic member: surfaced, never silently dropped.
    """

    return tuple(sorted(_project(family, findings=findings, metrics=metrics)[2]))


def unobserved_key_declarations(
    family: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> tuple[str, ...]:
    """Scoped declarations the projection of this document never reached.

    A declaration nothing utters is a dead witness: it looks like a
    conscious classification and classifies nothing.  The acceptance corpus
    pins this empty over the maximal document.
    """

    declared = set(SCOPED_KEY_CLASSES.get(family, {})) | set(
        SCOPED_ROW_CLASSES.get(family, {})
    )
    observed = _project(family, findings=findings, metrics=metrics)[3]
    return tuple(sorted(f"{section}/{path}" for section, path in declared - observed))


def evaluation_semantic_projection(
    family: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    """The identity projection of one EVALUATION family, digested whole at
    the evaluation tier.  An evaluation family has no comparison-tier
    projection: a statement the classification would route there is a typed
    refusal, never a silent drop from the only digest that carries it."""

    analysis, comparison, _entries, _observed = _project(
        family, findings=findings, metrics=metrics
    )
    if comparison:
        raise ReportIdentityRegistryError(
            f"evaluation family {family!r} classifies statements as comparison "
            f"({', '.join(sorted(comparison))}); an evaluation projection is "
            "digested whole at the evaluation tier — reclassify them in "
            "codeclone.contracts.report_identity"
        )
    return analysis


def document_section(
    section_path: str,
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> object:
    """The raw container one dotted document path names, or ``None``."""

    return _resolve_section(section_path, findings=findings, metrics=metrics)


def report_section_owners() -> dict[str, str]:
    """Every declared document section and the one family that owns it.

    Two producers declaring one section is a registry defect, refused here
    rather than resolved by order: one section, one owner.
    """

    owners: dict[str, str] = {}
    for spec in REPORT_SEMANTIC_PRODUCERS:
        family = spec_family(spec)
        for section_path in spec_document_sections(spec):
            if section_path in owners:
                raise ReportIdentityRegistryError(
                    f"document section {section_path!r} is declared by two "
                    f"producers ({owners[section_path]!r} and {family!r}); a "
                    "section has exactly one owner"
                )
            owners[section_path] = family
    return owners


def unowned_report_sections(
    *,
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> tuple[str, ...]:
    """Every user-visible section with no registered owner: the ``findings``
    groups and ``metrics`` families this document carries, plus every report
    section the metric-family registry names whether or not this document
    carries it.  Empty is the totality law; anything else is a producer
    whose statements would reach no tier."""

    named = {f"findings.groups.{name}" for name in _as_mapping(findings.get("groups"))}
    named.update(
        f"metrics.families.{name}" for name in _as_mapping(metrics.get("families"))
    )
    named.update(
        f"metrics.families.{family.report_section}"
        for family in METRIC_FAMILIES.values()
    )
    return tuple(sorted(named.difference(report_section_owners())))


__all__ = [
    "analysis_semantic_projection",
    "comparison_semantic_projection",
    "document_section",
    "evaluation_semantic_projection",
    "family_document_sections",
    "report_section_owners",
    "semantic_member_census",
    "unobserved_key_declarations",
    "unowned_report_sections",
]
