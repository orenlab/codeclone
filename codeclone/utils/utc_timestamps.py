# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from datetime import datetime, timezone


def age_seconds_since_utc_timestamp(timestamp: str | None) -> int | None:
    """Return whole seconds elapsed since an ISO-8601 UTC timestamp."""

    if timestamp is None:
        return None
    text = timestamp.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        created = datetime.fromisoformat(text)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds()))


__all__ = ["age_seconds_since_utc_timestamp"]
