# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The clone-artifact materialization law (tier ruling T2, 2026-08-24).

The near-miss statement sequence (39Y Y8) and the renamed-structure artifacts
(Wave C) are inputs of two opt-in detection tiers. The law this suite pins has
two halves:

1. **Disabled tiers cost nothing.** An extraction run whose configuration did
   not ask for a tier does not compute that tier's per-unit artifacts, and the
   cache rows it writes carry none.

2. **Cache absence is never computed emptiness.** A warm opt-in run over a
   cache written with the tier disabled must read the missing payload as "not
   materialized — recompute", never as "materialized empty". The distinction
   is carried *in the row form itself* by the materialization witness (the
   ``mt`` key of the neutral wire): a closed sorted list of the channels whose
   artifacts the writing extraction actually produced. The witness is the
   single authority the reuse gate consults; a row whose witness disagrees
   with its payload keys is rejected at decode, in both directions of the lie.

Measured on the pre-witness generation (3.7): a cache whose rows carried
present-but-empty artifact payloads loaded with ``load_status=ok``, warm-hit
every file, and the opt-in run reported zero near-miss pairs where a cold run
reports five — the exact silent lie the witness makes structurally illegal.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from codeclone.cache.store import Cache
from codeclone.cache.versioning import CacheStatus
from codeclone.models import ContentIdentityVerdict, Unit
from tests._ast_metrics_helpers import module_registry_context
from tests._cache_store_fixtures import read_cache_rows, write_cache_row
from tests._pipeline_fixtures import (
    analysis_boot,
    discover_and_process,
    golden_root,
    run_pipeline_once,
)

if TYPE_CHECKING:
    from codeclone.core._types import BootstrapResult
    from codeclone.models import NearMissPair, RenamedStructureGroup

DOMAIN = "clone_tiers"
FIXTURE_ROOT = golden_root(DOMAIN)
FIXTURE_MIN_LOC = 6
FIXTURE_MIN_STMT = 4

# One function comfortably above the default clone floors (6 loc / 4 stmt).
_ELIGIBLE_SOURCE = """\
def transfer(amount, source, target):
    if amount <= 0:
        raise ValueError("amount")
    balance = source.balance - amount
    if balance < 0:
        raise ValueError("balance")
    source.balance = balance
    target.balance = target.balance + amount
    return balance
"""


def _extract_units(
    *,
    collect_near_miss: bool = False,
    collect_renamed_structure: bool = False,
) -> list[Unit]:
    from codeclone.analysis.normalizer import NormalizationConfig
    from codeclone.analysis.units import extract_units_and_stats_from_source

    identity, registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )
    units, *_rest = extract_units_and_stats_from_source(
        source=_ELIGIBLE_SOURCE,
        filepath="pkg/mod.py",
        identity=identity,
        registry=registry,
        cfg=NormalizationConfig(),
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
        collect_near_miss=collect_near_miss,
        collect_renamed_structure=collect_renamed_structure,
    )
    return units


def _the_unit(units: list[Unit]) -> Unit:
    assert len(units) == 1
    return units[0]


def test_disabled_tiers_extract_no_artifacts() -> None:
    """T2 requirement (a): default extraction computes no tier artifacts.

    Both tiers are opt-in and off by default, so the default extraction call
    must leave every artifact field at its empty value. Mutation mut-1
    (reverting the gate so the artifacts are computed eagerly again) turns
    these fields non-empty and reds this test.
    """

    unit = _the_unit(_extract_units())
    assert unit.statement_sequence == ()
    assert unit.renamed_fingerprint == ""
    assert unit.renamed_statement_sequence == ()


def test_each_enabled_tier_computes_exactly_its_consumed_artifacts() -> None:
    """The opposite boundary, per channel, along the measured consumer graph.

    The near-miss tier consumes the y8 statement sequence AND the
    renamed-canonical sequence (its ``renamed`` token domain — see
    _DOMAIN_SEQUENCE_KEYS in findings/clones/near_miss.py); the
    renamed-structure tier consumes the digest and shares the
    renamed-canonical sequence. Mutation mut-2 (an enabled tier losing an
    artifact it consumes) reds a non-empty half; a cross-wired gate reds a
    still-empty half.
    """

    near_miss_only = _the_unit(_extract_units(collect_near_miss=True))
    assert near_miss_only.statement_sequence, "opt-in near_miss lost its y8 sequence"
    assert near_miss_only.renamed_statement_sequence, (
        "opt-in near_miss lost its renamed-domain sequence"
    )
    assert near_miss_only.renamed_fingerprint == ""

    renamed_only = _the_unit(_extract_units(collect_renamed_structure=True))
    assert renamed_only.statement_sequence == ()
    assert renamed_only.renamed_fingerprint, "opt-in renamed lost its digest"
    assert renamed_only.renamed_statement_sequence, "opt-in renamed lost its sequence"

    both = _the_unit(
        _extract_units(collect_near_miss=True, collect_renamed_structure=True)
    )
    assert both.statement_sequence == near_miss_only.statement_sequence
    assert both.renamed_fingerprint == renamed_only.renamed_fingerprint
    assert both.renamed_statement_sequence == renamed_only.renamed_statement_sequence
    assert (
        near_miss_only.renamed_statement_sequence
        == renamed_only.renamed_statement_sequence
    ), "one walk, one sequence — the two claims must not diverge"


def _pairs_package_boot(
    tmp_path: Path,
    *,
    near_miss: bool,
    renamed_structure: bool = False,
) -> BootstrapResult:
    """Bootstrap over the labelled-pair package, laying it out at most once.

    Laying out on every call would touch the files' mtimes, and a changed stat
    is a content miss before any reuse profile is consulted — every warm run
    in the suite would re-analyse for that reason alone and the witness gate
    would never be exercised. Measured under mutation: with the gate deleted,
    a warm opt-in run over a re-copied tree still recomputed the right pairs,
    so the law pins were green for the wrong mechanism.
    """

    package = tmp_path / "pkg"
    if not package.exists():
        package.mkdir()
        (package / "__init__.py").write_text("", "utf-8")
        shutil.copyfile(FIXTURE_ROOT / "pairs.py", package / "pairs.py")
    return analysis_boot(
        tmp_path,
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
        skip_metrics=True,
        near_miss=near_miss,
        renamed_structure=renamed_structure,
    )


def _pair_signature(pairs: tuple[NearMissPair, ...] | None) -> list[tuple[str, ...]]:
    assert pairs is not None
    return sorted(
        (
            pair.members[0].qualname,
            pair.members[1].qualname,
            pair.edit_kind,
            pair.token_domain,
        )
        for pair in pairs
    )


def _group_signature(
    groups: tuple[RenamedStructureGroup, ...] | None,
) -> list[tuple[str, ...]]:
    assert groups is not None
    return sorted(
        tuple(sorted(member.qualname for member in group.members)) for group in groups
    )


def _neutral_wires(cache_path: Path) -> list[dict[str, object]]:
    return [
        cast(dict[str, object], cast(dict[str, object], entry)["n"])
        for entry in read_cache_rows(cache_path).values()
    ]


def _cold_cache(
    root: Path,
    *,
    near_miss: bool,
    renamed_structure: bool = False,
) -> tuple[Cache, Path]:
    """One cold analysis over the pairs package, its cache persisted."""

    boot = _pairs_package_boot(
        root, near_miss=near_miss, renamed_structure=renamed_structure
    )
    cache_path = root / "cache.json"
    cache, _discovery, processing = discover_and_process(
        boot, cache_path, root=root, warm=False
    )
    assert processing.files_analyzed > 0, "cold run analysed nothing; harness inert"
    cache.save()
    return cache, cache_path


def test_tier_off_cache_rows_carry_witness_and_no_artifact_payload(
    tmp_path: Path,
) -> None:
    """A tier-off run writes rows that *declare* nothing was materialized.

    The declaration is the point: the payload keys are absent AND the witness
    says so, so a later reader never has to guess what an absent key means.
    """

    _cache, cache_path = _cold_cache(tmp_path, near_miss=False)

    wires = _neutral_wires(cache_path)
    assert wires, "the run cached no file entries; the guard is inert"
    for neutral in wires:
        assert neutral["mt"] == []
        assert "us" not in neutral
        assert "uc" not in neutral
        assert "urs" not in neutral


def test_tier_on_cache_rows_carry_witness_and_artifact_payload(
    tmp_path: Path,
) -> None:
    """The opposite boundary: opt-in rows declare and carry their channels."""

    _cache, cache_path = _cold_cache(tmp_path, near_miss=True, renamed_structure=True)

    wires = _neutral_wires(cache_path)
    assert wires, "the run cached no file entries; the guard is inert"
    seen_sequence_rows = False
    for neutral in wires:
        assert neutral["mt"] == ["near_miss", "renamed_structure"]
        if neutral.get("u"):
            assert "us" in neutral
            assert "uc" in neutral
            assert "urs" in neutral
            seen_sequence_rows = True
    assert seen_sequence_rows, "no cached unit rows; the guard is inert"

    # Near-miss alone claims "us" AND "urs" (its renamed token domain) but
    # never the digest key "uc" — the union semantics of _CLONE_KEY_CLAIMS.
    near_miss_root = tmp_path / "near-miss-only"
    near_miss_root.mkdir()
    _near_miss_cache, near_miss_cache_path = _cold_cache(near_miss_root, near_miss=True)
    for neutral in _neutral_wires(near_miss_cache_path):
        assert neutral["mt"] == ["near_miss"]
        if neutral.get("u"):
            assert "us" in neutral
            assert "urs" in neutral
            assert "uc" not in neutral


def test_warm_opt_in_over_tier_off_cache_recomputes_instead_of_serving_empty(
    tmp_path: Path,
) -> None:
    """Law (v), the core pin: cache absence is recomputed, never read as empty.

    A cache built with both tiers off carries no artifacts. The warm opt-in
    run over it must produce exactly the pairs and groups a cold opt-in run
    produces — and it can only do so by re-analysing, which the second
    assertion witnesses. Mutation mut-3 (dropping the witness gate from the
    reuse decision) serves the artifact-less rows as materialized-empty: zero
    pairs, zero groups, zero files re-analysed — both assertions red.
    """

    _off_cache, cache_path = _cold_cache(tmp_path, near_miss=False)

    _cache, cold = run_pipeline_once(
        _pairs_package_boot(tmp_path, near_miss=True, renamed_structure=True),
        tmp_path / "cache-cold-opt-in.json",
        root=tmp_path,
        warm=False,
    )
    cold_pairs = _pair_signature(cold.result.near_miss_pairs)
    cold_groups = _group_signature(cold.result.renamed_structure_groups)
    assert cold_pairs, "cold opt-in run found no pair; the guard is inert"
    assert cold_groups, "cold opt-in run found no group; the guard is inert"

    on_boot = _pairs_package_boot(tmp_path, near_miss=True, renamed_structure=True)
    from codeclone.core.pipeline import analyze

    _warm_cache, _discovery, warm_processing = discover_and_process(
        on_boot, cache_path, root=tmp_path, warm=True
    )
    warm = analyze(boot=on_boot, discovery=_discovery, processing=warm_processing)
    assert _pair_signature(warm.near_miss_pairs) == cold_pairs
    assert _group_signature(warm.renamed_structure_groups) == cold_groups
    assert warm_processing.files_analyzed > 0, (
        "the opt-in run served the artifact-less cache instead of recomputing"
    )


def test_warm_tier_off_over_opt_in_cache_recomputes(tmp_path: Path) -> None:
    """The reverse toggle misses too: a superset row is not this run's row.

    Strict equality keeps warm byte-identical to cold by construction — a
    tier-off run over opt-in rows would otherwise carry artifacts a cold
    tier-off run never computes.
    """

    _on_cache, cache_path = _cold_cache(
        tmp_path, near_miss=True, renamed_structure=True
    )

    off_boot = _pairs_package_boot(tmp_path, near_miss=False)
    _cache, _discovery, off_processing = discover_and_process(
        off_boot, cache_path, root=tmp_path, warm=True
    )
    assert off_processing.files_analyzed > 0


def test_same_channels_warm_run_stays_warm(tmp_path: Path) -> None:
    """The gate's hit boundary: matching channels keep the cache warm.

    Without this pin the channel gate could satisfy every miss-side test by
    missing always — the exact inert-guard failure mode.
    """

    for near_miss, renamed_structure in ((False, False), (True, True)):
        root = tmp_path / f"tree-{near_miss}-{renamed_structure}"
        root.mkdir()
        _cold, cache_path = _cold_cache(
            root, near_miss=near_miss, renamed_structure=renamed_structure
        )
        boot = _pairs_package_boot(
            root, near_miss=near_miss, renamed_structure=renamed_structure
        )
        _cache, _discovery, warm_processing = discover_and_process(
            boot, cache_path, root=root, warm=True
        )
        assert warm_processing.files_analyzed == 0, (
            f"same-channel warm run re-analysed at "
            f"near_miss={near_miss} renamed_structure={renamed_structure}"
        )


def _rewrite_neutral_wires(
    cache_path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    for wire_path, entry in read_cache_rows(cache_path).items():
        typed = cast(dict[str, object], entry)
        mutate(cast(dict[str, object], typed["n"]))
        # Re-checksum each row so the rewrite reaches the decode gate under
        # test rather than stopping at the integrity gate in front of it.
        write_cache_row(cache_path, wire_path, typed)


def _assert_no_entry_authorises_a_hit(cache_path: Path, root: Path) -> None:
    """No stored entry may be served after its witness was falsified.

    The refusal moved with the schema, and moved for the better. The document
    store could only answer by condemning the whole cache; identity and lanes
    apart, the store stays readable and the entries whose witness no longer
    decodes simply do not come back. What must not change is that none of them
    authorises a hit.
    """

    cache = Cache(cache_path, root=root)
    cache.load()
    assert cache.load_status == CacheStatus.OK
    stored = read_cache_rows(cache_path)
    assert stored, "the probe needs entries to falsify"
    for wire_path in stored:
        assert cache.get_file_entry(str(root / wire_path)) is None


def _loaded_cache_status(cache_path: Path, root: Path) -> CacheStatus:
    cache = Cache(cache_path, root=root)
    cache.load()
    return cache.load_status


def test_witness_under_claim_is_rejected_at_decode(tmp_path: Path) -> None:
    """mut-4, direction one: payload present, witness denies it — reject.

    This row shape claims "nothing materialized" while carrying sequence rows.
    Serving it would hand a tier-off run artifacts its own cold extraction
    never computes; trusting the keys over the witness would resurrect the
    pre-witness guessing game. The row is a lie and dies at decode.
    """

    _cache, cache_path = _cold_cache(tmp_path, near_miss=True, renamed_structure=True)

    def deny_witness(neutral: dict[str, object]) -> None:
        neutral["mt"] = []

    _rewrite_neutral_wires(cache_path, deny_witness)
    _assert_no_entry_authorises_a_hit(cache_path, tmp_path)


def test_witness_over_claim_is_rejected_at_decode(tmp_path: Path) -> None:
    """mut-4, direction two: witness claims a channel its payload lacks.

    This is the measured B8 form one floor down: on the pre-witness generation
    the same bytes (minus the witness) loaded fine and served empty artifacts
    as materialized. With the witness law the claim must be backed by the
    payload key, so the lying row dies at decode instead.
    """

    _cache, cache_path = _cold_cache(tmp_path, near_miss=False)

    def claim_channels(neutral: dict[str, object]) -> None:
        neutral["mt"] = ["near_miss", "renamed_structure"]

    _rewrite_neutral_wires(cache_path, claim_channels)
    _assert_no_entry_authorises_a_hit(cache_path, tmp_path)


def test_witness_outside_closed_vocabulary_is_rejected_at_decode(
    tmp_path: Path,
) -> None:
    """The witness vocabulary is closed; an unknown channel name is no witness."""

    _cache, cache_path = _cold_cache(tmp_path, near_miss=False)

    def unknown_channel(neutral: dict[str, object]) -> None:
        neutral["mt"] = ["exact"]

    _rewrite_neutral_wires(cache_path, unknown_channel)
    _assert_no_entry_authorises_a_hit(cache_path, tmp_path)


def test_reuse_gate_requires_exact_channel_match(tmp_path: Path) -> None:
    """The witness is what the reuse gate reads, with its own typed reason.

    Both mismatch directions and the hit are asserted on one production-built
    entry, so the reason can never be blurred into ``neutral_profile_mismatch``
    (the profiles are identical across all three calls).
    """

    # Deferred: the name is this change's contract surface, and the module
    # must still collect on the pre-witness generation for the red capture.
    from codeclone.cache.reuse import clone_artifact_channels

    cache, _cache_path = _cold_cache(tmp_path, near_miss=True, renamed_structure=True)

    filepath = str(tmp_path / "pkg" / "pairs.py")
    entry = cache.get_file_entry(filepath)
    assert entry is not None
    content_hit = ContentIdentityVerdict(
        hit=True,
        reason="digest_hit",
        git_fallback_reason=None,
        digest_verify_cost_us=0,
        stat_fast_reject=False,
    )

    both = clone_artifact_channels(near_miss=True, renamed_structure=True)
    matching = cache.reuse_decision(
        content=content_hit,
        entry=entry,
        runtime_path=filepath,
        required_clone_channels=both,
    )
    assert matching.neutral.hit

    fewer = cache.reuse_decision(
        content=content_hit,
        entry=entry,
        runtime_path=filepath,
        required_clone_channels=clone_artifact_channels(
            near_miss=False, renamed_structure=False
        ),
    )
    assert not fewer.neutral.hit
    assert fewer.neutral.reason == "clone_channels_mismatch"

    partial = cache.reuse_decision(
        content=content_hit,
        entry=entry,
        runtime_path=filepath,
        required_clone_channels=clone_artifact_channels(
            near_miss=True, renamed_structure=False
        ),
    )
    assert not partial.neutral.hit
    assert partial.neutral.reason == "clone_channels_mismatch"


def test_put_file_entry_refuses_artifacts_the_witness_does_not_claim(
    tmp_path: Path,
) -> None:
    """The producer-side half of mut-4: an under-claiming witness is loud.

    An artifact the witness does not claim would be silently dropped by the
    encoder — computed work thrown away and a row that cannot explain itself.
    The put is refused instead.
    """

    from codeclone.cache.projection import rehydrate_cache_neutral
    from codeclone.cache.reuse import clone_artifact_channels

    cache, _cache_path = _cold_cache(tmp_path, near_miss=True, renamed_structure=True)
    filepath = str(tmp_path / "pkg" / "pairs.py")
    entry = cache.get_file_entry(filepath)
    assert entry is not None
    rehydrated = rehydrate_cache_neutral(
        entry.module_neutral,
        module_name="pkg.pairs",
        filepath=filepath,
        analysed_filepath="pkg/pairs.py",
    )
    units = [unit for unit in rehydrated.units if unit.statement_sequence]
    assert units, "no cached unit carries a sequence; the guard is inert"

    with pytest.raises(ValueError, match="witness"):
        cache.put_file_entry(
            filepath,
            entry.stat,
            units,
            [],
            [],
            source_content_digest=entry.source_content_digest,
            materialized_clone_channels=clone_artifact_channels(
                near_miss=False, renamed_structure=False
            ),
        )
