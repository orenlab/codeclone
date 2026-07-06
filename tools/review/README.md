# CodeClone Review Kit (v3)

Maintainer-only internal tooling under `tools/review/`. It is **not** part of the
published `codeclone` PyPI wheel — only `codeclone.*` ships to users.

Run `scripts/install_review_kit.sh` to symlink shell, policy, and agent assets
into `.claude/` for local Claude Code discovery. Python sources stay under
`tools/review/review_kit/` only (no `.py` symlinks in `.claude/`).

The `review-change` skill is not part of this kit: it lives natively (and
untracked) under `.claude/skills/review-change/SKILL.md`, so the installer does
not manage it.

## Monorepo development

| Surface | How `review_kit` is resolved |
|---------|------------------------------|
| `pytest` | `[tool.pytest.ini_options] pythonpath = ["tools/review"]` |
| `review-change.sh` | `PYTHONPATH=$REPO_ROOT/tools/review` |
| `build_review_packet.py` / `check_surface_coverage.py` | local `sys.path` bootstrap |

## Quick start

```bash
tools/review/review-change.sh --range BASE..HEAD --dry-run
tools/review/review-change.sh --range BASE..HEAD --validate --yes
scripts/install_review_kit.sh
```

## Entry points

```bash
uv run python tools/review/build_review_packet.py range 'BASE..HEAD' --out /tmp/packet.json
uv run python tools/review/check_surface_coverage.py
PYTHONPATH=tools/review uv run python -m review_kit.cli build-packet range 'BASE..HEAD' --out /tmp/packet.json --validate
```

Packet v3 provides deterministic `review_units[]`, routing, incremental reuse,
verification plan/results, and `cost_estimate`.
