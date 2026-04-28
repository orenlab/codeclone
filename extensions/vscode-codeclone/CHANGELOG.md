# Change Log

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
