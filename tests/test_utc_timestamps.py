# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from codeclone.utils.utc_timestamps import age_seconds_since_utc_timestamp


def test_age_seconds_since_utc_timestamp_none_and_blank() -> None:
    assert age_seconds_since_utc_timestamp(None) is None
    assert age_seconds_since_utc_timestamp("") is None
    assert age_seconds_since_utc_timestamp("   ") is None


def test_age_seconds_since_utc_timestamp_invalid() -> None:
    assert age_seconds_since_utc_timestamp("not-a-timestamp") is None


def test_age_seconds_since_utc_timestamp_z_suffix() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=30)
    text = past.strftime("%Y-%m-%dT%H:%M:%SZ")
    age = age_seconds_since_utc_timestamp(text)
    assert age is not None
    assert 25 <= age <= 35


def test_age_seconds_since_utc_timestamp_naive_treated_as_utc() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    text = past.replace(tzinfo=None).isoformat()
    age = age_seconds_since_utc_timestamp(text)
    assert age is not None
    assert 5 <= age <= 20


def test_age_seconds_since_utc_timestamp_never_negative() -> None:
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    text = future.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    assert age_seconds_since_utc_timestamp(text) == 0
