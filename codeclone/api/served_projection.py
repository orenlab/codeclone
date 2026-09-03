# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The served projection: an index for one sealed report, never the report.

The report document is the PROOF.  ``integrity`` digests the whole of
``source_facts`` into the run's identity and the served ``run_id`` *is* that
document's digest, so a document with a lane removed is an object whose
payload disagrees with its own name -- a lie about what was measured.  That is
why nothing here mutates a report: :func:`build_served_projection` builds a
*different object*, with its own contract, that indexes the proof it was built
from and carries the proof's ``analysis_facts`` digest as the witness of
which proof that is.

The distinction is structural, not a convention a later reader has to keep:

* the projection is not a ``dict``, so no serializer will emit it as a report
  (``json.dumps`` and ``orjson.dumps`` both refuse a plain ``Mapping``);
* the lanes it withholds are absent from its key set, and *asking* for one
  raises :class:`ServedProjectionError` instead of answering ``None`` -- a
  silent ``None`` would reach a gate through ``as_mapping(...)`` as "no lanes
  enabled" and be published as a verdict;
* the facts a served answer genuinely needs out of ``source_facts`` are lifted
  into :class:`ServingAnalysisContract`, a typed value, so a consumer names the
  fact it wants rather than digging through a proof it does not hold.

Placement is decided by the frozen edges, not by which package the word
"report" appears in: the consumer is the MCP surface (ring ``r4``), which may
not import the report layer (``r2``), and the type here is a facade DTO -- the
one thing an ``r3`` door exists to carry.  ``codeclone.api`` is that door.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from ..contracts import REPORT_RUN_IDENTITY_TIER
from ..utils.coerce import as_mapping, as_sequence

#: Sections of the sealed report the served projection does not carry.
#:
#: One entry, and it is the whole observation record: every lane the analysis
#: observed, at full fidelity, because the proof has to carry what the identity
#: digests.  No served operation reads it -- ``source_facts`` is not a
#: ``get_report_section`` section and no consumer addresses it off a record --
#: while it is the largest block in the document by a wide margin.
WITHHELD_PROOF_SECTIONS: Final[frozenset[str]] = frozenset({"source_facts"})


class ServedProjectionError(LookupError):
    """A withheld lane was asked of the index instead of of the proof."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ServingAnalysisContract:
    """The analysis facts a served answer needs, lifted out of the proof.

    Each field is copied verbatim from the document being sealed; none is
    re-derived, so the contract cannot drift from the proof it describes.
    ``analysis_facts_digest`` is the binding one: it is the tier digest whose
    preimage includes the withheld lanes, so a holder of the index can prove
    which proof it indexes without holding the proof.
    """

    report_schema_version: str
    #: Observation lanes this analysis ran, in the proof's own order.  The
    #: gate evaluator needs them and can no longer read them off the document.
    enabled_lanes: tuple[str, ...]
    #: ``source_facts.analysis_contract`` -- the declared design thresholds.
    design_thresholds: Mapping[str, object]
    #: ``integrity.digests.analysis_facts.value``.
    analysis_facts_digest: str
    #: ``integrity.digests.observation.value``.
    observation_digest: str


class ServedReportProjection(Mapping[str, object]):
    """The sections one sealed report serves, plus its analysis contract.

    A ``Mapping`` over the served sections, so every consumer that reads a
    section off a run keeps reading it unchanged.  It is deliberately NOT a
    ``dict``: a projection that could be handed to a serializer could be
    published as the report it is not.
    """

    __slots__ = ("_sections", "contract", "indexed_report_id")

    def __init__(
        self,
        sections: Mapping[str, object],
        *,
        contract: ServingAnalysisContract,
        indexed_report_id: str,
    ) -> None:
        withheld = WITHHELD_PROOF_SECTIONS & frozenset(sections)
        if withheld:
            raise ServedProjectionError(
                "served projection may not carry withheld proof sections: "
                f"{sorted(withheld)}"
            )
        self._sections: Mapping[str, object] = sections
        self.contract: ServingAnalysisContract = contract
        #: The digest of the proof this projection indexes.
        self.indexed_report_id: str = indexed_report_id

    def __getitem__(self, key: str) -> object:
        if key in WITHHELD_PROOF_SECTIONS:
            raise ServedProjectionError(
                f"'{key}' is carried by the sealed report, not by the served "
                "projection; read it from the generated report document"
            )
        return self._sections[key]

    def __contains__(self, key: object) -> bool:
        # A withheld lane is honestly absent -- ``in`` answers the question it
        # was asked -- while ``[]``/``get`` refuse, because reaching for one
        # through a read chain is a defect and not a miss.
        return key in self._sections

    def __iter__(self) -> Iterator[str]:
        return iter(self._sections)

    def __len__(self) -> int:
        return len(self._sections)

    def __repr__(self) -> str:
        return (
            f"ServedReportProjection(indexed_report_id={self.indexed_report_id!r}, "
            f"sections={sorted(self._sections)!r})"
        )


def build_served_projection(
    report_document: Mapping[str, object],
) -> ServedReportProjection:
    """Index one sealed report: keep what is served, lift what is needed.

    ``report_document`` is left untouched and its served sections are shared,
    not copied: the projection exists to stop holding the withheld lanes, and
    copying the rest would defeat that while changing nothing a caller reads.

    The indexed report's id is read out of the document, never passed in: an
    index whose caller names the proof could be handed the wrong name, and an
    index that points at the wrong proof is the defect this whole type exists
    to prevent.  Which digest tier names a run is stated once, by
    ``REPORT_RUN_IDENTITY_TIER``.
    """

    integrity = as_mapping(report_document.get("integrity"))
    digests = as_mapping(integrity.get("digests"))
    withheld = as_mapping(report_document.get("source_facts"))
    observation_contract = as_mapping(withheld.get("observation_contract"))
    contract = ServingAnalysisContract(
        report_schema_version=str(report_document.get("report_schema_version", "")),
        enabled_lanes=tuple(
            str(lane) for lane in as_sequence(observation_contract.get("enabled_lanes"))
        ),
        design_thresholds=as_mapping(withheld.get("analysis_contract")),
        analysis_facts_digest=str(
            as_mapping(digests.get("analysis_facts")).get("value", "")
        ),
        observation_digest=str(as_mapping(digests.get("observation")).get("value", "")),
    )
    return ServedReportProjection(
        {
            key: value
            for key, value in report_document.items()
            if key not in WITHHELD_PROOF_SECTIONS
        },
        contract=contract,
        indexed_report_id=str(
            as_mapping(digests.get(REPORT_RUN_IDENTITY_TIER)).get("value", "")
        ),
    )


__all__ = [
    "WITHHELD_PROOF_SECTIONS",
    "ServedProjectionError",
    "ServedReportProjection",
    "ServingAnalysisContract",
    "build_served_projection",
]
