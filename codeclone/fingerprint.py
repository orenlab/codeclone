from __future__ import annotations

import hashlib

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def bucket_loc(loc: int) -> str:
    # Helps avoid grouping wildly different sizes if desired
    if loc < 20:
        return "0-19"
    if loc < 50:
        return "20-49"
    if loc < 100:
        return "50-99"
    return "100+"