<!-- doc-scope: PLANS, PRICING TIERS, AND DATA RETENTION.
     owns: OSS/Team/Enterprise tier definitions, retention policy.
     does-not-own: config keys (→ book/10), change controller internals (→ book/12).
     rule: cross-link to contracts, do not restate them. -->

# Plans and Retention

CodeClone is open source and runs locally. Some coordination, audit, and
semantic retrieval features have edition-specific limits. This page describes
the three editions, their feature boundaries, and how to reach the team for
Team or Enterprise options.

---

## Edition overview

| Capability                          | Open Source     | Team                                    | Enterprise                          |
|-------------------------------------|-----------------|-----------------------------------------|-------------------------------------|
| **Core analysis and CI gating**     | full            | full                                    | full                                |
| **Change controller**               | full            | full                                    | full                                |
| **Engineering Memory**              | full            | full                                    | full                                |
| **Semantic search — local**         | `fastembed`     | `fastembed`                             | `fastembed`                         |
| **Semantic search — API providers** | —               | OpenAI, Cohere, Voyage, custom endpoint | all Team + on-prem `local_model`    |
| **Memory record limit**             | 10 000          | 50 000                                  | configurable                        |
| **Memory draft retention**          | 14 days         | 30 days                                 | configurable                        |
| **Memory archived retention**       | 365 days        | 730 days                                | configurable                        |
| **Intent registry retention**       | 7 days (max 14) | up to 30 days                           | up to 90 days                       |
| **Intent registry backend**         | SQLite (local)  | SQLite or managed                       | PostgreSQL (managed or self-hosted) |
| **Audit trail retention**           | 30 days         | 90 days                                 | configurable                        |
| **Audit payloads**                  | compact         | compact or full                         | compact or full                     |
| **Support**                         | community       | priority onboarding + premium           | dedicated + SLA                     |

---

## Workspace intent registry retention

When `intent_registry_backend = "sqlite"`, closed workspace intents (`clean`,
`expired`, `orphaned`) are kept for audit and purged only after
`intent_registry_retention_days`. The open-source edition enforces these limits
at configuration time.

| Edition     | Default retention | Maximum retention | Intent registry backend                    |
|-------------|-------------------|-------------------|--------------------------------------------|
| Open source | 7 days            | 14 days           | SQLite (local file under `.codeclone/db/`) |
| Team        | configurable      | up to 30 days     | SQLite or managed deployment               |
| Enterprise  | configurable      | up to 90 days     | PostgreSQL (managed or self-hosted)        |

Values above **14 days** in `[tool.codeclone]` on the open-source edition return a
contract error and point here.

## Engineering Memory

Engineering Memory stores evidence-linked repository facts — contracts,
decisions, risk hotspots, agent drafts, git provenance. The store runs locally
on SQLite and is governed through the VS Code Memory view.

### Retention

| Record status | Open Source | Team      | Enterprise   |
|---------------|-------------|-----------|--------------|
| active        | unlimited   | unlimited | unlimited    |
| draft         | 14 days     | 30 days   | configurable |
| stale         | 180 days    | 365 days  | configurable |
| rejected      | 30 days     | 90 days   | configurable |
| archived      | 365 days    | 730 days  | configurable |
| receipt       | 90 days     | 180 days  | configurable |

### Record and candidate limits

| Limit                             | Open Source | Team   | Enterprise   |
|-----------------------------------|-------------|--------|--------------|
| `max_records`                     | 10 000      | 50 000 | configurable |
| `max_candidates` (pending drafts) | 1 000       | 5 000  | configurable |

### Semantic retrieval providers

Semantic search blends LanceDB vector proximity with FTS keyword recall for
meaning-oriented memory retrieval. The embedding provider determines retrieval
quality.

| Provider      | Edition          | What it is                                                                                                                     |
|---------------|------------------|--------------------------------------------------------------------------------------------------------------------------------|
| `diagnostic`  | all              | Deterministic hash-based vectors. Useful for tests, not for real recall.                                                       |
| `fastembed`   | all              | Local `BAAI/bge-small-en-v1.5` via FastEmbed. No network, no API key. Install `codeclone[semantic-local]`.                     |
| `api`         | Team, Enterprise | External embedding API (OpenAI, Cohere, Voyage, or a custom endpoint). Requires API key in `[tool.codeclone.memory.semantic]`. |
| `local_model` | Enterprise       | Custom on-premise embedding model. For air-gapped deployments or proprietary models.                                           |

Open-source users get full local semantic search with `fastembed` — no
functionality is removed. API and custom-model providers add options for teams
that prefer hosted embedding quality or need on-prem model compliance.

## Audit trail

The controller audit trail records passive events (intent lifecycle, lease
transitions, workspace coordination) in a local SQLite database when
`--audit-enabled` is set.

| Setting                | Open Source  | Team            | Enterprise           |
|------------------------|--------------|-----------------|----------------------|
| `audit_retention_days` | 30           | 90              | configurable         |
| `audit_payloads`       | compact      | compact or full | compact or full      |
| Audit backend          | local SQLite | local SQLite    | SQLite or PostgreSQL |

Full payloads include complete tool request/response metadata; compact payloads
include event type, timestamps, and identifiers only.

## Why longer retention matters

The SQLite intent registry and audit trail are **auditable coordination trails**:
who declared change intent, when leases expired, how workspace conflicts were
resolved, and what agent sessions produced. Longer retention helps:

- post-incident review across agent sessions and CI runs;
- compliance and internal audit without exporting ad hoc JSON files;
- multi-agent forensics when several tools share one repository;
- Engineering Memory lifecycle visibility (draft → active → stale → archived).

File-based registry (`intent_registry_backend = "file"`) remains ephemeral by
design; SQLite is the audit-oriented backend.

---

## Team plan

Team is for engineering groups that need longer local retention, API-powered
semantic search, and priority support — without operating their own database
tier.

**Includes:**

- workspace intent retention up to **30 days**;
- Engineering Memory: **50 000** records, **30-day** draft retention,
  **730-day** archived retention;
- semantic search via **API embedding providers** (OpenAI, Cohere, Voyage,
  custom endpoint);
- audit trail retention up to **90 days** with optional full payloads;
- priority onboarding for MCP, VS Code, and controller workflows;
- **premium support** for integration, CI gating, and upgrade questions;
- optional assisted rollout of SQLite registry and audit trail in shared
  workspaces.

Team keeps the same integrity-protected intent and memory payload contracts as
open source; limits are raised through licensed configuration, not by weakening
validation.

## Enterprise plan

Enterprise is for organizations that need centralized retention, PostgreSQL,
on-prem embedding models, and operational support.

**Includes everything in Team, plus:**

- workspace intent retention up to **90 days**;
- Engineering Memory: **configurable** record limits and retention;
- semantic search via **on-premise custom models** (`local_model` provider)
  for air-gapped or compliance-sensitive deployments;
- **PostgreSQL backend** for the intent registry (high availability, backup,
  and query from existing ops tooling);
- audit trail with **configurable** retention and full payload mode;
- **premium support** with agreed response targets;
- deployment guidance for air-gapped, multi-repo, or CI-controller topologies;
- optional alignment with internal security and change-management processes.

PostgreSQL is an Enterprise backend; open source and Team continue to use the
local SQLite registry unless you adopt Enterprise licensing.

---

## Contact

For Team or Enterprise pricing, retention entitlements, API provider setup,
PostgreSQL rollout, or premium support details:

**[sudo@secuapp.ru](mailto:sudo@secuapp.ru)**

## Related configuration

See [Config and Defaults — workspace intent registry](book/10-config-and-defaults.md)
and [Structural Change Controller — workspace intent registry](book/12-structural-change-controller/index.md).

Open-source keys:

```toml
[tool.codeclone]
intent_registry_backend = "sqlite"
intent_registry_path = ".codeclone/db/intents.sqlite3"
intent_registry_retention_days = 7   # max 14 in open source

[tool.codeclone.memory]
max_records = 10000
max_candidates = 1000
draft_retention_days = 14

[tool.codeclone.memory.semantic]
enabled = true
embedding_provider = "fastembed"      # or "api" (Team+), "local_model" (Enterprise)
# api_key = "..."                     # required for api provider
# api_base = "https://..."            # optional custom endpoint
allow_model_download = true
```

Environment overrides for registry and memory fields:
[10-config Environment variable overrides](book/10-config-and-defaults.md#environment-variable-overrides).
