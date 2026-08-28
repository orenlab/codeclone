# CodeClone for JetBrains IDEs

Native PyCharm / IntelliJ IDEA surface for [codeclone-mcp](https://orenlab.github.io/codeclone/concepts/mcp/) —
baseline-aware structural review for Python workspaces. Same contract as the VS Code extension:
stdio MCP client, triage-first workflow, repository read-only with governed Engineering Memory writes.

> **Not an inspections panel.** CodeClone is for structural review and refactoring flow, not the
> built-in Problems view.

## Requirements

- IntelliJ Platform **2025.2+** (build `252+`)
- **JDK 21** for Gradle builds (launcher JVM). JDK 25+ is not supported as the Gradle
  launcher JVM (failure message may be only the Java version, e.g. `26.0.1`).
- Python plugin (bundled with PyCharm; required on IntelliJ IDEA)
- Python project with a local root path
- `codeclone-mcp` launcher (`codeclone >= 2.0.0`)

Install the MCP launcher:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

## Features (v0.2.0)

Enterprise-grade tool window UI built on IntelliJ Platform widgets (not flat text trees):

| Surface | Implementation |
|---------|----------------|
| **Overview** | Metric cards, triage summary, quick actions, deep links to session reports |
| **Hotspots** | Sortable `TableView` with filter, master/detail splitter, inline finding preview |
| **Runs & Session** | Session metric cards + embedded HTML session stats / audit trail |
| **Memory** | Searchable inbox table, bulk approve/reject, detail pane |

| VS Code surface | JetBrains plugin |
|-----------------|------------------|
| Tool window: Overview / Hotspots / Session / Memory | Right-side **CodeClone** tool window with the same four tabs |
| Analyze Workspace / Changed Files | Tool window **Quick actions** + **Tools** menu entries |
| MCP stdio client + launcher auto-discovery | Same resolution order: settings → `.venv` → tool paths → `PATH` with monorepo `uv run` fallback |
| `--ide-governance-channel` | Enabled automatically for Memory governance |
| Production triage / remediation | Opens scratch editor with MCP markdown |
| Session stats / audit trail | Embedded HTML panels + scratch Markdown export |
| Mark finding reviewed | Hotspots context menu + Session tab reviewed list |
| Sync memory from run | `manage_engineering_memory(refresh_from_run)` |
| Status bar | Optional status bar widget |
| Memory approve/reject | Memory tab inbox tree; context menu approve/reject; PasswordSafe + MCP protocol v2 (same fields as VS Code) |
| Change-control MCP tools | **Not wired** — remain agent-only, matching VS Code policy |

## Build & run

Uses the [IntelliJ Platform Gradle Plugin 2.x](https://plugins.jetbrains.com/docs/intellij/tools-intellij-platform-gradle-plugin.html)
(target SDK `2025.2.6.1`, Java **21**).

**Local IDE:** Gradle picks an installed IDE whose version matches `codeclone.platformVersion`
(e.g. IntelliJ IDEA **2025.2.6.1** before PyCharm **2026.x** when the target SDK is 2025.2).
Override with `codeclone.localIde` in `gradle.properties`. PyCharm bundles Python
(`PythonCore` / `Pythonid`); IntelliJ IDEA Ultimate does **not** — Gradle resolves a
compatible `PythonCore` from JetBrains Marketplace via `compatiblePlugin` when IDEA is selected.

```bash
cd extensions/jetbrains-codeclone
./run-ide.sh
# or, with JDK 21 on PATH / JAVA_HOME:
./gradlew runIde
```

Force a specific install:

```bash
./gradlew -Pcodeclone.localIde="/Applications/PyCharm.app" runIde
```

If `./gradlew` fails with only a version number under `* What went wrong:`, your default
`java` is too new — use `./run-ide.sh` (prefers JDK 21 / JetBrains JBR) or
`export JAVA_HOME=$(/usr/libexec/java_home -v 21)`.

If you see `Could not find bundled plugin with ID: 'org.jetbrains.plugins.python'`, update
this checkout — modern builds use `PythonCore` / `Pythonid`, not the legacy plugin id.

Verify plugin:

```bash
./gradlew build verifyPlugin test
```

Package:

```bash
./gradlew buildPlugin
# build/distributions/jetbrains-codeclone-0.2.0.zip
```

## Settings

**Settings → Tools → CodeClone**

- `MCP command` — `auto` (default) or absolute/bare launcher command
- `MCP extra args` — space-separated; transport is always forced to `stdio`
- `Changed-files diff ref` — default `HEAD`
- `Analysis profile` — `defaults` / `deeperReview` / `custom`
- `Cache policy` — `reuse` / `off`

**PyCharm / IDEA launched from the Dock** often have a minimal `PATH` (no `~/.local/bin`, no
`uv`). The plugin augments `PATH` for MCP subprocesses and, inside the CodeClone repo, falls back
to `uv run --project <repo> codeclone-mcp` when `codeclone-mcp` is not on `PATH`.

If status stays **disconnected**, use **Tools → Verify Local Server**, the CodeClone toolbar,
or set `MCP command` to an absolute path, for example:

```text
/Users/you/PycharmProjects/codeclone/.venv/bin/codeclone-mcp
```

Install the launcher if needed:

```bash
uv tool install "codeclone[mcp]"
# or, in the repo:
uv sync --extra mcp
```

## Architecture

```
CodeCloneProjectService   ← orchestration, coroutines, notifications
McpClient                 ← JSON-RPC 2.0 / MCP 2025-03-26 over stdio
McpLauncher               ← launcher resolution + env filtering (VS Code parity)
MemoryGovernance          ← IDE governance register/prepare/commit via PasswordSafe (protocol v2)
MemorySnapshotLoader      ← query_engineering_memory status/drafts/stale (payload.records_by_status)
CodeCloneToolWindowPanels ← Overview / Hotspots / Session / Memory inbox tree UI
SessionInsightsLoader     ← workspace session stats summary (IDE governance channel)
WorkspaceInsightsFormatter← session stats / audit trail markdown for scratch editors
```

## Roadmap (post-0.2.0)

- Hotspot focus modes, reviewed markers, HTML report bridge
- Blast radius SVG tool window
- Memory search panel, trajectories
- `pluginVerifier` matrix for PyCharm + IDEA

## License

Mozilla Public License 2.0 — see repository `LICENSE`.
