## MCP Payload Token Budget

The optional controller audit trail can estimate the token footprint of MCP
payloads returned to the agent. This is a deterministic estimate of how much
context window each tool response consumes, not actual model billing tokens.

### Setup

Token estimation requires two conditions:

1. Audit trail enabled (`audit_enabled = true` in `pyproject.toml`).
2. The `codeclone[token-bench]` optional extra installed (provides `tiktoken`).

Without `tiktoken`, the estimator falls back to a character-based approximation
(`ceil(characters / 4)`). Without audit enabled, no estimation runs.

### How it works

The estimation runs inside the audit writer's `event_to_row`, not in the MCP
tool call path. The MCP session has zero overhead when audit is disabled or
when `tiktoken` is not installed.

Each audit event row includes three optional fields:

- `estimated_tokens` — BPE token count (or character-based approximation).
- `token_encoding` — encoding name (`o200k_base` or `chars_approx`).
- `payload_characters` — character count of the canonical JSON payload.

The estimation input is the full original payload (what the MCP client
receives), not the compact audit storage form.

With `audit_payloads=compact`, stored JSON drops large structured fields, but
`intent.declared` keeps bounded `intent_description`. The SQLite `summary` column
always stores a short essence via `event_summary()`, independent of payload mode.

### CLI visibility

The `--audit` Rich TUI renderer shows token columns when data is available:

```
Tokens  Encoding      Event
  412   o200k_base    intent.declared
  890   o200k_base    blast_radius.computed
 1204   o200k_base    patch_contract.verified
```

The `--session-stats` command appends a summary line when audit token data
exists:

```
MCP payload footprint: ~3,816 tokens (o200k_base, 7 tool calls)
```

### Invariants

- Token estimation never affects controller decisions, gate results, report
  digests, or baseline trust.
- Any exception in the estimation path results in `NULL` values, not a failed
  audit event write.
- The `codeclone/budget/` module never imports from `codeclone/surfaces/` or
  `codeclone/audit/`. Dependency direction: `audit -> budget`, never reverse.
- Base `codeclone` never depends on `tiktoken`. The import is lazy and guarded.
