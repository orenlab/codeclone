# Getting Started

Install CodeClone, run your first analysis, set up CI gating, and connect
an MCP client — in that order.

## Install

=== "uv (recommended)"

    ```bash
    uv tool install codeclone
    ```

=== "pip"

    ```bash
    pip install codeclone
    ```

=== "Run without installing"

    ```bash
    uvx codeclone@latest .
    ```

To use the MCP server (AI agents, IDE extensions), install the `mcp` extra:

```bash
uv tool install "codeclone[mcp]"
# or
pip install "codeclone[mcp]"
```

## First Run

```bash
codeclone .
```

This analyzes the current directory and prints a summary to stdout.
For an HTML report:

```bash
codeclone . --html --open-html-report
```

Other formats — all rendered from one canonical JSON report:

```bash
codeclone . --json       # JSON
codeclone . --md         # Markdown
codeclone . --sarif      # SARIF (IDE / Code Scanning)
codeclone . --text       # plain text
```

### Changed-scope review

Analyze only files changed relative to a branch:

```bash
codeclone . --changed-only --diff-against main
```

Or from a recent commit:

```bash
codeclone . --paths-from-git-diff HEAD~1
```

## CI Setup

### 1. Create a baseline

```bash
codeclone . --update-baseline
```

By default this writes `codeclone.baseline.json`, the unified clone and metrics
baseline. Commit it to the repository — it becomes the contract CI enforces.
If you use `--metrics-baseline` to redirect metric state, commit that file too.

### 2. Run in CI

```bash
codeclone . --ci
```

`--ci` equals `--fail-on-new --no-color --quiet`. When a trusted metrics
baseline is present, CI mode also enables `--fail-on-new-metrics`.

Baseline governance: new clones and metric regressions fail the build;
accepted legacy debt passes. CI sees only what changed.

### 3. Quality gates

Add thresholds for stricter enforcement:

```bash
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4
codeclone . --fail-cycles --fail-dead-code --fail-health 60
codeclone . --fail-on-typing-regression --fail-on-docstring-regression
codeclone . --coverage coverage.xml --fail-on-untested-hotspots
```

See [Metrics and quality gates](book/15-metrics-and-quality-gates.md) for the
full gate reference.

### GitHub Action

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2
  with:
    fail-on-new: "true"
    sarif: "true"
    pr-comment: "true"
```

Runs gating, generates reports, uploads SARIF to Code Scanning, and posts a
PR summary comment.
[Action docs](https://github.com/orenlab/codeclone/blob/main/.github/actions/codeclone/README.md)

### Pre-commit hook

```yaml
repos:
  - repo: local
    hooks:
      - id: codeclone
        name: CodeClone
        entry: codeclone
        language: system
        pass_filenames: false
        args: [ ".", "--ci" ]
        types: [ python ]
```

### Exit codes

| Code | Meaning                                             |
|------|-----------------------------------------------------|
| `0`  | Success                                             |
| `2`  | Contract error — untrusted baseline, invalid config |
| `3`  | Gating failure — new clones or threshold exceeded   |
| `5`  | Internal error                                      |

Contract errors (`2`) take precedence over gating failures (`3`).
See [Exit codes](book/03-contracts-exit-codes.md).

## MCP Setup

The MCP server exposes **31 tools** for agent clients over the same canonical
pipeline (33 when VS Code starts the server with `--ide-governance-channel` for
session stats and audit insights).

### Start the server

```bash
codeclone-mcp --transport stdio            # local clients (IDE, agents)
codeclone-mcp --transport streamable-http   # remote / HTTP clients
```

!!! warning
    Analysis tools require an **absolute** repository root.
    Relative roots like `.` are rejected.

### Connect a client

=== "VS Code"

    Install from the
    [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone).
    The extension connects to `codeclone-mcp` automatically.

    See [VS Code extension guide](vscode-extension.md).

=== "Claude Desktop"

    Use the pre-built bundle in
    [`extensions/claude-desktop-codeclone/`](https://github.com/orenlab/codeclone/tree/main/extensions/claude-desktop-codeclone).

    See [Claude Desktop guide](claude-desktop-bundle.md).

=== "Codex"

    ```bash
    marketplace add orenlab/codeclone-codex
    ```

    The source plugin lives in
    [`plugins/codeclone/`](https://github.com/orenlab/codeclone/tree/main/plugins/codeclone);
    the marketplace distribution is `orenlab/codeclone-codex`.

    See [Codex plugin guide](codex-plugin.md).

=== "Cursor"

    Install from the monorepo path
    [`plugins/cursor-codeclone/`](https://github.com/orenlab/codeclone/tree/main/plugins/cursor-codeclone)
    (symlink into `.cursor/` or use Cursor local plugin discovery).

    The Cursor plugin is **not** listed in `.agents/plugins/marketplace.json`;
    that file is Codex-only for local monorepo development.

    See [Cursor plugin guide](cursor-plugin.md).

=== "Manual registration"

    ```bash
    # Codex
    codex mcp add codeclone -- codeclone-mcp --transport stdio

    # Any MCP client
    codeclone-mcp --transport stdio
    ```

### Change controller (AI agents)

When an AI agent edits code, the MCP change controller governs the structural
boundary:

1. **Declare intent** — scope, files, and purpose
2. **Map blast radius** — reverse imports, clone cohorts, do-not-touch
3. **Check patch contract** — pre-edit budget, post-edit verification
4. **Generate receipt** — auditable artifact
5. **Validate claims** — cross-check review text against report

See [Structural Change Controller](book/24-structural-change-controller.md).

## Configuration

CodeClone loads project configuration from `pyproject.toml`:

```toml
[tool.codeclone]
baseline = "codeclone.baseline.json"
min_loc = 10
min_stmt = 6
block_min_loc = 20
block_min_stmt = 8
```

Precedence: CLI flags > `pyproject.toml` > built-in defaults.

See [Config and defaults](book/04-config-and-defaults.md).

## Next Steps

- [Architecture narrative](architecture.md) — how the pipeline works
- [Baseline contract](book/06-baseline.md) — trust model and schema
- [MCP interface contract](book/20-mcp-interface.md) — tool surface and guarantees
- [Report contract](book/08-report.md) — canonical JSON schema
