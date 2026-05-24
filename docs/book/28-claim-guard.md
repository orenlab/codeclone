# 28. Claim Guard

## Purpose

Define the `validate_review_claims` MCP tool in the CodeClone `2.1` release
line.

Claim guard keeps review text disciplined. It validates cited claims against
semantic flags already present in stored MCP runs. It does not perform free-form
NLP, source analysis, or fact checking.

## Public surface

- MCP tool: `validate_review_claims`
- service method: `CodeCloneMCPService.validate_review_claims`
- session mixin: `codeclone/surfaces/mcp/_session_claim_guard_mixin.py`
- pure validator: `codeclone/surfaces/mcp/_claim_guard.py`

## Parameters

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `text` | `str` | required | Markdown, plain text, or JSON string to validate. |
| `run_id` | `str \| None` | latest | Stored MCP run whose report semantics are used. |
| `require_citations` | `bool` | `true` | Warn when no known finding ids or metric family names are cited. |

Text must be non-empty and at most `50,000` characters.

## Contract

The tool is read-only. It does not mutate source files, baselines, reports,
analysis cache, review markers, or change intents.

Validation is deterministic:

1. Resolve the stored run.
2. Index canonical and short finding ids from the canonical report.
3. Read metric-family gate semantics from CodeClone's metric registry.
4. Extract citations from the supplied text.
5. Check conservative keyword patterns inside a bounded sentence/window around
   each citation.

The response contains:

- `valid`: `true` when no violations were found.
- `citations_found`: number of recognized citations.
- `violations`: deterministic overclaim records.
- `warnings`: missing or unknown citations.
- `validated_citations`: per-citation validity summary.

Warnings do not make the response invalid.

## Patterns

| Pattern | Meaning |
|---------|---------|
| `P-1` | Security Surfaces were described as vulnerabilities or exploitability. |
| `P-2` | A report-only metric family was described as a CI failure or blocking gate. |
| `P-3` | A finding with `novelty="known"` was described as new or introduced. |
| `P-4` | Dead-code certainty was claimed despite runtime reachability evidence. |
| `P-5` | A finding was claimed fixed/resolved before a post-patch run was available. |

## Non-goals

Claim guard is not:

- a vulnerability scanner
- a CI gate
- an LLM fact checker
- a proof that uncited text is correct
- a replacement for `check_patch_contract`

## Locked by tests

- `tests/test_mcp_service.py`
- `tests/test_mcp_server.py`
- `tests/test_mcp_tool_schema_snapshot.py`
