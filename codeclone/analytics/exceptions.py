# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations


class AnalyticsError(Exception):
    """Base error for corpus analytics."""


class AnalyticsCapabilityError(AnalyticsError):
    """Required optional dependency is not installed."""


class AnalyticsStoreError(AnalyticsError):
    """Analytics SQLite store error."""


class AnalyticsWorkflowError(AnalyticsError):
    """Orchestration or input validation error."""


__all__ = [
    "AnalyticsCapabilityError",
    "AnalyticsError",
    "AnalyticsStoreError",
    "AnalyticsWorkflowError",
]
