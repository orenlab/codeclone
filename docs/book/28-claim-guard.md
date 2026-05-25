# 28. Claim Guard

## Purpose

Define the `validate_review_claims` MCP tool in the CodeClone `2.1` release
line.

Claim guard keeps review text disciplined. It validates cited claims against
semantic flags already present in stored MCP runs. It does not perform
free-form NLP, source analysis, or fact checking.

---

## Public surface

| Artifact       | Path                                                   |
|----------------|--------------------------------------------------------|
| MCP tool       | `validate_review_claims`                               |
| Service method | `CodeCloneMCPService.validate_review_claims`           |
| Session mixin  | `codeclone/surfaces/mcp/_session_claim_guard_mixin.py` |
| Pure validator | `codeclone/surfaces/mcp/_claim_guard.py`               |

---

## Validation pipeline

```mermaid
graph LR
    T["Review text"] --> E["Extract citations<br/><small>finding IDs, metric families</small>"]
    E --> W["Text window<br/><small>±80 chars around citation</small>"]
    W --> P["Pattern checks<br/><small>P-1 … P-5</small>"]
    P --> V{"Violations?"}
    V -->|"yes"| INV["valid: false"]
    V -->|"no"| OK["valid: true"]

    style INV fill:#fee2e2
    style OK fill:#f0fdf4
```

The pipeline is fully deterministic:

1. Resolve the stored run.
2. Index canonical and short finding IDs from the canonical report.
3. Read metric-family gate semantics from the metric registry.
4. Extract citations from the supplied text.
5. Check keyword patterns inside a bounded text window around each citation.

---

## Parameters

| Parameter           | Type          | Default  | Meaning                                                         |
|---------------------|---------------|----------|-----------------------------------------------------------------|
| `text`              | `str`         | required | Markdown, plain text, or JSON string to validate                |
| `run_id`            | `str \| None` | latest   | Stored MCP run whose report semantics are used                  |
| `require_citations` | `bool`        | `true`   | Warn when no known finding IDs or metric family names are cited |

!!! info "Text limits"
    Text must be non-empty and at most `50,000` characters.

---

## Contract

The tool is **read-only**. It does not mutate source files, baselines,
reports, analysis cache, review markers, or change intents.

### Response shape

| Field                 | Type   | Meaning                              |
|-----------------------|--------|--------------------------------------|
| `valid`               | `bool` | `true` when no violations were found |
| `citations_found`     | `int`  | Number of recognized citations       |
| `violations`          | `list` | Deterministic overclaim records      |
| `warnings`            | `list` | Missing or unknown citations         |
| `validated_citations` | `list` | Per-citation validity summary        |

Warnings do not make the response invalid. Only violations set
`valid=false`.

---

## Patterns

Five deterministic overclaim patterns, each checking keyword proximity
around cited finding IDs or metric family names:

### P-1: Security surface overclaim

Security Surfaces described as vulnerabilities or exploitability.
Security Surfaces are a **report-only boundary inventory** — they show
where security-relevant capabilities exist, not whether they are
exploitable.

### P-2: Gate overclaim

A report-only metric family described as a CI failure or blocking gate.
Not all metric families participate in gating; report-only families are
informational.

### P-3: Regression overclaim

A finding with `novelty="known"` described as new or introduced. Known
findings are accepted baseline debt, not new regressions.

### P-4: Dead code certainty overclaim

Dead-code certainty claimed despite runtime reachability evidence. When
framework reachability patterns match a dead-code candidate, certainty
claims are invalid.

### P-5: Fix overclaim

A finding claimed as fixed or resolved before a post-patch run is
available. Without a comparison run, fix claims cannot be verified.

---

## Non-goals

!!! warning "What claim guard is not"
    - Not a vulnerability scanner
    - Not a CI gate
    - Not an LLM fact checker
    - Not proof that uncited text is correct
    - Not a replacement for `check_patch_contract`

---

## Locked by tests

- `tests/test_mcp_service.py`
- `tests/test_mcp_server.py`
- `tests/test_mcp_tool_schema_snapshot.py`

---

## See also

- [20-mcp-interface.md](20-mcp-interface.md) — full MCP tool and resource contract
- [MCP deep dive](../mcp.md) — architecture, workflows, prompt patterns
