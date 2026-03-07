# Appendix B. Schema Layouts

## Purpose

Provide concise structural layouts for baseline/cache/report contracts.

## Baseline schema (v2.0)

```json
{
  "meta": {
    "generator": {
      "name": "codeclone",
      "version": "2.0.0"
    },
    "schema_version": "2.0",
    "fingerprint_version": "1",
    "python_tag": "cp313",
    "created_at": "2026-03-06T12:00:00Z",
    "payload_sha256": "...",
    "metrics_payload_sha256": "..."
  },
  "clones": {
    "functions": [
      "..."
    ],
    "blocks": [
      "..."
    ]
  },
  "metrics": {
    "max_complexity": 21,
    "high_risk_functions": [],
    "max_coupling": 8,
    "high_coupling_classes": [],
    "max_cohesion": 3,
    "low_cohesion_classes": [],
    "dependency_cycles": [],
    "dependency_max_depth": 4,
    "dead_code_items": [],
    "health_score": 89,
    "health_grade": "A"
  }
}
```

Notes:

- Top-level `metrics` is optional.
- `metrics_payload_sha256` is present when metrics are embedded.

Refs:

- `codeclone/baseline.py:_baseline_payload`
- `codeclone/metrics_baseline.py:_build_payload`

## Cache schema (v2.0)

```json
{
  "v": "2.0",
  "payload": {
    "py": "cp313",
    "fp": "1",
    "ap": {
      "min_loc": 15,
      "min_stmt": 6
    },
    "files": {
      "rel/path.py": {
        "st": [
          1730000000000000000,
          2048
        ],
        "u": [],
        "b": [],
        "s": []
      }
    }
  },
  "sig": "..."
}
```

Refs:

- `codeclone/cache.py:Cache.save`
- `codeclone/cache.py:_encode_wire_file_entry`

## Report schema (v2.0)

```json
{
  "report_schema_version": "2.0",
  "meta": {
    "report_schema_version": "2.0",
    "codeclone_version": "2.0.0",
    "project_name": "my-project",
    "scan_root": "/abs/path/to/my-project",
    "python_version": "3.13",
    "python_tag": "cp313",
    "baseline_status": "ok",
    "cache_status": "ok"
  },
  "files": [
    "/abs/path.py"
  ],
  "groups": {
    "functions": {},
    "blocks": {},
    "segments": {}
  },
  "groups_split": {
    "functions": {
      "new": [],
      "known": []
    },
    "blocks": {
      "new": [],
      "known": []
    },
    "segments": {
      "new": [],
      "known": []
    }
  },
  "clones": {
    "functions": {
      "groups": {},
      "split": {
        "new": [],
        "known": []
      },
      "count": 0
    },
    "blocks": {
      "groups": {},
      "split": {
        "new": [],
        "known": []
      },
      "count": 0
    },
    "segments": {
      "groups": {},
      "split": {
        "new": [],
        "known": []
      },
      "count": 0
    },
    "clone_types": {
      "functions": {},
      "blocks": {},
      "segments": {}
    }
  },
  "clone_types": {
    "functions": {},
    "blocks": {},
    "segments": {}
  },
  "group_item_layout": {
    "functions": [
      "file_i",
      "qualname",
      "start",
      "end",
      "loc",
      "stmt_count",
      "fingerprint",
      "loc_bucket",
      "cyclomatic_complexity",
      "nesting_depth",
      "risk",
      "raw_hash"
    ],
    "blocks": [
      "file_i",
      "qualname",
      "start",
      "end",
      "size"
    ],
    "segments": [
      "file_i",
      "qualname",
      "start",
      "end",
      "size",
      "segment_hash",
      "segment_sig"
    ]
  }
}
```

Refs:

- `codeclone/report/serialize.py:to_json_report`
- `codeclone/report/serialize.py:GROUP_ITEM_LAYOUT`

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

- `codeclone/report/serialize.py:to_text_report`
