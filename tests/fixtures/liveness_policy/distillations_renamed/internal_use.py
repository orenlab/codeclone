"""Rename twin of ``distillations/internal_use.py``.

Same structure, every identifier renamed: the sibling import that references
the non-re-exported adapter, so the export-root rule is proven to be the
declared predicate rather than a match on the original fixture's names.
"""

from .api import ConcealedAdapter


def apply_adapter() -> ConcealedAdapter:
    return ConcealedAdapter()
