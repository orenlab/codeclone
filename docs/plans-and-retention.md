<!-- doc-scope: PLANS, PRICING TIERS, AND DATA RETENTION.
     owns: OSS/Team/Enterprise tier definitions, retention policy.
     does-not-own: config keys (→ book/10), change controller internals (→ book/12).
     rule: cross-link to contracts, do not restate them. -->
# Plans and Retention

CodeClone is open source and runs locally. Some coordination and audit features
have edition-specific limits. This page describes workspace intent registry
retention by plan and how to reach the team for Team or Enterprise options.

## Workspace intent registry retention

When `intent_registry_backend = "sqlite"`, closed workspace intents (`clean`,
`expired`, `orphaned`) are kept for audit and purged only after
`intent_registry_retention_days`. The open-source edition enforces these limits
at configuration time.

| Edition     | Default retention | Maximum retention | Intent registry backend                          |
|-------------|-------------------|-------------------|--------------------------------------------------|
| Open source | 7 days            | 14 days           | SQLite (local file under `.codeclone/db/`) |
| Team        | configurable      | up to 30 days     | SQLite or managed deployment                     |
| Enterprise  | configurable      | up to 90 days     | PostgreSQL (managed or self-hosted)              |

Values above **14 days** in `[tool.codeclone]` on the open-source edition return a
contract error and point here.

## Why longer retention matters

The SQLite intent registry is an **auditable coordination trail**: who declared
change intent, when leases expired, and how workspace conflicts were resolved.
Longer retention helps:

- post-incident review across agent sessions and CI runs;
- compliance and internal audit without exporting ad hoc JSON files;
- multi-agent forensics when several tools share one repository.

File-based registry (`intent_registry_backend = "file"`) remains ephemeral by
design; SQLite is the audit-oriented backend.

## Team plan

Team is for engineering groups that need a longer local audit window without
operating their own database tier.

**Includes:**

- workspace intent retention up to **30 days**;
- priority onboarding for MCP, VS Code, and controller workflows;
- **premium support** for integration, CI gating, and upgrade questions;
- optional assisted rollout of SQLite registry and audit trail in shared
  workspaces.

Team keeps the same integrity-protected intent payload contract as open source;
limits are raised through licensed configuration, not by weakening validation.

## Enterprise plan

Enterprise is for organizations that need centralized retention, PostgreSQL,
and operational support.

**Includes everything in Team, plus:**

- workspace intent retention up to **90 days**;
- **PostgreSQL backend** for the intent registry (high availability, backup, and
  query from existing ops tooling);
- **premium support** with agreed response targets;
- deployment guidance for air-gapped, multi-repo, or CI-controller topologies;
- optional alignment with internal security and change-management processes.

PostgreSQL is an Enterprise backend; open source and Team continue to use the
local SQLite registry unless you adopt Enterprise licensing.

## Contact

For Team or Enterprise pricing, retention entitlements, PostgreSQL rollout, or
premium support details:

**[sudo@secuapp.ru](mailto:sudo@secuapp.ru)**

## Related configuration

See [Config and Defaults — workspace intent registry](book/10-config-and-defaults.md)
and [Structural Change Controller — workspace intent registry](book/12-structural-change-controller.md).

Open-source keys:

```toml
[tool.codeclone]
intent_registry_backend = "sqlite"
intent_registry_path = ".codeclone/db/intents.sqlite3"
intent_registry_retention_days = 7   # max 14 in open source
```

Environment overrides: `CODECLONE_INTENT_REGISTRY_BACKEND`,
`CODECLONE_INTENT_REGISTRY_PATH`, `CODECLONE_INTENT_REGISTRY_RETENTION_DAYS`.
