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

Memory tools fail until the store exists. **Bootstrap is human/CI**, not MCP:

```bash
codeclone memory init --root /abs/repo
codeclone memory init --root /abs/repo --refresh   # after major repo changes
```

If MCP returns "database not found", ask the user to init — do not invent memory
from local files or CLI report dumps.

## When to read

| Moment                           | Tool                       | Parameters                                                  |
|----------------------------------|----------------------------|-------------------------------------------------------------|
| After `start`, before first edit | `get_relevant_memory`      | `scope` or `intent_id` from active intent                   |
| One file deep-dive               | `query_engineering_memory` | `mode=for_path`, `path`                                     |
| Symbol context                   | `query_engineering_memory` | `mode=for_symbol`, `symbol`                                 |
| Keyword discovery                | `query_engineering_memory` | `mode=search`, `query`, `filters={match_mode:"any"\|"all"}` |
| Store health                     | `query_engineering_memory` | `mode=status`                                               |
| Stale inventory                  | `query_engineering_memory` | `mode=stale`                                                |

Defaults exclude **stale** and **draft**. Pass `include_stale=true` only for
diagnostics.

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
| Atomic fallback                 | `manage_engineering_memory(action=propose_from_receipt, text=…, intent_id?)`                | When finish hook unavailable |

### Write rules

- Agents **never** approve, reject, or archive via MCP
- Ask user to run `codeclone memory approve RECORD_ID` to promote drafts
- Ask user to run `codeclone memory init --refresh` when system facts drift
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
- Missing memory DB (init required)
- Draft candidate should become team policy (approve needed)
- System facts outdated after large refactor (refresh needed)
