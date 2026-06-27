---
name: codeclone-engineering-memory
description: Use CodeClone Engineering Memory through MCP to retrieve scoped evidence before edits and preserve durable incidents, decisions, risks, contradictions, and verification anchors as draft candidates. Memory never grants edit permission; agents propose, humans govern.
---

# CodeClone Engineering Memory

Engineering Memory stores evidence-linked repository facts beyond one agent session.
Chat is ephemeral: when a future human or agent would otherwise rediscover an
important fact, preserve it through MCP.

Agents use MCP for memory operations. Do not substitute CLI output or local report
files for `get_relevant_memory` or `query_engineering_memory`.

## Mandatory after `start_controlled_change`

After `start_controlled_change` returns `edit_allowed:true`:

1. `get_relevant_memory(root=<abs>, intent_id=... or scope=...)`.
2. Read contract, stale, risk, and conflict evidence in the response.
3. `query_engineering_memory(mode=for_path | search | get)` only when drill-down
   is needed.

`root` is required (`intent_id` alone fails MCP validation).

`get_implementation_context` may include a memory facet, but it does **not** replace
this explicit retrieval step in the change-control cycle.

Repository root (`.` or empty path) is **rejected** for memory scope and
`subject_path`. Use the narrowest file or directory that still anchors the fact.

Evaluate conflicts by evidence strength:

- `relations.contradicted_by` / `superseded_by` involving **active** or
  **human-approved** records that affect the planned change → resolve against
  source or report before editing;
- **draft**, **inferred**, or **stale** conflicts → verify against source; do not
  treat them as authoritative blockers by default.

## When to write

Create a candidate only when the cycle produced a fact a future session would
otherwise rediscover the hard way:

| Category | Examples |
|----------|----------|
| **Incident** | Unexpected failure, blocked verification, hygiene problem, non-obvious recovery |
| **Complexity** | Hidden coupling, difficult root cause, interaction near a protected boundary |
| **Decision** | Non-default architectural or contract tradeoff that should not be reopened casually |
| **Contradiction** | Memory disagreed with current evidence and the resolution matters |
| **Risk** | Hidden invariant, footgun, or reusable verification/test anchor |

**Skip** trivial edits, routine reads, obvious source facts, and progress narration.

Before `finish_controlled_change`, when any category above applies, call
`record_candidate`. Chat text does not satisfy this.

At `finish_controlled_change`, `propose_memory=true` may request related **draft**
candidates from the completed cycle. Human governance still applies before they
become trusted memory.

## Write one durable fact

A `statement` must make sense **without** this chat:

- state **what** is true;
- explain **why** it matters;
- say what a future maintainer should **do**;
- name concrete paths, tools, fields, errors, or contracts;
- avoid session-local shorthand: “as discussed”, “option 2”, “the usual fix”.

**Good**

`finish_controlled_change` requires a new `after_run_id` for `python_structural`
patches; reusing the before run returns `after_run_not_new`.
Anchor: `codeclone/surfaces/mcp/_session_workflow_mixin.py`.

**Bad**

- `Fixed memory.`
- `Root required.`
- `Use option B.`

One card = one durable fact, not a session narrative.

## Statement length

| Limit | Chars | Behaviour |
|-------|-------|-----------|
| **Target** | ≤ **300** | Preferred durable-card size |
| **Soft** | ≤ **500** | Governance / `validate_claims` may warn — compress |
| **Hard** | ≤ **1000** | `record_candidate` **rejects** the statement |

Several independent facts → separate candidates with appropriate anchors. Do not
split one fact merely to bypass the hard limit.

## Draft through MCP

```
manage_engineering_memory(
  action="record_candidate",
  record_type="<appropriate-type>",
  statement="<one self-contained durable fact>",
  subject_path="<repo-relative path>",
)
```

`subject_path` is **required**. It must be a real repo-relative path, not `.` or
empty. For repository-wide decisions, anchor to the governing file
(`pyproject.toml`, a contracts module, CI config, etc.).

Use the record type that matches the fact. Common examples: `risk_note`,
`change_rationale`, `contract_note`, `test_anchor`, `architecture_decision`,
`contradiction_note`, `protocol_rule`.

Agents create **draft** candidates only. Approval, rejection, superseding, and
archival are **human-governed** actions through supported human-facing surfaces
(IDE Memory views, including JetBrains, or CLI
`codeclone memory approve|reject|archive --i-know-what-im-doing`).

Agents must **not** call `approve`, `reject`, or `archive` via MCP.

Memory never:

- grants edit permission;
- expands controlled scope;
- overrides `do_not_touch`;
- overrides canonical findings or controller outcomes.

## Read evidence correctly

| Field | Meaning |
|-------|---------|
| `records` | Asserted repository facts |
| `trajectories` | Episodic workflow evidence |
| `experiences` | Advisory patterns from prior work |
| `relevance_score` | Lane-local; do not compare across lanes |
| `status` | `draft`, `active`, `stale`, `historical`, `superseded`, `rejected`, or `archived` |
| `approved` | Whether a human governance action approved the record |
| `relations` | Linked conflicts: `contradicted_by`, `superseded_by`, `supersedes` |
| `coverage` | Visibility metadata, not correctness or approval |
| `subjects_truncated` | More subjects exist outside the bounded response |
| `context_governance.mode` | `partial_enforce` for compact scoped retrieval; `observe` for full/detail pages |

When `get_relevant_memory` includes `continuation.lanes.<lane>.page`, the cursor
is an exact continuation of that ranked lane. Use
`get_memory_projection_page(root=<abs>, cursor=...)` to inspect omitted tail
items disclosed by `context_governance.omitted`. If the memory projection
changed, the page returns `snapshot_mismatch`; do not replace that with a fresh
broad search while claiming it is the same evidence. Known object drill-downs remain:
`query_engineering_memory(mode="get")`,
`query_engineering_memory(mode="trajectory_get")`, and
`query_engineering_memory(mode="experience_get")`.

Treat `draft`, `inferred`, `stale`, `historical`, `superseded`, and `rejected`
records according to provenance and lifecycle status. Historical evidence may be
authoritative about the past but must not be assumed current.

## Non-goals

- Do not treat chat as durable memory.
- Do not record routine activity or obvious source facts.
- Do not use memory to authorize edits or weaken change-control boundaries.
- Do not let memory override canonical source, findings, reports, or controller
  evidence.
- Do not approve your own agent-generated candidates.
