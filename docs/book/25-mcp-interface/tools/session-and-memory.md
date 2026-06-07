### Session-local tools

| Tool                     | Key parameters                 | Purpose                                                                                               |
|--------------------------|--------------------------------|-------------------------------------------------------------------------------------------------------|
| `mark_finding_reviewed`  | `finding_id`, `run_id`, `note` | Session-local review marker (in-memory)                                                               |
| `list_reviewed_findings` | `run_id`                       | List reviewed markers for a run                                                                       |
| `clear_session_runs`     | —                              | Reset in-memory runs, session review markers, and workspace intent registry state for the MCP process |
