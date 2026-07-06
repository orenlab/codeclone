---
title: "Engineering Memory"
audience: public
doc_type: concept
status: draft
source_commit: "582228177b2f57d9b9823ff1da9b6a0620f1297f"
---

## What it is

Engineering Memory is CodeClone's durable knowledge store for repository insights and workflow decisions. It persists evidence-linked facts across analysis runs, AI agent sessions, and developer workflows in a local SQLite database, and survives process exits and restarts.

It holds four kinds of evidence: **records** (architecture decisions, change rationales, contract notes, risk notes), **experiences** (episodic patterns distilled from past workflow trajectories), **trajectories** (timestamped audit trails of agent actions), and a **semantic index** over records and experiences for retrieval.

## Why it exists

An AI agent session is ephemeral — a new session, a context-window reset, or a new MCP process all start with no memory of what a previous session learned. Without a durable store, hard-won context (a non-obvious root cause, a workaround for a stale contract, a decision that was already litigated) is lost and gets rediscovered at cost, or worse, silently contradicted. Chat transcripts are not a substitute: they are ephemeral and not queryable by a future agent working on the same file. Engineering Memory exists to make that knowledge durable, evidence-linked, and scoped to the files it's actually relevant to.

## How it fits together

| Lane | What it captures | Authority |
|------|--------------------|-----------|
| Records | Asserted knowledge (decisions, rationale, risks) | Human-approved before treated as established |
| Experiences | Advisory patterns distilled from many past trajectories | Advisory, not a fact about the current code |
| Trajectories | Episodic evidence of what agents actually did | Evidence, not authorization |

Memory is retrieved mid-workflow, after [controlled change](controlled-change.md) has declared an edit scope, and is filtered to that scope rather than the whole repository. Writing new records happens through the same MCP surface, not by asserting things in chat. Draft records require human approval (via the CodeClone VS Code Memory view) before being treated as established facts — memory cannot authorize edits, expand scope, or override structural findings on its own.

```mermaid
graph LR
    A["Controlled change scope declared"] --> B["Retrieve relevant memory"]
    B --> C["Records / Experiences / Trajectories"]
    C --> D["Edit with context"]
    D --> E["Write new records if warranted"]
```

## Related pages

- [Engineering Memory workflow](../guides/engineering-memory-workflow.md) — the concrete retrieval and write commands
- [Controlled change](controlled-change.md) — where memory retrieval fits in the edit lifecycle
