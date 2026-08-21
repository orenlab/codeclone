# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Cross-section HTML absence copy.

Absence sentences spoken by more than one section renderer. A phrase with
one owning section lives in that section's copy module; a phrase repeated
across sections lives here, so renaming it moves every site at once instead
of leaving silent inline orphans.
"""

from __future__ import annotations

from typing import Final

#: The insight-line absence sentence for a run whose metrics never ran.
#: Five section panels (quality, module map, dependencies, dead code,
#: review) state the same fact; one owner keeps the spelling from
#: drifting apart site by site.
METRICS_SKIPPED: Final = "Metrics are skipped for this run."

#: The empty-state sentence for a dependency graph that has no edges to
#: draw. The dependencies panel and the module map say it for the same
#: absent graph, so the wording has one owner.
DEPENDENCY_GRAPH_UNAVAILABLE: Final = "Dependency graph is not available."
