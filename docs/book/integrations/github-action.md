<!-- doc-scope: GitHub Action contract stub. class: contract max-lines: 40 -->

# GitHub Action

Setup guide: [Getting started: CI setup](../../getting-started.md#ci-setup).

CodeClone ships a composite GitHub Action for CI and pull-request workflows:
structural analysis, optional SARIF upload, PR summary comments, and
deterministic JSON reports.

**Authoritative reference:** [
`.github/actions/codeclone/README.md`](https://github.com/orenlab/codeclone/blob/main/.github/actions/codeclone/README.md)
in the CodeClone repository (inputs, outputs, exit codes, baseline requirements,
and v2 workflow shape).

Quick start:

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2
  with:
    fail-on-new: "true"
```

The action installs `codeclone` from PyPI for remote consumers. When used from
the checked-out CodeClone monorepo (`uses: ./.github/actions/codeclone`), it
installs from the repository under test.

For CLI flag semantics and exit codes, see [CLI](../11-cli.md) and
[Exit codes](../09-exit-codes.md). For SARIF upload details, see
[SARIF integration](sarif.md).
