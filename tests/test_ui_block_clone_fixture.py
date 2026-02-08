"""
Temporary manual fixture for HTML explainability demo.

This module intentionally contains repetitive assert-only functions so that
CodeClone reports a deterministic block clone with assert-only hints.
It is safe to delete after visual verification.
"""

from __future__ import annotations


def fixture_block_clone_case_one(html: str) -> None:
    if not html:
        raise ValueError("case_one requires non-empty html")

    assert "m01" in html
    assert "m02" in html
    assert "m03" in html
    assert "m04" in html
    assert "m05" in html
    assert "m06" in html
    assert "m07" in html
    assert "m08" in html
    assert "m09" in html
    assert "m10" in html
    assert "m11" in html
    assert "m12" in html
    assert "m13" in html
    assert "m14" in html
    assert "m15" in html
    assert "m16" in html
    assert "m17" in html
    assert "m18" in html
    assert "m19" in html
    assert "m20" in html
    assert "m21" in html
    assert "m22" in html
    assert "m23" in html
    assert "m24" in html
    assert "m25" in html
    assert "m26" in html
    assert "m27" in html
    assert "m28" in html
    assert "m29" in html
    assert "m30" in html
    assert "m31" in html
    assert "m32" in html
    assert "m33" in html
    assert "m34" in html
    assert "m35" in html
    assert "m36" in html

    assert html.startswith("<")


def fixture_block_clone_case_two(html: str) -> None:
    marker = len(html)
    assert marker >= 0

    assert "m01" in html
    assert "m02" in html
    assert "m03" in html
    assert "m04" in html
    assert "m05" in html
    assert "m06" in html
    assert "m07" in html
    assert "m08" in html
    assert "m09" in html
    assert "m10" in html
    assert "m11" in html
    assert "m12" in html
    assert "m13" in html
    assert "m14" in html
    assert "m15" in html
    assert "m16" in html
    assert "m17" in html
    assert "m18" in html
    assert "m19" in html
    assert "m20" in html
    assert "m21" in html
    assert "m22" in html
    assert "m23" in html
    assert "m24" in html
    assert "m25" in html
    assert "m26" in html
    assert "m27" in html
    assert "m28" in html
    assert "m29" in html
    assert "m30" in html
    assert "m31" in html
    assert "m32" in html
    assert "m33" in html
    assert "m34" in html
    assert "m35" in html
    assert "m36" in html

    assert html.endswith(">")
