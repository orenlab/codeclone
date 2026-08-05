# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The declared ``near_miss`` clone tier (39Y Y8, EMP-CC-003b).

Exact fingerprints cannot match two functions whose normalized statement
sequences differ at all, so a clone that carries one extra statement is
invisible to every existing tier. The declared rule closing that gap:

    two clone-eligible units are a ``near_miss`` pair when their normalized
    statement sequences differ by at least one and at most
    ``NEAR_MISS_MAX_EDIT_STATEMENTS`` inserted, deleted or replaced
    statements.

Integer distance, named bound, no similarity score. Distance zero stays the
exact tier's business, and a divergence that lands on a control-flow anchor
rather than a statement is not a statement edit, so it does not qualify.

Confinement: this channel never enters ``func_groups``, so it reaches no
observation lane, no baseline novelty and no gate. It is advisory by
construction rather than by a flag that could be flipped.

The distance is sequence Levenshtein over the normalized statement tokens:
an inserted, deleted or replaced statement costs exactly one edit and an
equal statement costs zero. Not LCS distance, which would price a replace as
delete-plus-insert at two; not a positional diff, which would cascade one
insertion into a difference at every later position. The contract is
two-layer: the VERDICT is the scalar minimum distance and is unique, while
the WITNESS — which statements are reported as the edit — is not unique once
a sequence repeats a fingerprint, so ``_edit_script`` fixes one canonical
optimal script by a documented total order over the DP backtrace.

Cost. Pairwise scanning would be quadratic in functions. Instead the tier
indexes deletion variants: for ``K = 1``, ``distance(a, b) <= 1`` implies
``del(a)`` and ``del(b)`` intersect, where ``del(x)`` is ``x`` plus its ``L``
one-statement deletions — deleting the inserted statement from the longer side,
or the replaced statement from both, lands on the same sequence. Prefix and
suffix hashes make each variant key O(1), so indexing is O(L) per unit and
O(total statements) overall.

The index is only a superset filter: ``[X, Y]`` and ``[Y, X]`` share the
variants ``[X]`` and ``[Y]`` yet sit at distance two. Every candidate therefore
goes through the exact bounded confirmation before it can be reported, and
confirmation runs once per distinct sequence pair — an O(n*m) dynamic program
over two function-sized sequences the index has already certified as
near-identical, so the quadratic bound is confined.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final, Literal

from ...analysis.fingerprint import is_near_miss_statement_token
from ...contracts import NEAR_MISS_MAX_EDIT_STATEMENTS
from ...contracts.errors import ValidationError
from ...models import NearMissElement, NearMissMember, NearMissPair
from ...utils.coerce import as_int

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...models import GroupItemLike, GroupItemsLike

__all__ = ["build_near_miss_pairs"]

# The single edit distance this module is CONSTRUCTED for, as opposed to the
# contract value it enforces. The deletion index assumes it: one one-statement
# deletion per sequence, so candidates beyond distance one are never even
# collected. The Levenshtein confirmation itself is general — the index is
# what pins the module to K = 1. Kept separate from the contract constant so
# the two can be compared and the mismatch refused loudly.
_SUPPORTED_MAX_EDIT_STATEMENTS: Final = 1

_VARIANT_DOMAIN: Final = b"ccnm:variant\x00"
# Mersenne prime modulus and a fixed base for the canonical sequence hash.
# Both are constants of the encoding, not tunable knobs: no classification
# outcome moves with them, because every candidate is confirmed exactly.
_VARIANT_MODULUS: Final = (1 << 61) - 1
_VARIANT_BASE: Final = 1_000_003
_VARIANT_BASE_INVERSE: Final = pow(_VARIANT_BASE, -1, _VARIANT_MODULUS)

_Tokens = tuple[str, ...]
# (filepath, qualname, start_line, end_line) — the sort key is the tuple order.
_Location = tuple[str, str, int, int]
_EditKind = Literal["insert", "delete", "replace"]
# One canonical-script operation: (kind, left index, right index), ``-1``
# where that side contributes no element.
_ScriptOp = tuple[Literal["equal", "insert", "delete", "replace"], int, int]
# Units grouped by their exact normalized statement sequence.
_Cohort = dict[_Tokens, list[tuple[_Location, tuple[NearMissElement, ...]]]]
_FLIPPED_KIND: Final[dict[str, _EditKind]] = {
    "insert": "delete",
    "delete": "insert",
    "replace": "replace",
}
# Narrows a script op kind to the reportable edit kinds; ``"equal"`` is
# filtered before this table is consulted, and a leak fails loudly as a
# KeyError instead of a silently wrong finding.
_SCRIPT_EDIT_KIND: Final[dict[str, _EditKind]] = {
    "insert": "insert",
    "delete": "delete",
    "replace": "replace",
}


def _token_value(token: str) -> int:
    return (
        int.from_bytes(
            hashlib.sha256(_VARIANT_DOMAIN + token.encode("utf-8")).digest()[:8],
            "big",
        )
        % _VARIANT_MODULUS
    )


def _deletion_variant_keys(tokens: _Tokens) -> tuple[tuple[int, int], ...]:
    """Return the sequence's own key plus one key per single-statement deletion.

    Every key is the *canonical* hash of the sequence it denotes, so a shorter
    sequence's own key equals the longer sequence's key for deleting the extra
    statement. A prefix/suffix chain cannot do this — it encodes the same tail
    differently depending on where the split falls — so the hash is polynomial:
    ``sum(value(token_k) * BASE**k)`` modulo a fixed prime. Deleting index
    ``i`` shifts every later term down one power, which is one modular
    multiplication by the inverse base. Prefix sums make the whole family O(L).

    Keys carry the resulting length so sequences of different sizes cannot
    share one. A hash collision can only add a candidate — never remove one —
    because equal sequences always produce equal keys, and every candidate is
    confirmed exactly before it is reported.
    """

    length = len(tokens)
    prefix = [0] * (length + 1)
    power = 1
    for index, token in enumerate(tokens):
        prefix[index + 1] = (
            prefix[index] + _token_value(token) * power
        ) % _VARIANT_MODULUS
        power = (power * _VARIANT_BASE) % _VARIANT_MODULUS

    keys = [(length, prefix[length])]
    for index, token in enumerate(tokens):
        # Anchors are structure, not statements: deleting one would model an
        # edit the declared rule does not recognise.
        if not is_near_miss_statement_token(token):
            continue
        tail = (prefix[length] - prefix[index + 1]) % _VARIANT_MODULUS
        shifted = (tail * _VARIANT_BASE_INVERSE) % _VARIANT_MODULUS
        keys.append((length - 1, (prefix[index] + shifted) % _VARIANT_MODULUS))
    return tuple(keys)


def _edit_script(left: _Tokens, right: _Tokens) -> tuple[_ScriptOp, ...]:
    """Return THE canonical optimal edit script between two token sequences.

    The verdict layer needs no tie-break — the minimum edit distance is
    unique. The witness layer does: once a sequence repeats a fingerprint,
    several equally cheap scripts exist, and evidence must not depend on
    implementation accident. Canonicality is one total order over the DP
    backtrace: at every cell exactly the first applicable rule below is
    taken, so every equal-cost fork resolves identically on every run.

    Backtrace decision table. ``D`` is the Levenshtein matrix (insert,
    delete and replace cost one; equal costs zero). The walk starts at
    ``(len(left), len(right))``, ends at ``(0, 0)``, and the emitted
    operations are reversed into left-to-right sequence order::

        | # | taken when (first match wins)                            | emits   |
        |---|----------------------------------------------------------|---------|
        | 1 | i>0, j>0, left[i-1] == right[j-1], D[i][j] == D[i-1][j-1]     | equal   |
        | 2 | i>0, j>0, left[i-1] != right[j-1], D[i][j] == D[i-1][j-1] + 1 | replace |
        | 3 | i>0, D[i][j] == D[i-1][j] + 1                                 | delete  |
        | 4 | j>0, D[i][j] == D[i][j-1] + 1                                 | insert  |

    Exactly one rule fires at every cell because they are tried in this
    fixed order, and every rule strictly decreases ``i + j``, so the walk
    terminates with a complete script. Two consequences are the law's
    observable contract, both pinned by tests: the single edit of a
    within-budget pair lands on the LEFTMOST position of a repeated-
    fingerprint run, and the equal-cost fork between a replace and a
    delete-plus-insert decomposition resolves so the delete or insert
    precedes the replace in left-to-right reading.

    O(len(left) * len(right)) time and space — two function-sized sequences
    that the deletion index has already certified as near-identical.
    """

    left_length, right_length = len(left), len(right)
    distance = [[0] * (right_length + 1) for _ in range(left_length + 1)]
    for i in range(left_length + 1):
        distance[i][0] = i
    for j in range(right_length + 1):
        distance[0][j] = j
    for i in range(1, left_length + 1):
        for j in range(1, right_length + 1):
            distance[i][j] = min(
                distance[i - 1][j] + 1,
                distance[i][j - 1] + 1,
                distance[i - 1][j - 1] + (left[i - 1] != right[j - 1]),
            )

    ops: list[_ScriptOp] = []
    i, j = left_length, right_length
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and left[i - 1] == right[j - 1]
            and distance[i][j] == distance[i - 1][j - 1]
        ):
            ops.append(("equal", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif (
            i > 0
            and j > 0
            and left[i - 1] != right[j - 1]
            and distance[i][j] == distance[i - 1][j - 1] + 1
        ):
            ops.append(("replace", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and distance[i][j] == distance[i - 1][j] + 1:
            ops.append(("delete", i - 1, -1))
            i -= 1
        else:
            ops.append(("insert", -1, j - 1))
            j -= 1
    return tuple(reversed(ops))


def _confirm(left: _Tokens, right: _Tokens) -> tuple[_EditKind, int, int, int] | None:
    """Exact bounded check: edit kind, each side's edit index, and the distance.

    The distance is sequence Levenshtein, so one inserted statement is one
    edit — never a cascade of positional differences, and a replace is never
    priced as delete-plus-insert. ``None`` means distance zero (the exact
    tier's business) or beyond ``NEAR_MISS_MAX_EDIT_STATEMENTS``, which is
    the answer for every candidate the deletion index over-collects. The
    returned indexes point at the canonical witness fixed by
    ``_edit_script``, or ``-1`` where that side has no edited element.
    """

    if abs(len(left) - len(right)) > NEAR_MISS_MAX_EDIT_STATEMENTS:
        return None
    edits = [op for op in _edit_script(left, right) if op[0] != "equal"]
    if not edits or len(edits) > NEAR_MISS_MAX_EDIT_STATEMENTS:
        return None
    kind, left_index, right_index = edits[0]
    return (_SCRIPT_EDIT_KIND[kind], left_index, right_index, len(edits))


def _elements(unit: GroupItemLike) -> tuple[NearMissElement, ...]:
    raw = unit.get("statement_sequence", ())
    if not isinstance(raw, (tuple, list)):
        return ()
    elements: list[NearMissElement] = []
    for item in raw:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            return ()
        elements.append((str(item[0]), as_int(item[1]), as_int(item[2])))
    return tuple(elements)


def _span(elements: Sequence[NearMissElement], index: int) -> tuple[int, int]:
    if index < 0:
        return (0, 0)
    _token, start, end = elements[index]
    return (start, end)


def _sequences_by_tokens(units: GroupItemsLike) -> _Cohort:
    """Group unit facts by their normalized statement sequence.

    Units that share a sequence exactly are one cohort: they are the exact
    tier's business, and collapsing them here means confirmation runs once per
    distinct sequence pair rather than once per unit pair.
    """

    sequences: _Cohort = {}
    for unit in units:
        elements = _elements(unit)
        if elements:
            location: _Location = (
                str(unit.get("filepath", "")),
                str(unit.get("qualname", "")),
                as_int(unit.get("start_line", 0)),
                as_int(unit.get("end_line", 0)),
            )
            tokens = tuple(element[0] for element in elements)
            sequences.setdefault(tokens, []).append((location, elements))
    return sequences


def _candidate_sequence_pairs(sequences: _Cohort) -> list[tuple[_Tokens, _Tokens]]:
    """Return sequence pairs that share a deletion variant, in sorted order.

    A superset of the answer: co-indexing is necessary for distance one but not
    sufficient, so every pair returned here still has to be confirmed exactly.
    """

    index: dict[tuple[int, int], list[_Tokens]] = {}
    for tokens in sequences:
        for key in _deletion_variant_keys(tokens):
            index.setdefault(key, []).append(tokens)

    candidates: set[tuple[_Tokens, _Tokens]] = set()
    for co_indexed in index.values():
        ordered = sorted(set(co_indexed))
        for position, left in enumerate(ordered):
            for right in ordered[position + 1 :]:
                candidates.add((left, right))
    return sorted(candidates)


def _edit_is_on_statements(
    left_tokens: _Tokens,
    right_tokens: _Tokens,
    *,
    left_index: int,
    right_index: int,
) -> bool:
    """Return whether the confirmed edit lands on statements, not anchors.

    A statement edit is the declared predicate; a divergence that lands on a
    control-flow anchor is a different fact and is not reported as a near miss.
    The edited tokens are a property of the sequence pair, so this decides a
    whole cohort at once.
    """

    return all(
        is_near_miss_statement_token(tokens[position])
        for tokens, position in (
            (left_tokens, left_index),
            (right_tokens, right_index),
        )
        if position >= 0
    )


def _cohort_pairs(
    sequences: _Cohort,
    *,
    left_tokens: _Tokens,
    right_tokens: _Tokens,
    confirmed: tuple[_EditKind, int, int, int],
) -> list[NearMissPair]:
    """Expand one confirmed sequence pair over every unit that carries it."""

    edit_kind, left_index, right_index, distance = confirmed
    return [
        _pair(
            left=(left_location, _span(left_elements, left_index)),
            right=(right_location, _span(right_elements, right_index)),
            edit_kind=edit_kind,
            edit_statements=distance,
        )
        for left_location, left_elements in sorted(sequences[left_tokens])
        for right_location, right_elements in sorted(sequences[right_tokens])
    ]


def build_near_miss_pairs(units: GroupItemsLike) -> tuple[NearMissPair, ...]:
    """Return every declared near-miss pair among clone-eligible unit facts.

    ``units`` must already be the clone lane's population: the tier inherits
    the lane's floors instead of re-deciding eligibility.

    Raises:
        ValidationError: if ``NEAR_MISS_MAX_EDIT_STATEMENTS`` has moved off the
            single edit this module is built for.
    """

    if NEAR_MISS_MAX_EDIT_STATEMENTS != _SUPPORTED_MAX_EDIT_STATEMENTS:
        raise ValidationError(
            "near_miss supports NEAR_MISS_MAX_EDIT_STATEMENTS == "
            f"{_SUPPORTED_MAX_EDIT_STATEMENTS}, got "
            f"{NEAR_MISS_MAX_EDIT_STATEMENTS}. The deletion index emits one "
            "one-statement deletion per sequence, so candidates beyond "
            "distance one are never collected: a larger bound would keep "
            "reporting only distance-1 pairs while claiming a wider tier. "
            "Widening the tier requires widening the index construction."
        )

    sequences = _sequences_by_tokens(units)
    pairs: list[NearMissPair] = []
    for left_tokens, right_tokens in _candidate_sequence_pairs(sequences):
        confirmed = _confirm(left_tokens, right_tokens)
        if confirmed is not None and _edit_is_on_statements(
            left_tokens,
            right_tokens,
            left_index=confirmed[1],
            right_index=confirmed[2],
        ):
            pairs.extend(
                _cohort_pairs(
                    sequences,
                    left_tokens=left_tokens,
                    right_tokens=right_tokens,
                    confirmed=confirmed,
                )
            )
    return tuple(sorted(pairs, key=lambda pair: pair.pair_key))


def _member_key(location: _Location) -> str:
    filepath, qualname, start_line, _end_line = location
    return f"{filepath}:{qualname}:{start_line}"


def _pair(
    *,
    left: tuple[_Location, tuple[int, int]],
    right: tuple[_Location, tuple[int, int]],
    edit_kind: _EditKind,
    edit_statements: int,
) -> NearMissPair:
    ordered = sorted((left, right), key=lambda side: side[0])
    if ordered[0] is not left:
        edit_kind = _FLIPPED_KIND[edit_kind]
    members = tuple(
        NearMissMember(
            qualname=location[1],
            filepath=location[0],
            start_line=location[2],
            end_line=location[3],
            differing_start_line=span[0],
            differing_end_line=span[1],
        )
        for location, span in ordered
    )
    return NearMissPair(
        pair_key=f"{_member_key(ordered[0][0])}|{_member_key(ordered[1][0])}",
        members=(members[0], members[1]),
        edit_statements=edit_statements,
        edit_kind=edit_kind,
    )
