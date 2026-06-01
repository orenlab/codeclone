---
name: codeclone-engineering-memory
description: Use CodeClone Engineering Memory via MCP — scope context before edits, FTS search, draft writes, finish proposals, and human approve boundaries.
---

# CodeClone Engineering Memory

Local SQLite store of evidence-linked repository facts. Complements change
control — does **not** replace analysis, blast radius, or patch verify.

Full contract: `docs/book/26-engineering-memory.md`. MCP help:
`help(topic="engineering_memory")`.

## Prerequisites

Default `mcp_sync_policy=bootstrap_if_missing` auto-creates the store from the
latest MCP analysis run on first `get_relevant_memory` after `analyze_repository`.

| Need | Tool |
|------|------|
| Auto bootstrap (default) | `analyze_repository` → `get_relevant_memory` |
| Explicit refresh | `manage_engineering_memory(action=refresh_from_run, run_id?)` |
| CI / offline bootstrap | `codeclone memory init [--refresh]` |

If policy is `off` or no MCP run exists and the DB is missing, call
`refresh_from_run` after `analyze_repository` or ask the user to run CLI init.
Do not invent memory from local files or report dumps.

## When to read

| Moment                           | Tool                       | Parameters                                                  |
|----------------------------------|----------------------------|-------------------------------------------------------------|
| After `start`, before first edit | `get_relevant_memory`      | `scope` or `intent_id` from active intent                   |
| One file deep-dive               | `query_engineering_memory` | `mode=for_path`, `path`                                     |
| Symbol context                   | `query_engineering_memory` | `mode=for_symbol`, `symbol`                                 |
| Keyword discovery                | `query_engineering_memory` | `mode=search`, `query`, `filters={match_mode:"any"\|"all"}` |
| Store health                     | `query_engineering_memory` | `mode=status`                                               |
| Stale inventory                  | `query_engineering_memory` | `mode=stale`                                                |

Defaults exclude **stale**. Keyword `search` excludes drafts unless
`include_drafts=true`; scoped `get_relevant_memory` and `for_path` /
`for_symbol` include draft agent notes automatically so handoffs are visible.
Draft records remain non-authoritative.

### Read checklist

1. Scan ranked records for `contract_note`, `document_link`, `risk_note`
2. Check response warnings for stale linked paths
3. If `contradiction_note` matches scope → **stop and tell the user**
4. Do not treat `draft` / `inferred` as policy

## When to write (draft only)

| Situation                       | Tool                                                                                        | Notes                        |
|---------------------------------|---------------------------------------------------------------------------------------------|------------------------------|
| Durable observation during edit | `manage_engineering_memory(action=record_candidate, record_type, statement, subject_path?)` | Creates **draft**            |
| Validate claims before finish   | `manage_engineering_memory(action=validate_claims, text=…)`                                 | Memory-layer guard           |
| Post-edit batch proposal        | `finish_controlled_change(..., propose_memory=true)`                                        | On **accept** only           |
| Refresh system facts from run   | `manage_engineering_memory(action=refresh_from_run, run_id?)`                               | Force ingest                 |
| Atomic fallback                 | `manage_engineering_memory(action=propose_from_receipt, text=…, intent_id?)`                | When finish hook unavailable |

### Write rules

- **Session chat is ephemeral** — durable notes require `record_candidate` or
  `finish(..., propose_memory=true)`; never rely on the assistant message alone.
- Before `finish_controlled_change`, if the cycle had an **incident**, **complexity**,
  or a **decision** worth remembering, write at least one `record_candidate` (see
  `change-control-gate` and `codeclone-change-control` §Incident memory).
- Agents **never** approve, reject, or archive via MCP
- Ask the user to approve drafts in the CodeClone VS Code **Memory** view (agents
  cannot approve through MCP)
- Ask user to run `codeclone memory init --refresh` when policy is `off` and facts drift
- Or call `refresh_from_run` when an MCP run is available
- Memory writes do **not** satisfy change-control scope or verify requirements

## When NOT to use memory

- Justifying `do_not_touch` path edits
- Expanding scope beyond declared intent
- Overriding CodeClone findings
- Substituting for `analyze_repository` or `get_blast_radius`
- Treating draft/stale as verified project policy

## Integration with change control

Normal edit cycle (memory steps in **bold**):

```
analyze_repository
→ start_controlled_change
→ get_relevant_memory          # after edit_allowed=true
→ edit in scope
→ analyze_repository           # when after_run required
→ record_candidate             # before finish if incident/complexity/decision
→ finish_controlled_change     # optional propose_memory=true
```

Memory context is **advisory**. Blast radius `do_not_touch` remains a hard boundary.

## Record types (common)

| Type                 | Typical source              | Agent trust               |
|----------------------|-----------------------------|---------------------------|
| `contract_note`      | init ingest                 | high when active+verified |
| `document_link`      | docs ingest                 | high when active          |
| `risk_note`          | metrics ingest              | informational             |
| `module_role`        | inventory / finish proposal | context                   |
| `change_rationale`   | finish proposal             | draft until approved      |
| `contradiction_note` | ingest conflict             | **escalate to user**      |

## Escalate to user

- `contradiction_note` in scope
- Stale warnings on previously approved records you rely on
- Missing memory DB with no MCP run (init or analyze first)
- Draft candidate should become team policy (approve needed)
- System facts outdated after large refactor (refresh needed)
