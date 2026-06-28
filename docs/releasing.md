<!-- doc-scope: STOREFRONT SYNC AND RELEASE WORKFLOW only.
     owns: sync_integrations.py usage, layout models, post-sync checklist,
       Cursor and Claude Code launcher overrides.
     does-not-own: docs-site build (→ publishing.md), plugin contracts
       (→ integration pages).
     rule: split from the former combined publishing page. Do not re-merge. -->

# Releasing & Storefront Sync

## Integration distribution repos (storefronts)

Public IDE/agent installs are mirrored from this monorepo into **sibling git
repositories** under a shared parent directory. The sync driver is
`scripts/sync_integrations.py`; contract tests live in
`tests/test_sync_integrations.py`.

| CLI `--target`   | Distribution directory      | GitHub / marketplace            | Monorepo source paths                                                                                                                                         |
|------------------|-----------------------------|---------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `codex`          | `codeclone-codex/`          | `orenlab/codeclone-codex`       | `plugins/codeclone/` + overlays under `scripts/integration_dist/` (root `README.md`, `.gitignore`, public `marketplace.json`)                                 |
| `claude-code`    | `codeclone-claude-code/`    | `orenlab/codeclone-claude-code` | `plugins/claude-code-codeclone/` → `plugins/codeclone/` + shared standalone launcher + root `README.md`, `.gitignore`, and public `marketplace.json` overlays |
| `cursor`         | `codeclone-cursor/`         | `orenlab/codeclone-cursor`      | `plugins/cursor-codeclone/` + `plugins/codeclone/scripts/launch_mcp.py` → `scripts/launch_mcp.py` + `gitignore.cursor`                                        |
| `vscode`         | `codeclone-vscode/`         | VS Code Marketplace             | `extensions/vscode-codeclone/` (flat) + `gitignore.vscode`                                                                                                    |
| `claude-desktop` | `codeclone-claude-desktop/` | Claude Desktop `.mcpb` bundle   | `extensions/claude-desktop-codeclone/` (flat) + `gitignore.claude-desktop`                                                                                    |

Each target must be a **git repository** named exactly `codeclone-{target}` (for
example `codeclone-cursor`). The script refuses wrong directory names or
non-git targets.

### What sync copies (and what it does not)

**Copied:** plugin/extension trees listed above, **distribution overlays** from
`scripts/integration_dist/` (per-target `.gitignore`; Codex and Claude Code root
`README.md` plus their public marketplace manifests), plus generated
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

**Claude Code marketplace rule:** the public `codeclone-claude-code` repo gets
`.claude-plugin/marketplace.json` from
`scripts/integration_dist/marketplace.claude-code.json`. The distributable
plugin stays nested under `plugins/codeclone/`, while its root README comes from
`scripts/integration_dist/README.claude-code.root.md`.

**Not copied:** the Python package (`codeclone/`), baselines, analysis cache,
canonical reports, monorepo `.cursor/rules` (developer-only; Cursor users get
`plugins/cursor-codeclone/rules/`), or arbitrary files already present in a
distribution repo (for example `.github/workflows/`, extra CI-only files).

**Flat targets (Cursor, VS Code, Claude Desktop):** product `README.md` still
comes from the synced extension/plugin tree at the distribution repo root (same
file as in the monorepo). Codex and Claude Code use separate,
distribution-specific root READMEs.

**Denied globally during copy:** `.git`, `__pycache__`, `*.pyc`, `node_modules`,
`dist/`, `build/`, `.coverage`. VS Code sync also skips `node_modules/**` and
`.coverage` under the extension tree.

### Layout models

- **Nested (Codex and Claude Code):** `plugins/codeclone/` stays under
  `plugins/codeclone/` in the distribution repository. Stale files inside that
  subtree are removed before copy.
- **Flat (Cursor, VS Code, Claude Desktop):** extension/plugin files land at the
  distribution repo root. Sync deletes only **top-level names that still exist**
  in the current source tree, then recopies. If you **remove an entire top-level
  directory** from the monorepo source, sync does **not** delete the old copy in
  the distribution repo — remove it manually or restore a stub directory before
  syncing.

### Standalone launcher overrides

`plugins/cursor-codeclone/scripts/launch_mcp.py` in the monorepo is a thin
`runpy` delegate to the shared Codex launcher. Distribution **`codeclone-cursor`**
must ship the **full** `plugins/codeclone/scripts/launch_mcp.py` body so
`mcp.json` (`python3` + `./scripts/launch_mcp.py`) works standalone. Sync always
applies a second copy pair for that file after the plugin tree (see
`test_cursor_sync_ships_standalone_launcher`).

The Claude Code source plugin uses the same monorepo delegation pattern.
Distribution **`codeclone-claude-code`** therefore replaces
`plugins/codeclone/scripts/launch_mcp.py` with the same full standalone
implementation (see `test_claude_code_sync_ships_standalone_launcher`).

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

=== "Sync all five storefronts"

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
2. **`.gitignore` (all five)** — present at distribution repo root; includes
   `.idea/`, `.DS_Store`; VS Code copy also lists `node_modules/`, `*.vsix`, `out/`.
3. **Codex (`codeclone-codex`)** — root `README.md` is the distribution stub (not
   a duplicate of `plugins/codeclone/README.md`);
   `plugins/codeclone/skills/` has nine skills;
   `plugins/codeclone/.mcp.json` and `scripts/launch_mcp.py` present;
   `.agents/plugins/marketplace.json` has `name: orenlab-codeclone`.
4. **Claude Code (`codeclone-claude-code`)** — root `README.md` documents the
   two-step marketplace install; `.claude-plugin/marketplace.json` has
   `name: orenlab-codeclone`; `plugins/codeclone/.claude-plugin/plugin.json`,
   `.mcp.json`, nine skills, and the standalone launcher are present. The plugin
   manifest omits `version` intentionally so Git commit identity drives cache
   updates.
5. **Cursor (`codeclone-cursor`)** — nine skills including `codeclone-production-triage/` and
   `codeclone-blast-radius/`; three rules under `rules/` (including `change-control-gate.mdc`);
   `scripts/launch_mcp.py` contains `resolve_launch_target` and **not** `runpy`;
   `mcp.json` still points at `./scripts/launch_mcp.py`.
6. **VS Code (`codeclone-vscode`)** — `package.json` and `src/` at repo root (no
   `extensions/` mirror path); `codeclone.memory.searchSemantic` and related memory
   search settings present when the monorepo extension ships them.
7. **Claude Desktop (`codeclone-claude-desktop`)** — `manifest.json`, `server/index.js`,
   `src/launcher.js` at repo root; bundle build smoke:
   `node extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs` in monorepo
   or the equivalent script path in the distribution repo after sync.

Automated regression: `uv run pytest -q tests/test_sync_integrations.py`.

Byte-for-byte parity: for each synced file, the distribution copy should match
the monorepo source file that sync last wrote for that destination (remember
Cursor and Claude Code standalone launchers come from
`plugins/codeclone/scripts/`, not from their monorepo delegate stubs).

## When to update this page

Update this page when you change:

- `scripts/sync_integrations.py` or `scripts/integration_dist/*`
- `tests/test_sync_integrations.py`
- integration distribution layout or sibling repo naming
- after changing any integration surface under `plugins/` or `extensions/`, run
  sync and the post-sync checklist before publishing marketplace/plugin releases
