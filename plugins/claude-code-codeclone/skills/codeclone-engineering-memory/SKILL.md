---
name: codeclone-engineering-memory
description: CodeClone Engineering Memory via MCP — scope evidence before edits, search, draft writes, finish proposals, and the human-only approve boundary.
---

# CodeClone Engineering Memory

Local SQLite store of evidence-linked repository facts. Chat is ephemeral — anything
the next agent must remember goes here via MCP, never "I noted it in the summary".

## In the edit cycle (mandatory step 3)

After `start_controlled_change` returns `edit_allowed:true`:

1. `get_relevant_memory(root=<abs>, intent_id=... or scope=...)` — `root` is REQUIRED; `intent_id` alone fails MCP
   validation.
2. Read contract warnings, stale decisions, `contradiction_note` alerts. Surface contradictions to the user before
   editing.
3. Drill down: `query_engineering_memory(mode=for_path | search | get)`.

## Writing (agents draft only)

- During a cycle, on a stable observation or any incident / complexity / decision:
  `manage_engineering_memory(action=record_candidate, record_type=risk_note|change_rationale, statement="<what happened / learned / do next>", subject_path="<repo-relative file>")`.
- After an accepted patch: `finish_controlled_change(..., propose_memory=true)` → `memory_candidates`.
- Before `finish`: if the cycle had an incident / complexity / decision, you MUST `record_candidate` first. Chat
  summaries do not count.

## Hard boundaries

- Agents CANNOT `approve` / `reject` / `archive`. Only a human, via the VS Code Memory view (not MCP, not
  `codeclone memory approve`).
- Memory NEVER authorizes edits, expands scope, or overrides findings.
- Do NOT treat `draft` / `inferred` / stale records as established fact. Do not ignore stale warnings.
- Never use the repo root as memory scope. Compress each statement to one durable fact (target ≤300 chars).

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                      | Meaning                                                                         |
|--------------------------------------------|---------------------------------------------------------------------------------|
| `records` / `trajectories` / `experiences` | separate evidence lanes: asserted facts / episodic workflow / advisory patterns |
| `relevance_score`                          | lane-LOCAL — never compare across lanes; `for_path` / plain search are unranked |
| record `status`                            | draft (unverified) / active / stale / historical / rejected                     |
| record `approved`                          | human-approved? draft + inferred are non-authoritative                          |
| `contradiction_note`                       | conflicting records for your scope — surface before editing                     |
| `coverage`                                 | visibility metadata, NOT correctness or approval                                |
| `subjects_truncated`                       | more subjects exist — use `mode=get` / `detail_level=full`                      |

## Non-goals

- Do not approve / reject via MCP. Do not treat chat as memory. Do not let memory override a finding or grant an edit.
