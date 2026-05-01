# CodeClone GitHub Action

Baseline-aware structural code quality analysis for Python with:

- configurable CI gating
- SARIF upload for GitHub Code Scanning
- PR summary comments
- deterministic JSON report generation

This action is designed for PR and CI workflows where you want CodeClone to act
as a non-LLM review bot: run analysis, upload SARIF, post a concise summary,
and propagate the real gate result.

## What it does

The v2 action flow is:

1. set up Python
2. install `codeclone`
3. optionally require a committed baseline
4. run CodeClone with JSON + optional SARIF output
5. optionally upload SARIF to GitHub Code Scanning
6. optionally post or update a PR summary comment
7. return the real CodeClone exit code as the job result

When the action is used from the checked-out CodeClone repository itself
(`uses: ./.github/actions/codeclone`), it installs CodeClone from the repo
source under test. Remote consumers still install from PyPI.

## Basic usage

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2
  with:
    fail-on-new: "true"
```

For strict reproducibility, pin the full release tag:

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2.0.0
```

For long-lived workflows, `@v2` follows the latest compatible 2.x action
metadata.

## PR workflow example

```yaml
name: CodeClone

on:
  pull_request:
    types: [ opened, synchronize, reopened ]
    paths: [ "**/*.py" ]

permissions:
  contents: read
  security-events: write
  pull-requests: write

jobs:
  codeclone:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: orenlab/codeclone/.github/actions/codeclone@v2
        with:
          fail-on-new: "true"
          fail-health: "60"
          sarif: "true"
          pr-comment: "true"
```

## Inputs

| Input                   | Default                         | Purpose                                                                                                           |
|-------------------------|---------------------------------|-------------------------------------------------------------------------------------------------------------------|
| `python-version`        | `3.14`                          | Python version used to run the action                                                                             |
| `package-version`       | `2.0.0`                         | CodeClone version from PyPI for remote installs; ignored when the action runs from the checked-out CodeClone repo |
| `path`                  | `.`                             | Project root to analyze                                                                                           |
| `json-path`             | `.cache/codeclone/report.json`  | JSON report output path                                                                                           |
| `sarif`                 | `true`                          | Generate SARIF and try to upload it                                                                               |
| `sarif-path`            | `.cache/codeclone/report.sarif` | SARIF output path                                                                                                 |
| `pr-comment`            | `true`                          | Post or update a PR summary comment                                                                               |
| `fail-on-new`           | `true`                          | Fail if new clone groups are detected                                                                             |
| `fail-on-new-metrics`   | `false`                         | Fail if metrics regress vs baseline                                                                               |
| `fail-threshold`        | `-1`                            | Max allowed function+block clone groups                                                                           |
| `fail-complexity`       | `-1`                            | Max cyclomatic complexity                                                                                         |
| `fail-coupling`         | `-1`                            | Max coupling CBO                                                                                                  |
| `fail-cohesion`         | `-1`                            | Max cohesion LCOM4                                                                                                |
| `fail-cycles`           | `false`                         | Fail on dependency cycles                                                                                         |
| `fail-dead-code`        | `false`                         | Fail on high-confidence dead code                                                                                 |
| `fail-health`           | `-1`                            | Minimum health score                                                                                              |
| `require-baseline`      | `true`                          | Fail early if the baseline file is missing                                                                        |
| `baseline-path`         | `codeclone.baseline.json`       | Baseline path passed to CodeClone                                                                                 |
| `metrics-baseline-path` | `codeclone.baseline.json`       | Metrics baseline path passed to CodeClone                                                                         |
| `extra-args`            | `""`                            | Additional CodeClone CLI arguments                                                                                |
| `no-progress`           | `true`                          | Disable progress output                                                                                           |

For numeric gate inputs, `-1` means "disabled".

## Outputs

| Output          | Meaning                                                    |
|-----------------|------------------------------------------------------------|
| `exit-code`     | CodeClone process exit code                                |
| `json-path`     | Resolved JSON report path                                  |
| `sarif-path`    | Resolved SARIF report path                                 |
| `pr-comment-id` | PR comment id when the action updated or created a comment |

## Exit behavior

The action propagates the real CodeClone exit code at the end:

- `0` — success
- `2` — contract error
- `3` — gating failure
- `5` — internal error

SARIF upload and PR comment posting are treated as additive integrations. The
final job result is still driven by the CodeClone analysis exit code.

## Permissions

Recommended permissions:

```yaml
permissions:
  contents: read
  security-events: write
  pull-requests: write
```

Notes:

- `security-events: write` is required for SARIF upload
- `pull-requests: write` is required for PR comments
- if you only want gating and JSON output, you can disable `sarif` and
  `pr-comment`

## Install policy

Released action tags pin the PyPI package version in action metadata. For
example, `@v2.0.0` installs `codeclone==2.0.0` unless you override
`package-version`.

Explicit prerelease or smoke-test override:

```yaml
with:
  package-version: "<version>"
```

Local/self-repo validation:

```yaml
- uses: ./.github/actions/codeclone
```

- `uses: ./.github/actions/codeclone` installs CodeClone from the checked-out
  repository source, so release branches and unreleased commits do not depend on
  PyPI publication.

## Notes and limitations

- For private repositories without GitHub Advanced Security, SARIF upload may
  not be available. In that case, set `sarif: "false"` and rely on the PR
  comment + exit code.
- The baseline file must exist in the repository when `require-baseline: true`.
- The action always generates a canonical JSON report, even if SARIF is
  disabled.
- PR comments are updated in place using a hidden marker, so repeated runs do
  not keep adding duplicate comments.
- Analysis has a 10-minute timeout. For very large repositories, consider
  using `extra-args: "--skip-metrics"` or narrowing the scan scope.

## See also

- [CodeClone repository](https://github.com/orenlab/codeclone)
- [Documentation](https://orenlab.github.io/codeclone/)
- [SARIF integration](https://orenlab.github.io/codeclone/sarif/)
