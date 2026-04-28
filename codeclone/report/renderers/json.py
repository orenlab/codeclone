# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping

import orjson


def render_json_report_document(payload: Mapping[str, object]) -> str:
    return orjson.dumps(payload, option=orjson.OPT_INDENT_2).decode("utf-8")


__all__ = ["render_json_report_document"]
