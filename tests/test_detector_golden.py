# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.baseline import current_python_tag
from codeclone.findings.clones.grouping import build_block_groups, build_groups
from codeclone.paths.module_identity.inventory import build_module_registry
from tests._assertions import (
    assert_snapshot_matches_or_smoke_on_python_tag_mismatch,
    snapshot_python_tag,
)


def _detect_group_keys(project_root: Path) -> tuple[list[str], list[str]]:
    cfg = NormalizationConfig()
    all_units: list[dict[str, object]] = []
    all_blocks: list[dict[str, object]] = []
    registry = build_module_registry(root=project_root)

    for path in sorted(project_root.glob("*.py")):
        source = path.read_text("utf-8")
        relative_path = path.relative_to(project_root).as_posix()
        identity = registry.entries_by_path[relative_path].identity
        units, blocks, _segments, _source_stats, _file_metrics, _sf = (
            extract_units_and_stats_from_source(
                source=source,
                filepath=str(path),
                identity=identity,
                registry=registry,
                cfg=cfg,
                min_loc=1,
                min_stmt=1,
            )
        )
        all_units.extend(asdict(unit) for unit in units)
        all_blocks.extend(asdict(block) for block in blocks)

    function_group_keys = sorted(build_groups(all_units).keys())
    block_group_keys = sorted(build_block_groups(all_blocks).keys())
    return function_group_keys, block_group_keys


def test_detector_output_matches_golden_fixture() -> None:
    fixture_root = Path("tests/fixtures/golden_project").resolve()
    expected_path = fixture_root / "golden_expected_ids.json"
    expected = json.loads(expected_path.read_text("utf-8"))
    expected_python_tag = snapshot_python_tag(expected)

    # Golden fixture is a detector snapshot for one canonical Python tag.
    # Cross-version behavior is covered by contract/invariant tests.
    function_group_keys, block_group_keys = _detect_group_keys(fixture_root)
    assert_snapshot_matches_or_smoke_on_python_tag_mismatch(
        snapshot={
            "function_group_keys": function_group_keys,
            "block_group_keys": block_group_keys,
        },
        expected={
            "function_group_keys": expected["function_group_keys"],
            "block_group_keys": expected["block_group_keys"],
        },
        runtime_tag=current_python_tag(),
        expected_python_tag=expected_python_tag,
        smoke_keys=("function_group_keys", "block_group_keys"),
    )


# Block identities produced by the ccfp2 generation of this fixture, recorded
# before the fp3 cutover. Four of these survived the fp2 -> fp3 boundary
# byte-identically while the function identity moved, because only the function
# domain had been re-versioned.
_FP2_GENERATION_BLOCK_KEYS = frozenset(
    {
        "01ccd1c66f4c8f5e876fea2a8bc3fc82a8aa51233b43b8c3624bfc9465dc3b5e|5304b1e710742f760c178ef516aa82bc1bf547d49e7a152ade989df87e378843|dc8207e7a15319362749b5a7de4443c123ee69409ec5b1121d3baa8940f38ace|69b8754ff188260dc540b1b099833916dcb31593308f59fa38afb7eb7b5c1a5a",
        "5304b1e710742f760c178ef516aa82bc1bf547d49e7a152ade989df87e378843|dc8207e7a15319362749b5a7de4443c123ee69409ec5b1121d3baa8940f38ace|69b8754ff188260dc540b1b099833916dcb31593308f59fa38afb7eb7b5c1a5a|69b8754ff188260dc540b1b099833916dcb31593308f59fa38afb7eb7b5c1a5a",
        "69b8754ff188260dc540b1b099833916dcb31593308f59fa38afb7eb7b5c1a5a|d9c14d6771d6cdac8bfbc8028ca2654f9bf521a821d9d6991028a07b44c656b2|fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7|fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7",
        "8b40de5d6bdb615fbd2056321dbf218a25778479d6aa291ae9d50eb5567b5a3b|9ba1f215b1cc70e1e44775ffa9b63a323472fb200c49bc06e36d3196bab89b10|42a00f2bba529ae118f6ff9e5356ed707085d43847f99a55f4ee2876d2fca059|42a00f2bba529ae118f6ff9e5356ed707085d43847f99a55f4ee2876d2fca059",
        "9ba1f215b1cc70e1e44775ffa9b63a323472fb200c49bc06e36d3196bab89b10|42a00f2bba529ae118f6ff9e5356ed707085d43847f99a55f4ee2876d2fca059|42a00f2bba529ae118f6ff9e5356ed707085d43847f99a55f4ee2876d2fca059|01ccd1c66f4c8f5e876fea2a8bc3fc82a8aa51233b43b8c3624bfc9465dc3b5e",
        "fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7|fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7|fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7|ba26c2268997cfb0152884e5fc1e1cff216fcc0138fd3487c80573b64dcd0823",
        "fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7|fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7|fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7|fd791573aff114d8bedaefc33ee95898c2dc5c5e39feeab7a1255f059a241cc7",
    }
)


def test_block_identities_do_not_survive_a_fingerprint_generation() -> None:
    """No block identity may be reused across a fingerprint generation.

    A block key is published identity: it names a clone group in the
    ``clones.blocks`` lane of every baseline. The fingerprint contract requires
    the digest itself to be domain-separated rather than only metadata-gated,
    precisely so that content the new normalization did not move cannot produce
    a digest an older generation already used to mean something else.

    This is the guard the fn-only cutover lacked. It is recorded as concrete
    historical values rather than a recomputation, because the point is that
    THESE bytes, which a real fp2 baseline can contain, must never be minted
    again by this generation.
    """

    _, block_keys = _detect_group_keys(Path("tests/fixtures/golden_project").resolve())

    collisions = _FP2_GENERATION_BLOCK_KEYS.intersection(block_keys)
    assert not collisions, (
        f"{len(collisions)} block identities are byte-identical to the ccfp2 "
        f"generation; the block statement domain did not move with the "
        f"fingerprint version"
    )
