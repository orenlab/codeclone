# Appendix B. Schema Layouts

## Purpose
Provide concise structural layouts for baseline/cache/report contracts.

## Baseline schema (v1.0)
```json
{
  "meta": {
    "generator": {"name": "codeclone", "version": "1.4.0"},
    "schema_version": "1.0",
    "fingerprint_version": "1",
    "python_tag": "cp313",
    "created_at": "2026-02-11T12:00:00Z",
    "payload_sha256": "..."
  },
  "clones": {
    "functions": ["..."],
    "blocks": ["..."]
  }
}
```
Refs:
- `codeclone/baseline.py:_baseline_payload`

## Cache schema (v1.2)
```json
{
  "v": "1.2",
  "payload": {
    "py": "cp313",
    "fp": "1",
    "files": {
      "rel/path.py": {
        "st": [1730000000000000000, 2048],
        "u": [["mod:f", 1, 10, 10, 3, "fp", "0-19"]],
        "b": [["mod:f", 3, 6, 4, "h1|h2|h3|h4"]],
        "s": [["mod:f", 3, 8, 6, "segment_hash", "segment_sig"]]
      }
    }
  },
  "sig": "..."
}
```
Refs:
- `codeclone/cache.py:Cache.save`
- `codeclone/cache.py:_encode_wire_file_entry`

## Report schema (v1.1)
```json
{
  "meta": {
    "report_schema_version": "1.1",
    "codeclone_version": "1.4.0",
    "python_version": "3.13",
    "python_tag": "cp313",
    "baseline_status": "ok",
    "cache_status": "ok",
    "groups_counts": {
      "functions": {"total": 1, "new": 0, "known": 1},
      "blocks": {"total": 7, "new": 0, "known": 7},
      "segments": {"total": 0, "new": 0, "known": 0}
    }
  },
  "files": ["/abs/path.py"],
  "groups": {
    "functions": {"group_key": [[0, "mod:f", 1, 20, 20, 6, "fp", "20-49"]]},
    "blocks": {"group_key": [[0, "mod:f", 5, 8, 4]]},
    "segments": {"group_key": [[0, "mod:f", 5, 10, 6, "h", "s"]]}
  },
  "groups_split": {
    "functions": {"new": ["..."], "known": ["..."]},
    "blocks": {"new": ["..."], "known": ["..."]},
    "segments": {"new": ["..."], "known": []}
  },
  "group_item_layout": {
    "functions": ["file_i", "qualname", "start", "end", "loc", "stmt_count", "fingerprint", "loc_bucket"],
    "blocks": ["file_i", "qualname", "start", "end", "size"],
    "segments": ["file_i", "qualname", "start", "end", "size", "segment_hash", "segment_sig"]
  }
}
```
Refs:
- `codeclone/_report_serialize.py:to_json_report`
- `codeclone/_report_serialize.py:GROUP_ITEM_LAYOUT`

## TXT report sections
```text
REPORT METADATA
...
FUNCTION CLONES (NEW)
FUNCTION CLONES (KNOWN)
BLOCK CLONES (NEW)
BLOCK CLONES (KNOWN)
SEGMENT CLONES (NEW)
SEGMENT CLONES (KNOWN)
```
Refs:
- `codeclone/_report_serialize.py:to_text_report`
