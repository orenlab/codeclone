# Changelog

## 0.1.0 — 2026-06-22

Initial JetBrains Platform plugin scaffold:

- MCP stdio client aligned with VS Code `mcpClient.js` protocol (`2025-03-26`)
- Launcher auto-discovery, IDE governance channel, PasswordSafe memory governance
- Tool window with Overview, Hotspots, Session, Memory tabs
- Analyze workspace / changed files, triage, remediation, session clear
- Settings page and status bar widget
- Gradle IntelliJ Platform Plugin 2.10.4, target SDK 2025.2 (`sinceBuild=252`)
- JDK 21 launcher helper (`run-ide.sh`) and Gradle daemon JVM pin for hosts where the
  default `java` is JDK 25+ (Gradle fails with only the version in the error)
- Gradle wrapper **8.14.3** (IPGP 2.10.4 requires Gradle 8.13+)
- Engineering Memory inbox: status/drafts/stale via `query_engineering_memory`, tree UI,
  context-menu approve/reject, refresh action
- Memory governance wire format aligned with MCP + VS Code (`governance_ticket`, `proof`,
  `protocol`, `actor`; reads `payload.records_by_status`)
- Unit tests for governance proof and memory payload parsing
- Run summary + reviewed findings after analyze; session stats/audit markdown reports;
  mark finding reviewed; sync memory from latest run
- Gradle: version-aware local IDE selection; `PythonCore`/`Pythonid` bundled deps for PyCharm;
  `compatiblePlugin("PythonCore")` for IntelliJ IDEA (fixes legacy `org.jetbrains.plugins.python`)
