# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import html


def _escape_html(v: object) -> str:
    text = html.escape("" if v is None else str(v), quote=True)
    text = text.replace("`", "&#96;")
    text = text.replace("\u2028", "&#8232;").replace("\u2029", "&#8233;")
    return text


def _meta_display(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "n/a"
    text = str(v).strip()
    return text if text else "n/a"
