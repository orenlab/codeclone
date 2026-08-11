# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The staleness contract: who witnesses a record's freshness, and how it fails.

Every memory record asserts something, and each kind of assertion is falsified
by a different file. A ``document_link`` says *this document contains a
reference*; editing the referenced file leaves that true, so the document owns
its freshness. A ``risk_note`` about a code file is falsified by exactly that
edit, so the code file owns it. A single global subject-kind priority cannot
serve both -- it silently hands one kind the other kind's witness, and the
record then compares two unrelated files that can never agree.

So ownership is declared per record kind, here, as data with one owner, and
both sides of the store read it: the ingest writes the owner's fingerprint and
the refresh compares against the same owner. When the two disagree a record
goes stale the moment it is written, with nothing edited at all.

Two questions are kept apart deliberately:

* **Did the owner change?** Answered by the owner's content fingerprint.
* **Does the reference still resolve?** Answered by existence alone.

They are different facts and must never share one fingerprint. A vanished
target is not drift in the document; it is a change in the resolution
relation, and it carries its own reason so a reader can tell which happened.
Where a record genuinely depends on several subjects, the honest answer is a
vector of witnesses -- not a contest over which single hash is "the right one".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from ..utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from .enums import MemoryRecordType, SubjectKind
from .models import MemorySubject
from .paths import normalize_repo_path
from .project import module_repo_path

WitnessKind = Literal["code_content", "document_content", "test_content"]

# Every way a record can lose freshness. Declared here so the set is knowable
# from one place: the reasons used to be bare literals at their write sites, so
# nobody could enumerate them without grepping, and each new one arrived
# invisibly. Membership is enforced by test, not by convention.
SUBJECT_FINGERPRINT_DRIFT = "subject_fingerprint_drift"
REFERENCE_UNRESOLVED = "reference_unresolved"
SCOPE_FILES_CHANGED = "scope_files_changed"
MISSING_FROM_REFRESH = "missing_from_refresh"
REFRESH_CONTENT_CONTRADICTION = "refresh_content_contradiction"
EVIDENCE_DIGEST_MISMATCH = "evidence_digest_mismatch"
REPORT_DIGEST_SHIFT = "report_digest_shift"

STALE_REASONS: frozenset[str] = frozenset(
    {
        SUBJECT_FINGERPRINT_DRIFT,
        REFERENCE_UNRESOLVED,
        SCOPE_FILES_CHANGED,
        MISSING_FROM_REFRESH,
        REFRESH_CONTENT_CONTRADICTION,
        EVIDENCE_DIGEST_MISMATCH,
        REPORT_DIGEST_SHIFT,
    }
)

# Subject kinds that name a file in the repository, and are therefore the only
# kinds that can carry a content fingerprint or be checked for resolution.
FILE_BACKED_SUBJECT_KINDS: tuple[SubjectKind, ...] = ("path", "test", "doc", "module")


# One row per record kind: (owner subject kinds, witness kind, reference
# subject kinds). Read it through the accessors below rather than by index.
#
# The owner kinds are consulted in order and the first kind present on the
# record wins. That order is a fallback chain within one kind's own semantics,
# not a priority across kinds. For a record that is simply *about one file*,
# ``path``/``doc``/``test`` are alternative spellings of naming that file and
# ``module`` is the projection fallback, so the chain lists the spellings it
# accepts. Several kinds sharing a chain is not the old global priority
# returning: each kind still declares its own, and ``document_link``
# deliberately declares a different one.
#
# The reference kinds name subjects the record points *at* without claiming
# anything about their content. They are checked for resolution only, never
# fingerprinted.
StalenessOwnershipRow = tuple[
    tuple[SubjectKind, ...],
    WitnessKind,
    tuple[SubjectKind, ...],
]


# The record is about one file, named in whichever spelling the writer used.
_ABOUT_ONE_FILE: tuple[SubjectKind, ...] = ("path", "doc", "test", "module")

# One row per record kind. Adding a kind without adding it here leaves its
# freshness unwitnessed, which is why completeness is pinned by test.
RECORD_STALENESS_OWNERSHIP: Mapping[MemoryRecordType, StalenessOwnershipRow] = {
    "module_role": (_ABOUT_ONE_FILE, "code_content", ()),
    "contract_note": (_ABOUT_ONE_FILE, "code_content", ()),
    "test_anchor": (("test",), "test_content", ()),
    # The claim is that this document contains a reference. Editing the
    # referenced file leaves that claim true, so the document owns freshness
    # and the target is a reference, checked for resolution only.
    "document_link": (("doc",), "document_content", ("path",)),
    "risk_note": (_ABOUT_ONE_FILE, "code_content", ()),
    "public_surface": (_ABOUT_ONE_FILE, "code_content", ()),
    # Asserts a document contradicts another source, so the document leads.
    "contradiction_note": (("doc", "path", "test", "module"), "document_content", ()),
    "architecture_decision": (_ABOUT_ONE_FILE, "code_content", ()),
    "change_rationale": (_ABOUT_ONE_FILE, "code_content", ()),
    "protocol_rule": (_ABOUT_ONE_FILE, "code_content", ()),
    "stale_marker": (_ABOUT_ONE_FILE, "code_content", ()),
    "human_note": (_ABOUT_ONE_FILE, "code_content", ()),
}


def staleness_ownership_for(
    record_type: MemoryRecordType,
) -> StalenessOwnershipRow | None:
    """Ownership row for *record_type*, or None when the kind is not declared.

    An undeclared kind fails closed: with no declared owner we cannot say what
    would falsify the record, so no fingerprint verdict is issued about it.
    Guessing an owner is how a record acquires someone else's witness.
    """

    return RECORD_STALENESS_OWNERSHIP.get(record_type)


def owner_subject_kinds_for(
    record_type: MemoryRecordType,
) -> tuple[SubjectKind, ...]:
    """Subject kinds that may own freshness for this record kind, in order."""

    row = staleness_ownership_for(record_type)
    return () if row is None else row[0]


def witness_kind_for(record_type: MemoryRecordType) -> WitnessKind | None:
    """What the owner's content is, as a statement of the contract."""

    row = staleness_ownership_for(record_type)
    return None if row is None else row[1]


def reference_subject_kinds_for(
    record_type: MemoryRecordType,
) -> tuple[SubjectKind, ...]:
    """Subject kinds this record merely points at."""

    row = staleness_ownership_for(record_type)
    return () if row is None else row[2]


def owner_subject(
    record_type: MemoryRecordType,
    subjects: Sequence[MemorySubject],
) -> MemorySubject | None:
    """The subject whose content witnesses freshness for this record."""

    for kind in owner_subject_kinds_for(record_type):
        for subject in subjects:
            if subject.subject_kind == kind:
                return subject
    return None


def reference_subjects(
    record_type: MemoryRecordType,
    subjects: Sequence[MemorySubject],
) -> tuple[MemorySubject, ...]:
    """Subjects the record points at, whose resolution is a separate fact."""

    kinds = reference_subject_kinds_for(record_type)
    if not kinds:
        return ()
    return tuple(subject for subject in subjects if subject.subject_kind in kinds)


def subject_reference_resolves(root_path: Path, subject: MemorySubject) -> bool:
    """Does *subject* still name a file in the tree? Existence only.

    Deliberately does not read or hash the file: "the reference still points
    somewhere" and "the target's content is unchanged" are different questions,
    and answering the first with the second is what made a vanished target look
    like drift.
    """

    if subject.subject_kind == "module":
        # Routed through the memory-side owner of module projection rather than
        # reaching into the path package directly: that projection already
        # knows about package inits and phantom module files.
        return module_repo_path(subject.subject_key, root_path) is not None
    try:
        normalized = normalize_repo_path(subject.subject_key)
    except ValueError:
        return False
    try:
        resolve_under_repo_root(
            root_path,
            normalized,
            policy=RepoPathPolicy(must_exist=True, must_be_file=True),
        )
    except (PathOutsideRepoError, RepoPathError):
        return False
    return True


__all__ = [
    "EVIDENCE_DIGEST_MISMATCH",
    "FILE_BACKED_SUBJECT_KINDS",
    "MISSING_FROM_REFRESH",
    "RECORD_STALENESS_OWNERSHIP",
    "REFERENCE_UNRESOLVED",
    "REFRESH_CONTENT_CONTRADICTION",
    "REPORT_DIGEST_SHIFT",
    "SCOPE_FILES_CHANGED",
    "STALE_REASONS",
    "SUBJECT_FINGERPRINT_DRIFT",
    "StalenessOwnershipRow",
    "WitnessKind",
    "owner_subject",
    "owner_subject_kinds_for",
    "reference_subject_kinds_for",
    "reference_subjects",
    "staleness_ownership_for",
    "subject_reference_resolves",
    "witness_kind_for",
]
