## Staleness and anchor durability

Records with a git anchor (`created_at_commit` + `code_fingerprint`) are judged
by **drift from that anchor**, not by whether the subject appears in the current
analysis inventory. Non-Python subjects (`.md`, `.toml`, `.js`, …) therefore
stay `active` across refresh when their on-disk bytes are unchanged.

| Anchor vs `HEAD`           | Status transition                                           |
|----------------------------|-------------------------------------------------------------|
| Fingerprint matches anchor | `active` (or reactivated from `historical` / drift `stale`) |
| Fingerprint differs        | `stale` (`subject_fingerprint_drift`)                       |
| Subject file absent        | `historical` (preserved, queryable)                         |

A record is **anchored** only when both `created_at_commit` and `code_fingerprint`
are present at write time. `record_candidate` sets git fields only when the
subject fingerprint resolves (commit without fingerprint is treated as
unanchored). Unanchored records skip anchor drift; system-ingest signals below
still apply.

Only `draft` records skip refresh drift evaluation. `human`-origin and
human-approved records follow the same anchor table — approval does not exempt
a record from honest content drift.

```mermaid
flowchart TD
    subgraph Anchor["anchor drift (refresh)"]
        A1[fingerprint match]
        A2[subject_fingerprint_drift]
        A3[subject deleted]
    end

    subgraph Refresh["init --refresh (system ingest)"]
        R1[missing_from_refresh]
        R2[evidence_digest_mismatch]
        R3[refresh_content_contradiction]
        R4[report_digest_shift]
    end

    subgraph Scope["accepted finish"]
        S1[scope_files_changed]
    end

    A1 --> ACT[(status = active)]
    A2 --> ST[(status = stale)]
    A3 --> HIST[(status = historical)]
    Refresh --> ST
    Scope --> ST
    ST --> RE[Excluded from default retrieval]
    HIST --> RET[Included in default retrieval]
    RE --> RA[Reactivate when anchor fingerprint matches]
    HIST --> RA
```

`historical` is a durable resting state — vacuum never auto-deletes it.
Stale records remain for audit but are **excluded** from `get_relevant_memory`
and default search unless explicitly included.

---
