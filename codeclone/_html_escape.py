"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import html
from typing import Any


def _escape_html(v: Any) -> str:
    text = html.escape("" if v is None else str(v), quote=True)
    text = text.replace("`", "&#96;")
    text = text.replace("\u2028", "&#8232;").replace("\u2029", "&#8233;")
    return text


def _escape_attr(v: Any) -> str:
    text = html.escape("" if v is None else str(v), quote=True)
    text = text.replace("`", "&#96;")
    text = text.replace("\u2028", "&#8232;").replace("\u2029", "&#8233;")
    return text


def _meta_display(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "n/a"
    text = str(v).strip()
    return text if text else "n/a"
