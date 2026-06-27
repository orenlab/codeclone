## Search semantics (schema 1.1)

### FTS (always available)

FTS5 index (`memory_fts`) indexes record statements and metadata.

| `match_mode`    | Behavior                                      |
|-----------------|-----------------------------------------------|
| `any` (default) | Match records containing **any** query token  |
| `all`           | Match records containing **all** query tokens |

Document links display as normalized headings, e.g.
`AGENTS.md · §16 · Change routing → AGENTS.md`.

Refs:

- `codeclone/memory/search_index.py`
- `codeclone/memory/display.py`

Semantic retrieval: [search-semantic.md](search-semantic.md).
