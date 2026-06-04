# Publishing and Docs Site

## Purpose

Document how the documentation site is built, validated, and published.

This page is operational, not contractual. The source of truth for behavior
remains the current repository code and CI workflow.

!!! note "Scope"
    This page covers docs-site build and publishing mechanics. Public behavior
    contracts still live in the book chapters and in the repository code.

## Current stack

- Site generator: `Zensical`
- Theme: Zensical built-in theme (Material-derived)
- Docs root: `docs/`
- Site config: `zensical.toml`
- Publish workflow: `.github/workflows/docs.yml`

## What gets published

The published site contains:

- the documentation tree under `docs/`
- the contract book under `docs/book/`
- deep-dive pages such as architecture and CFG notes
- a live sample report for the current repository build under
  `Examples / Sample Report`

## Build flow

The docs workflow (`.github/workflows/docs.yml`) follows this order:

1. install project dependencies
2. build the site with `zensical build --clean --strict`
3. generate a live sample report into `site/examples/report/live`
4. upload the built site as a GitHub Pages artifact
5. deploy on pushes to `main`

Admonition indentation (`!!!` / `???` body must be indented 4 spaces) is enforced
in the main test workflow via `tests/test_docs_build_contract.py`, not in
`docs.yml`. Repair locally with
`python3 scripts/lint_admonitions.py docs/ --fix`.

Relevant files:

- `zensical.toml`
- `.github/workflows/docs.yml`
- `scripts/build_docs_example_report.py`

!!! warning "Generated output only"
    `site/` is a generated artifact. It is used for local preview and GitHub
    Pages deployment, but it should not be committed.

## Sample report generation

The sample report is generated from the current `codeclone` repository tree.

Generated artifacts:

- `site/examples/report/live/index.html`
- `site/examples/report/live/report.json`
- `site/examples/report/live/report.sarif`
- `site/examples/report/live/manifest.json`

The sample report is generated during docs publishing and is not committed to
git. `site/` remains ignored.

## Local preview

=== "Build the site"

    ```bash title="Validate the Zensical site"
    uv run --with zensical==0.0.43 zensical build --clean --strict
    ```

=== "Build the site and sample report"

    ```bash title="Generate the live sample report into site/"
    uv run --with zensical==0.0.43 zensical build --clean --strict
    uv run python scripts/build_docs_example_report.py --output-dir site/examples/report/live
    ```

Then open:

- `site/index.html`
- `site/examples/report/live/index.html`

## Integration distribution repos (storefronts)

Public IDE/agent installs are mirrored from this monorepo into **sibling git
repositories** under a shared parent directory. The sync driver is
`scripts/sync_integrations.py`; contract tests live in
`tests/test_sync_integrations.py`.

| CLI `--target` | Distribution directory | GitHub / marketplace | Monorepo source paths |
|----------------|------------------------|----------------------|------------------------|
| `codex` | `codeclone-codex/` | `orenlab/codeclone-codex` | `plugins/codeclone/` + overlays under `scripts/integration_dist/` (root `README.md`, `.gitignore`, public `marketplace.json`) |
| `cursor` | `codeclone-cursor/` | Cursor plugin publish flow | `plugins/cursor-codeclone/` + `plugins/codeclone/scripts/launch_mcp.py` → `scripts/launch_mcp.py` + `gitignore.cursor` |
| `vscode` | `codeclone-vscode/` | VS Code Marketplace | `extensions/vscode-codeclone/` (flat) + `gitignore.vscode` |
| `claude-desktop` | `codeclone-claude-desktop/` | Claude Desktop `.mcpb` bundle | `extensions/claude-desktop-codeclone/` (flat) + `gitignore.claude-desktop` |

Each target must be a **git repository** named exactly `codeclone-{target}` (for
example `codeclone-cursor`). The script refuses wrong directory names or
non-git targets.

### What sync copies (and what it does not)

**Copied:** plugin/extension trees listed above, **distribution overlays** from
`scripts/integration_dist/` (per-target `.gitignore`; Codex-only root `README.md`
and public `.agents/plugins/marketplace.json`), plus generated
`SYNC_MANIFEST.json` at the distribution repo root (commit, package version from
`pyproject.toml`, file counts, UTC timestamp).

**Codex README rule:** GitHub renders only the **repository root** `README.md`.
The plugin guide stays at `plugins/codeclone/README.md`. Sync writes a separate
root file from `scripts/integration_dist/README.codex.root.md` — do not copy the
plugin README to the repo root.

**Codex marketplace rule:** Monorepo dev uses `.agents/plugins/marketplace.json`
(`orenlab-local`). The public `codeclone-codex` repo gets
`scripts/integration_dist/marketplace.codex.json` (`orenlab-codeclone` /
`displayName: CodeClone`).

**Not copied:** the Python package (`codeclone/`), baselines, analysis cache,
canonical reports, monorepo `.cursor/rules` (developer-only; Cursor users get
`plugins/cursor-codeclone/rules/`), or arbitrary files already present in a
distribution repo (for example `.github/workflows/`, extra CI-only files).

**Flat targets (Cursor, VS Code, Claude):** product `README.md` still comes from
the synced extension/plugin tree at the distribution repo root (same file as in
the monorepo). Only Codex needs a second, distribution-specific root README.

**Denied globally during copy:** `.git`, `__pycache__`, `*.pyc`, `node_modules`,
`dist/`, `build/`, `.coverage`. VS Code sync also skips `node_modules/**` and
`.coverage` under the extension tree.

### Layout models

- **Nested (Codex):** `plugins/codeclone/` stays under `plugins/codeclone/` in
  `codeclone-codex`. Stale files inside that subtree are removed before copy.
- **Flat (Cursor, VS Code, Claude Desktop):** extension/plugin files land at the
  distribution repo root. Sync deletes only **top-level names that still exist**
  in the current source tree, then recopies. If you **remove an entire top-level
  directory** from the monorepo source, sync does **not** delete the old copy in
  the distribution repo — remove it manually or restore a stub directory before
  syncing.

### Cursor launcher override

`plugins/cursor-codeclone/scripts/launch_mcp.py` in the monorepo is a thin
`runpy` delegate to the shared Codex launcher. Distribution **`codeclone-cursor`**
must ship the **full** `plugins/codeclone/scripts/launch_mcp.py` body so
`mcp.json` (`python3` + `./scripts/launch_mcp.py`) works standalone. Sync always
applies a second copy pair for that file after the plugin tree (see
`test_cursor_sync_ships_standalone_launcher`).

## Sync workflow (maintainers)

Run from the **monorepo root** (`codeclone/`), with sibling repos checked out
next to it (default `--base-dir ..`) or pass an absolute parent path.

=== "Dry run (plan only)"

    ```bash title="Print copy/delete counts without writing"
    cd /path/to/codeclone
    uv run python scripts/sync_integrations.py --dry-run --all --base-dir ..
    ```

=== "Sync one storefront"

    ```bash title="Sync Codex marketplace repo only"
    uv run python scripts/sync_integrations.py --target codex --base-dir ..
    ```

=== "Sync all four storefronts"

    ```bash title="Update every distribution repo"
    uv run python scripts/sync_integrations.py --all --base-dir ..
    ```

=== "Dirty monorepo (emergency only)"

    ```bash title="Allow sync from uncommitted source"
    uv run python scripts/sync_integrations.py --all --base-dir .. --allow-dirty
    ```

    Exit codes: **0** success, **1** validation error (missing source path, dirty
    tree, bad target name), **2** copy/delete failure.

    After sync, commit and push **each distribution repository** separately. The
    monorepo commit recorded in `SYNC_MANIFEST.json` is the sync source of truth
    for audits.

### Post-sync verification checklist

Use this after `--all` or a single `--target` before tagging a plugin release:

1. **`SYNC_MANIFEST.json`** — `target` matches repo; `codeclone_version` matches
   monorepo `pyproject.toml`; `source_dirty` is `false` for release builds;
   `files_copied` is stable for the same source tree.
2. **`.gitignore` (all four)** — present at distribution repo root; includes
   `.idea/`, `.DS_Store`; VS Code copy also lists `node_modules/`, `*.vsix`, `out/`.
3. **Codex (`codeclone-codex`)** — root `README.md` is the distribution stub (not
   a duplicate of `plugins/codeclone/README.md`);
   `plugins/codeclone/skills/` has four skills;
   `plugins/codeclone/.mcp.json` and `scripts/launch_mcp.py` present;
   `.agents/plugins/marketplace.json` has `name: orenlab-codeclone`.
4. **Cursor (`codeclone-cursor`)** — six skills including `production-triage/` and
   `blast-radius/`; three rules under `rules/` (including `change-control-gate.mdc`);
   `scripts/launch_mcp.py` contains `resolve_launch_target` and **not** `runpy`;
   `mcp.json` still points at `./scripts/launch_mcp.py`.
5. **VS Code (`codeclone-vscode`)** — `package.json` and `src/` at repo root (no
   `extensions/` mirror path); `codeclone.memory.searchSemantic` and related memory
   search settings present when the monorepo extension ships them.
6. **Claude Desktop (`codeclone-claude-desktop`)** — `manifest.json`, `server/index.js`,
   `src/launcher.js` at repo root; bundle build smoke:
   `node extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs` in monorepo
   or the equivalent script path in the distribution repo after sync.

Automated regression: `uv run pytest -q tests/test_sync_integrations.py`.

Byte-for-byte parity: for each synced file, the distribution copy should match
the monorepo source file that sync last wrote for that destination (remember
Cursor `scripts/launch_mcp.py` comes from `plugins/codeclone/scripts/`, not from
the monorepo delegate stub).

## Maintenance rules

- Keep `docs/` as the single source tree for site content.
- Do not commit generated `site/` artifacts.
- Keep docs publishing deterministic: no timestamps in published docs paths.
- Keep the sample report generated from the same commit as the site itself.
- Prefer documenting docs-site mechanics here or in adjacent deep-dive pages,
  not inside contract chapters unless a public contract is affected.
- After changing any integration surface under `plugins/` or `extensions/`, run
  sync and the post-sync checklist before publishing marketplace/plugin releases.

## When to update this page

Update this page when you change:

- `zensical.toml`
- `.github/workflows/docs.yml`
- `scripts/sync_integrations.py` or `scripts/integration_dist/*`
- `tests/test_sync_integrations.py`
- the site navigation model
- the sample report publishing path/layout
- integration distribution layout or sibling repo naming
