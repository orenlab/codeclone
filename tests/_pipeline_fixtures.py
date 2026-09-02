# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared harness for suites that run the pipeline over a golden fixture tree.

Several behavioural suites need the same four things: the domain's ground
truth, unit facts extracted from its tree, a bootstrap the pipeline accepts,
and a cold/warm run pair for cache-carriage guards. Each of those was written
once per suite until the clones lane said so; they live here now so a change to
the pipeline's entry shape lands in one place.
"""

from __future__ import annotations

import json
import shutil
from argparse import Namespace
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import codeclone.core.discovery as core_discovery
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.cache.store import Cache
from codeclone.core._types import BootstrapResult, OutputPaths
from codeclone.core.parallelism import process
from codeclone.core.pipeline import analyze
from codeclone.paths.module_identity.inventory import build_module_registry

if TYPE_CHECKING:
    from codeclone.core._types import AnalysisResult, DiscoveryResult, ProcessingResult
    from codeclone.models import Unit

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


def golden_root(domain: str) -> Path:
    """The fixture tree owning ``domain``."""

    return FIXTURES_ROOT / domain


def golden_ground_truth(domain: str) -> dict[str, Any]:
    """Return one domain's declared ground truth."""

    payload = json.loads((golden_root(domain) / "ground_truth.json").read_text("utf-8"))
    assert isinstance(payload, dict)
    return payload


def golden_case(domain: str, case_id: str) -> dict[str, Any]:
    """Return one declared case, or fail loudly on an unknown id."""

    for case in golden_ground_truth(domain)["cases"]:
        if case["id"] == case_id:
            return dict(case)
    raise AssertionError(f"unknown {domain} fixture case: {case_id}")


def payload_mapping(value: object) -> dict[str, object]:
    """Narrow a report-payload node to a typed mapping, or fail the test."""

    assert isinstance(value, Mapping)
    return {str(key): item for key, item in value.items()}


def payload_sequence(value: object) -> list[object]:
    """Narrow a report-payload node to a typed sequence, or fail the test."""

    assert isinstance(value, Sequence)
    assert not isinstance(value, str)
    return list(value)


def extract_units(root: Path, *, min_loc: int, min_stmt: int) -> list[Unit]:
    """Extract every unit fact of a fixture tree, in module-path order.

    Every fact includes the opt-in clone-artifact channels (T2): the suites
    this helper serves are the tier suites, and a helper that silently
    dropped their inputs would make each of them opt in separately or go
    inert. A suite pinning the *disabled* configuration calls the extractor
    itself with the flags it means.
    """

    registry = build_module_registry(root=root)
    units: list[Unit] = []
    for relative_path, entry in sorted(registry.entries_by_path.items()):
        source = (root / relative_path).read_text("utf-8")
        extracted, *_rest = extract_units_and_stats_from_source(
            source=source,
            filepath=relative_path,
            identity=entry.identity,
            registry=registry,
            cfg=NormalizationConfig(),
            min_loc=min_loc,
            min_stmt=min_stmt,
            collect_near_miss=True,
            collect_renamed_structure=True,
        )
        units.extend(extracted)
    return units


def analysis_boot(
    root: Path,
    *,
    min_loc: int,
    min_stmt: int,
    skip_metrics: bool,
    skip_dependencies: bool = False,
    skip_dead_code: bool = False,
    near_miss: bool = False,
    renamed_structure: bool = False,
    api_surface: bool = False,
) -> BootstrapResult:
    """A bootstrap over ``root`` with the clone floors the caller declares."""

    return BootstrapResult(
        root=root,
        config=NormalizationConfig(),
        args=Namespace(
            processes=1,
            min_loc=min_loc,
            min_stmt=min_stmt,
            block_min_loc=20,
            block_min_stmt=8,
            segment_min_loc=20,
            segment_min_stmt=10,
            skip_metrics=skip_metrics,
            api_surface=api_surface,
            skip_dependencies=skip_dependencies,
            skip_dead_code=skip_dead_code,
            near_miss=near_miss,
            renamed_structure=renamed_structure,
        ),
        output_paths=OutputPaths(html=None, json=None, text=None),
        cache_path=root / "cache.json",
    )


def package_tree(root: Path, fixture_file: Path) -> Path:
    """Lay one fixture module out as an importable package under ``root``."""

    package = root / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", "utf-8")
    shutil.copyfile(fixture_file, package / fixture_file.name)
    return package


def discover_and_process(
    boot: BootstrapResult,
    cache_path: Path,
    *,
    root: Path,
    warm: bool,
) -> tuple[Cache, DiscoveryResult, ProcessingResult]:
    """Discover and process once over a cold or warm cache, asserting nothing.

    ``run_pipeline_once`` layers the warmth guarantee on top of this. Suites
    that deliberately exercise cache *invalidation* need a warm pass that is
    allowed to re-analyse, so the assertion cannot live down here.
    """

    cache = Cache(cache_path, root=root)
    if warm:
        cache.load()
    discovery = core_discovery.discover(boot=boot, cache=cache)
    return cache, discovery, process(boot=boot, discovery=discovery, cache=cache)


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """One end-to-end run, kept together so cold and warm share one shape."""

    discovery: DiscoveryResult
    processing: ProcessingResult
    result: AnalysisResult


def run_pipeline_once(
    boot: BootstrapResult,
    cache_path: Path,
    *,
    root: Path,
    warm: bool,
    expect_cache_hits: int | None = None,
) -> tuple[Cache, PipelineRun]:
    """Discover, process and analyse once, over a cold or a warm cache.

    A warm run is asserted to be genuinely warm here rather than at the call
    site: a run that quietly re-analysed everything would make a carriage
    guard prove nothing at all.
    """

    cache, discovery, processing = discover_and_process(
        boot,
        cache_path,
        root=root,
        warm=warm,
    )
    if warm:
        assert processing.files_analyzed == 0, "warm run re-analysed; guard is inert"
        if expect_cache_hits is not None:
            assert discovery.cache_hits == expect_cache_hits
    return cache, PipelineRun(
        discovery=discovery,
        processing=processing,
        result=analyze(boot=boot, discovery=discovery, processing=processing),
    )
