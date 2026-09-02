# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The api-surface materialization decision has a witness on the cache row.

The clone-artifact lane answered this class at CACHE_VERSION 3.8 with ``mt``:
the row records what the writing extraction produced, and the reuse gate
compares that witness rather than the payload fields, because an empty artifact
list and a never-computed artifact list are byte-identical. ``api_surface`` was
the one lane with a materialization decision and no witness.

These pins are on the witness, not on the profile key. Both rows below carry
the same dependent profile digest, so a fix that only corrects which boolean
keys the profile leaves every assertion here green while the defect stands.
The end-to-end consequence is pinned in ``test_api_surface_cross_surface``.
"""

from __future__ import annotations

from pathlib import Path

from codeclone.cache.reuse import cache_reuse_decision
from codeclone.models import (
    CacheDependentPayload,
    CacheEntryV3,
    CacheNeutralPayload,
    CacheReuseDecision,
    ContentIdentityVerdict,
    DigestObject,
    SemanticFileFacts,
    SourceStatsDict,
)


def _stats() -> SourceStatsDict:
    return {"lines": 1, "functions": 0, "methods": 0, "classes": 0}


def _entry(*, materialized_api_surface: bool) -> CacheEntryV3:
    return CacheEntryV3(
        cache_content_binding_version="1",
        stat={"mtime_ns": 1, "size": 1},
        source_content_digest=DigestObject(
            domain="codeclone.source-content.v1", algorithm="sha256", value="0" * 64
        ),
        binding_context_digest=DigestObject(
            domain="codeclone.cache.binding-context.v1",
            algorithm="sha256",
            value="3" * 64,
        ),
        git_blob_id_at_write=None,
        module_neutral_profile=DigestObject(
            domain="codeclone.cache.profile.neutral.v1",
            algorithm="sha256",
            value="1" * 64,
        ),
        module_dependent_profile=DigestObject(
            domain="codeclone.cache.profile.dependent.v1",
            algorithm="sha256",
            value="2" * 64,
        ),
        module_neutral=CacheNeutralPayload(
            source_stats=_stats(),
            units=(),
            blocks=(),
            segments=(),
            semantic_facts=SemanticFileFacts(),
        ),
        module_dependent=CacheDependentPayload(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=(),
            referenced_qualnames=(),
            import_names=(),
            class_names=(),
            runtime_reachability=(),
            security_surfaces=(),
            function_relationship_facts=(),
            typing_coverage=None,
            docstring_coverage=None,
            api_surface=None,
            structural_findings=(),
            materialized_api_surface=materialized_api_surface,
        ),
    )


def _decide(
    *,
    row_materialized: bool,
    run_requires: bool,
) -> CacheReuseDecision:
    entry = _entry(materialized_api_surface=row_materialized)
    return cache_reuse_decision(
        content=ContentIdentityVerdict(
            hit=True,
            reason="blob_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        ),
        entry=entry,
        neutral_profile=entry.module_neutral_profile,
        dependent_profile=entry.module_dependent_profile,
        binding_context=entry.binding_context_digest,
        required_clone_channels=(),
        requires_api_surface=run_requires,
    )


def _verdict(*, row_materialized: bool, run_requires: bool) -> tuple[bool, str]:
    lane = _decide(
        row_materialized=row_materialized, run_requires=run_requires
    ).dependent
    return lane.hit, lane.reason


def test_a_row_without_the_api_witness_is_refused_by_a_run_needing_it() -> None:
    """The guard is the witness, not the profile key.

    Both rows here carry the *same* dependent profile digest, so a fix that
    only corrects which boolean keys the profile leaves this green while the
    defect stands. Only a witness on the row separates them.
    """

    assert _verdict(row_materialized=False, run_requires=True) == (
        False,
        "api_surface_witness_mismatch",
    )
    assert _verdict(row_materialized=True, run_requires=True) == (True, "hit")


def test_a_row_carrying_an_api_surface_a_run_never_computes_is_refused_too() -> None:
    """The opposite error is a different failure and reds here, not above.

    Equality in both directions is what makes warm output cold output: a row
    that materialized the lane, handed to a run that does not collect it, would
    serve artifacts the cold path never produces.
    """

    assert _verdict(row_materialized=True, run_requires=False) == (
        False,
        "api_surface_witness_mismatch",
    )
    assert _verdict(row_materialized=False, run_requires=False) == (True, "hit")


_PROBE_SOURCE = '__all__ = ["run"]\n\n\ndef run(value: int) -> int:\n    return value\n'


def _witness_of(root: Path, *, skip_metrics: bool, api_surface: bool) -> bool:
    """The witness a run of this shape actually stamps on the row it writes."""

    from tests._pipeline_fixtures import analysis_boot, discover_and_process

    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    module = package / "mod.py"
    module.write_text(_PROBE_SOURCE, encoding="utf-8")
    boot = analysis_boot(
        root,
        min_loc=1,
        min_stmt=1,
        skip_metrics=skip_metrics,
        api_surface=api_surface,
    )
    cache, _discovery, _processing = discover_and_process(
        boot, root / "cache.json", root=root, warm=False
    )
    entry = cache.get_file_entry(str(module))
    assert entry is not None, "the run wrote no row for the probe module"
    return entry.module_dependent.materialized_api_surface


def test_a_run_that_collects_the_api_surface_claims_it_on_every_row(
    tmp_path: Path,
) -> None:
    """The claiming direction, read back off the row the run wrote."""

    assert (
        _witness_of(tmp_path / "collecting", skip_metrics=False, api_surface=True)
        is True
    )


def test_a_run_that_collects_nothing_claims_nothing(tmp_path: Path) -> None:
    """The refusing direction, and the shape that produced the defect.

    ``skip_metrics`` with the lane configured on is exactly what a
    ``clones_only`` call is: the flag says yes, the extraction does nothing.
    The witness follows the extraction, so both of the two ways to get there
    are asserted -- the flag off, and the flag on under a metrics-skipping run.
    """

    assert (
        _witness_of(tmp_path / "skipping", skip_metrics=True, api_surface=True) is False
    )
    assert (
        _witness_of(tmp_path / "unasked", skip_metrics=False, api_surface=False)
        is False
    )
