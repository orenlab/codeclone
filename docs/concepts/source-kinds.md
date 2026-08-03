---
title: "Source-kind classification"
audience: public
doc_type: concept
status: draft
source_commit: "47b7ef37dbe958c40753b933af18beb9480a8b80"
---

## What it is

Every analyzed file is classified by what it is for, so findings in production
code are not averaged together with findings in test code.

Kinds: `production`, `tests`, `fixtures`, `mixed`, `other`. Report breakdowns use
four of them — `production`, `tests`, `fixtures`, `other`.

Policy version: `1`.

## The rule

Classification walks the repo-relative path looking for a test-named segment —
`test`, `tests`, or `testing`:

| Path shape | Kind |
|------------|------|
| No test-named segment | `production` |
| Test-named segment, next segment is `fixtures` | `fixtures` |
| Test-named segment otherwise | `tests` |
| Test-named segment inside a distributed package | `production` |

## Packaging facts decide the last row

A `tests/` directory is test-kind *unless* the module identity registry proves it
is a subpackage of an importable distributed package. Two registry facts decide
it:

1. the owning top-level module must not itself be a test-named tree;
2. every segment from that top level down to the test-named segment must be a
   regular package, so the tree is reachable by an ordinary import.

This is why `mypkg/testing/harness.py` — shipped to your users — is production,
while `tests/test_harness.py` is not. The verdict comes from packaging evidence,
not from the name.

## Golden fixture suppression

Duplication among golden fixtures is usually intentional. `golden_fixture_paths`
suppresses those clone groups:

```toml
[tool.codeclone]
golden_fixture_paths = ["tests/fixtures/goldens"]
```

Rules the patterns must satisfy:

- repo-relative, no `..`, non-empty;
- the pattern must target a `tests/` or `tests/fixtures/` path — production code
  cannot be suppressed this way.

A group is suppressed only when **every** member matches; one production member
keeps the whole group active.

Suppression is visible, never silent. The run reports the suppressed count
alongside the active one, and each suppressed group records the patterns that
matched it, the rule `golden_fixture`, and the source `project_config`.

## Related pages

- [Inline suppressions](../reference/suppressions.md) — the other suppression channel
- [Configuration reference](../reference/configuration.md) — `golden_fixture_paths`
