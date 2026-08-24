"""Two clone-eligible units that share nothing any tier could group.

The pair is deliberately dissimilar in every tier's own terms: their
normalized statement sequences differ by far more than one edit (no
near-miss pair), and their ordinal-canonical digests differ (no
renamed-structure group). An opt-in run over this tree therefore completes
with an empty result in both advisory channels — the ``complete``/``count=0``
half of the tier-state fixture base. The disabled half runs over the same
tree with the flags off.
"""


def summarize_ledger(rows: list[int]) -> int:
    total = 0
    seen = []
    for row in rows:
        total += row
        seen.append(row * 2)
    if not seen:
        return 0
    return total + len(seen)


def render_banner(width: int) -> str:
    header = "=" * width
    lines = [header]
    body = "codeclone".center(width)
    lines.append(body)
    lines.append(header)
    caption = "|".join(lines)
    return caption.strip()
