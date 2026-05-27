# Change Log

## 0.3.0

- add **Show Blast Radius** command — concentric SVG diagram of structural
  impact for the active file, rendered in a secure WebviewPanel with no scripts
  and nonce-scoped CSP
- add **Copy Blast Radius Brief** command — structured Markdown summary of
  origin, dependents, clone cohort, risk signals, and guardrails copied to
  clipboard
- both commands available from the editor title menu when a run is active and
  the workspace is trusted
- bump minimum version to reflect the new MCP `get_blast_radius` dependency
- upgrade `@vscode/vsce` from `2.25.0` to `3.9.1`, resolving the transitive
  `tmp` path-traversal (GHSA-ph9p-34f9-6g65) and `qs` DoS
  (GHSA-q8mj-m7cp-5q26) vulnerabilities
- upgrade `@types/node` to `25.9.1` and `typescript` to `6.0.3`

## 0.2.7

- surface Coverage Join review items in Hotspots when coverage data is available
- auto-detect workspace-root `coverage.xml` or use `codeclone.analysis.coverageXml`

## 0.2.6

- align setup guidance with the stable CodeClone `2.0.0` MCP package
- require CodeClone `2.0.0` or newer for the final 2.0 release line

## 0.2.5

- pin the packaging toolchain to `@vscode/vsce@2.25.0` to remove the vulnerable transitive `uuid<14` chain from the
  extension lockfile
- keep the generated `.vsix` package behavior unchanged after the packaging dependency refresh

## 0.2.4

- restore repo-local `uv run codeclone-mcp` fallback for the refactored MCP server layout
- cover both legacy and current CodeClone repo markers in extension runtime tests
- surface report-only `Security Surfaces` as a first-class hotspot and overview layer
- add source-first security review actions, briefs, and Markdown detail without creating a second truth model
- join `Security Surfaces` with current-run `Coverage Join` context when MCP exposes both families

## 0.2.3

- explain baseline mismatch runs more clearly with compact baseline/runtime tag context
- surface runtime source in the session view and alongside baseline-mismatch run details

## 0.2.2

- surface repository-vs-focus semantics more clearly in triage and summary UX
- explain new findings by source kind without widening the review flow

## 0.2.1

- refresh packaged extension metadata for prerelease validation

## 0.2.0

- add a native preview VS Code extension for `codeclone-mcp`
- ship triage-first `Overview`, `Hotspots`, and `Runs & Session` views
- keep the extension read-only and canonical-report-first
- add setup guidance for local `codeclone-mcp` installation and launcher issues
- add guided review actions that prefer revealing source before opening deeper
  detail
- surface report-only `Overloaded Modules` as a distinct IDE layer without promoting
  them to health or gating truth
