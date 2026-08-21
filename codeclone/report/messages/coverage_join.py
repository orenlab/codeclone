# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Coverage Join section copy."""

from __future__ import annotations

from typing import Final

#: The HTML ring's absence sentence for a coverage join that never ran.
#: One owner for the wording: the coverage-join panel states it and the
#: quality insight repeats it, so a divergent respelling in either site
#: is a defect, not a nuance.
COVERAGE_JOIN_UNAVAILABLE: Final = "Coverage Join is unavailable for this run."
