---
title: "Inline suppressions"
audience: public
doc_type: reference
status: published
source_commit: "60eac9c367d74deeba1478521461addfedd8e681"
---

# Inline suppressions

CodeClone supports **explicit inline suppressions** for a small set of findings.
A suppression is local policy — an accepted, reviewed exception — not analysis
truth. Keep suppressions narrow and declaration-scoped; never use them to hide
broad classes of debt.

## Syntax

A suppression is a comment directive of the form:

```python
# codeclone: ignore[<rule-id>[, <rule-id> ...]]
```

- The marker literal is `codeclone:` — comments without it are ignored by the parser.
- Rule IDs go inside `[ ... ]`, comma-separated.
- Whitespace around `codeclone`, `:`, `ignore`, and the brackets is tolerated.
- Unknown or malformed rule IDs inside the brackets are silently dropped (only
  supported IDs take effect).

## Supported rule IDs

| Rule ID | Suppresses |
|---------|------------|
| `dead-code` | Dead-code (unused declaration) findings |
| `clone-cohort-drift` | Clone cohort-drift findings |
| `clone-guard-exit-divergence` | Clone guard/exit-divergence findings |

Rule IDs are lowercase, `[a-z0-9]` with internal hyphens allowed.

## Placement and binding

A suppression is **declaration-scoped**. It binds to the nearest `def`,
`async def`, or `class` declaration (function, method, or class). Two placements
are supported:

- **Leading** — on the line immediately above the declaration:

  ```python
  # codeclone: ignore[dead-code]
  def legacy_entrypoint() -> None:
      ...
  ```

- **Inline** — as a trailing comment on the declaration/header line:

  ```python
  def legacy_entrypoint() -> None:  # codeclone: ignore[dead-code]
      ...
  ```

Suppressions are **target-specific**: they apply only to the bound declaration.
They do not cascade to nested declarations and are not file-wide.

## When to use them

Use a suppression for an accepted dynamic or runtime false positive — for
example, a function that is only referenced through a plugin registry or reflective
dispatch that CodeClone cannot see statically. Do not use suppressions to silence
a broad class of findings; adjust configuration thresholds or fix the underlying
structure instead.

## Related

- [Configuration reference](configuration.md) — thresholds and gates
- [Reports](reports.md) and [JSON output](json-output.md) — how findings are reported
- MCP help: `help(topic="suppressions")`
