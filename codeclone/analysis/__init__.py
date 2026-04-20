# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from .cfg import CFG, CFGBuilder
from .fingerprint import bucket_loc, sha1
from .normalizer import AstNormalizer, NormalizationConfig, stmt_hashes


def __getattr__(name: str) -> object:
    if name == "extract_units_and_stats_from_source":
        from .units import extract_units_and_stats_from_source

        return extract_units_and_stats_from_source
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CFG",
    "AstNormalizer",
    "CFGBuilder",
    "NormalizationConfig",
    "bucket_loc",
    "extract_units_and_stats_from_source",
    "sha1",
    "stmt_hashes",
]
