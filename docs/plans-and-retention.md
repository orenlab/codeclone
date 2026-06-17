<!-- doc-scope: PLANS, EDITIONS, AND DATA RETENTION.
     owns: Community/Team/Enterprise edition definitions, retention policy.
     does-not-own: config keys (→ book/10), change controller internals (→ book/12).
     rule: cross-link to contracts, do not restate them. -->

# Plans and Retention

CodeClone is open source and runs **fully locally**. Every edition — including
open source — ships the complete analysis, change-control, memory, and
integration product; nothing that runs on your machine is paywalled or
edition-capped. Team and Enterprise add **support and managed/hosted services**
on top of the same local core. Hosted capabilities are in development and are
marked **roadmap** below.

---

## What every edition includes (open source)

**The full local product is open source (MPL-2.0) and free.** No analysis,
change-control, memory, or integration capability is gated.

- **Structural analysis & CI** — clones, complexity, coupling, cohesion, dead
  code, dependency cycles, [Health Score](book/15-health-score.md), and
  baseline-aware [quality gates](book/16-metrics-and-quality-gates.md).
- **Report surfaces** — canonical JSON, HTML, Markdown, text, and
  [SARIF](guide/integrations/sarif/export.md), plus the
  [GitHub Action](getting-started.md#github-action) (gating, SARIF upload, PR comments).
- **Report-only signals** — Security Surfaces, Overloaded Modules, API-surface
  inventory with breaking-change detection, and external Coverage Join.
- **Structural Change Controller** — intent → blast radius → bounded edit →
  patch verify → receipt, with Patch Trail and multi-agent coordination
  ([change control](book/12-structural-change-controller/index.md)).
- **Live Implementation Context** — bounded structural, call-graph, and contract evidence.
- **Engineering Memory** — typed evidence-linked facts, FTS + local `fastembed`
  semantic search, Trajectory Memory, quality passports, anomaly detection, and
  the [Experience Layer](book/13-engineering-memory/experience-layer.md).
- **Corpus Analytics** — offline clustering of change-control intents (`codeclone[analytics]`).
- **33 MCP tools and native integrations** — VS Code, Cursor, Claude Code,
  Codex, and Claude Desktop on one canonical analysis.
- **Platform Observability** — opt-in local runtime diagnostics.

Local storage (intent registry, audit trail, Engineering Memory) is SQLite/file
and **configurable without an edition cap** — retention windows are plain
`[tool.codeclone]` settings, not license-gated.

---

## Editions

| Capability                                                  | Community (OSS) | Team           | Enterprise      |
|-------------------------------------------------------------|-----------------|----------------|-----------------|
| Full local analysis, change control, memory, integrations   | full            | full           | full            |
| Local semantic search (`fastembed`)                         | full            | full           | full            |
| Local retention (registry / audit / memory)                 | configurable    | configurable   | configurable    |
| Support                                                     | community       | priority + SLA | dedicated + SLA |
| Managed control plane (hosted registry / audit / retention) | —               | roadmap        | roadmap         |
| Hosted embedding / retrieval service                        | —               | roadmap        | roadmap         |
| Cross-repo / org-wide trajectory & analytics dashboards     | —               | roadmap        | roadmap         |
| Managed PostgreSQL backends                                 | —               | —              | roadmap         |
| On-prem embedding model (`local_model`)                     | —               | —              | roadmap         |

!!! note "Roadmap items are not yet available"
    Today CodeClone ships as a single open-source build. Selecting an unbuilt
    provider or backend (`api`, `local_model`, PostgreSQL) returns a
    "not available yet" error. Team and Enterprise are available now as
    **support and licensing** tiers; managed/hosted services are in development.
    [Contact us](#contact) to shape priorities.

---

## Retention (local, configurable)

The intent registry, audit trail, and Engineering Memory store data locally in
SQLite. Retention windows are configured in `[tool.codeclone]` and are **not
capped by edition** — full key reference in
[Config and Defaults](book/10-config-and-defaults.md).

| Store                         | Key                              | Default |
|-------------------------------|----------------------------------|---------|
| Intent registry (closed rows) | `intent_registry_retention_days` | `14`    |
| Audit trail                   | `audit_retention_days`           | `30`    |
| Memory drafts                 | `draft_retention_days`           | `14`    |

You can already set any local window you need. Longer **managed** retention —
central storage, backup, compliance attestations, and cross-session forensics —
is the roadmap Team/Enterprise value.

---

## Semantic retrieval providers

| Provider      | Status                   | What it is                                                                                                 |
|---------------|--------------------------|------------------------------------------------------------------------------------------------------------|
| `diagnostic`  | available                | Deterministic hash vectors. For tests, not real recall.                                                    |
| `fastembed`   | available (all editions) | Local `BAAI/bge-small-en-v1.5` via FastEmbed. No network, no API key. Install `codeclone[semantic-local]`. |
| `api`         | roadmap                  | Hosted embedding / retrieval service. Currently returns "not available yet".                               |
| `local_model` | roadmap                  | On-prem custom embedding model for air-gapped deployments. Currently returns "not available yet".          |

Open source already includes **full local semantic search** with `fastembed` —
no functionality is removed. Hosted and on-prem providers are in development.

---

## Audit trail

The controller audit trail records intent lifecycle, lease transitions, and
workspace coordination in a local SQLite database when `audit_enabled=true` in
effective config. CLI display uses `--audit` / `--audit-json`. Payload mode
(`audit_payloads`) is `off` / `compact` / `full`; retention
(`audit_retention_days`, default `30`) is configurable. Managed/hosted audit
storage is a roadmap Team/Enterprise option.

---

## Platform Observability

Platform Observability is a development diagnostic store — not controller audit
retention and not repository quality history. It is disabled by default and
local in every edition; operators own the lifecycle of
`.codeclone/db/platform_observability.sqlite3`. The observer stores no raw
MCP/prompt bodies and never contributes findings, gates, baselines, memory
facts, or edit authorization. See
[Platform Observability](book/26-platform-observability.md).

---

## Team and Enterprise

**Available now** — priority/dedicated support, SLA, and onboarding for MCP,
VS Code, and controller workflows, plus help with CI gating and rollout.

**In development (roadmap)** — a managed control plane: hosted registry / audit
/ retention, cross-repo and org-wide dashboards, hosted and on-prem embedding
providers, and PostgreSQL backends.

The open-source contracts (integrity-protected intents, signed memory payloads,
deterministic reports) are identical across editions. Managed options add
operation and scale; they never weaken validation.

## Contact

For support tiers, roadmap timelines, managed-service interest, or compliance
requirements:

**[sudo@secuapp.ru](mailto:sudo@secuapp.ru)**

## Related configuration

See [Config and Defaults](book/10-config-and-defaults.md) and
[Structural Change Controller — intent registry](book/12-structural-change-controller/index.md).

```toml
[tool.codeclone]
intent_registry_backend = "sqlite"
intent_registry_path = ".codeclone/db/intents.sqlite3"
intent_registry_retention_days = 14   # default; any positive value, no edition cap

[tool.codeclone.memory]
max_records = 10000
max_candidates = 1000
draft_retention_days = 14

[tool.codeclone.memory.semantic]
enabled = true
embedding_provider = "fastembed"      # "diagnostic" or "fastembed" today; "api" / "local_model" are roadmap
allow_model_download = true
```

Environment overrides:
[Config and Defaults — environment variable overrides](book/10-config-and-defaults.md#environment-variable-overrides).
