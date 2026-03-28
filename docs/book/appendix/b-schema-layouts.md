# Appendix B. Schema Layouts

## Purpose

Compact structural layouts for baseline/cache/report contracts in `2.0.0b3`.

## Baseline schema (`2.0`)

```json
{
  "meta": {
    "generator": { "name": "codeclone", "version": "2.0.0b3" },
    "schema_version": "2.0",
    "fingerprint_version": "1",
    "python_tag": "cp313",
    "created_at": "2026-03-11T00:00:00Z",
    "payload_sha256": "...",
    "metrics_payload_sha256": "..."
  },
  "clones": {
    "functions": ["<fingerprint>|<loc_bucket>"],
    "blocks": ["<block_hash>|<block_hash>|<block_hash>|<block_hash>"]
  },
  "metrics": { "...": "optional embedded metrics snapshot" }
}
```

## Cache schema (`2.2`)

```json
{
  "v": "2.2",
  "payload": {
    "py": "cp313",
    "fp": "1",
    "ap": {
      "min_loc": 10,
      "min_stmt": 6,
      "block_min_loc": 20,
      "block_min_stmt": 8,
      "segment_min_loc": 20,
      "segment_min_stmt": 10
    },
    "files": {
      "codeclone/cache.py": {
        "st": [1730000000000000000, 2048],
        "ss": [450, 12, 3, 1],
        "u": [[
          "qualname", 1, 2, 2, 1, "fp", "0-19", 1, 0, "low", "raw_hash",
          0, "none", 0, "fallthrough", "none", "none"
        ]],
        "b": [["qualname", 10, 14, 5, "block_hash"]],
        "s": [["qualname", 10, 14, 5, "segment_hash", "segment_sig"]],
        "cm": [["qualname", 1, 30, 3, 2, 4, 2, "low", "low"]],
        "cc": [["qualname", ["pkg.a", "pkg.b"]]],
        "md": [["pkg.a", "pkg.b", "import", 10]],
        "dc": [["pkg.a:unused_fn", "unused_fn", 20, 24, "function"]],
        "rn": ["used_name"],
        "rq": ["pkg.dep:used_name"],
        "in": ["pkg.dep"],
        "cn": ["ClassName"],
        "sf": [["duplicated_branches", "key", [["stmt_seq", "Expr,Return"]], [["pkg.a:f", 10, 12]]]]
      }
    }
  },
  "sig": "..."
}
```

Notes:

- File keys are wire paths (repo-relative when root is configured).
- Optional sections are omitted when empty.
- `ss` stores per-file source stats and is required for full cache-hit accounting
  in discovery.
- `rn`/`rq` are optional and decode to empty arrays when absent.
- `u` row decoder accepts both legacy 11-column rows and canonical 17-column rows
  (legacy rows map new structural fields to neutral defaults).

## Report schema (`2.1`)

```json
{
  "report_schema_version": "2.1",
  "meta": {
    "codeclone_version": "2.0.0b3",
    "project_name": "codeclone",
    "scan_root": ".",
    "analysis_mode": "full",
    "report_mode": "full",
    "baseline": {
      "...": "..."
    },
    "cache": {
      "...": "..."
    },
    "metrics_baseline": {
      "...": "..."
    },
    "runtime": {
      "report_generated_at_utc": "2026-03-11T08:36:32Z"
    }
  },
  "inventory": {
    "files": {
      "...": "..."
    },
    "code": {
      "...": "..."
    },
    "file_registry": {
      "encoding": "relative_path",
      "items": []
    }
  },
  "findings": {
    "summary": {
      "...": "...",
      "suppressed": {
        "dead_code": 0
      }
    },
    "groups": {
      "clones": {
        "functions": [],
        "blocks": [],
        "segments": []
      },
      "structural": {
        "groups": [
          {
            "kind": "duplicated_branches",
            "...": "..."
          },
          {
            "kind": "clone_guard_exit_divergence",
            "...": "..."
          },
          {
            "kind": "clone_cohort_drift",
            "...": "..."
          }
        ]
      },
      "dead_code": {
        "groups": []
      },
      "design": {
        "groups": []
      }
    }
  },
  "metrics": {
    "summary": {
      "...": "...",
      "dead_code": {
        "total": 0,
        "high_confidence": 0,
        "suppressed": 1
      }
    },
    "families": {
      "complexity": {},
      "coupling": {},
      "cohesion": {},
      "dependencies": {},
      "dead_code": {
        "summary": {
          "total": 0,
          "high_confidence": 0,
          "suppressed": 1
        },
        "items": [],
        "suppressed_items": [
          {
            "...": "..."
          }
        ]
      },
      "health": {}
    }
  },
  "derived": {
    "suggestions": [],
    "overview": {
      "families": {
        "clones": 0,
        "structural": 0,
        "dead_code": 0,
        "design": 0
      },
      "top_risks": [],
      "source_scope_breakdown": {
        "production": 0,
        "tests": 0,
        "fixtures": 0
      },
      "health_snapshot": {
        "score": 100,
        "grade": "A"
      }
    },
    "hotlists": {
      "most_actionable_ids": [],
      "highest_spread_ids": [],
      "production_hotspot_ids": [],
      "test_fixture_hotspot_ids": []
    }
  },
  "integrity": {
    "canonicalization": {
      "version": "1",
      "scope": "canonical_only",
      "sections": [
        "report_schema_version",
        "meta",
        "inventory",
        "findings",
        "metrics"
      ]
    },
    "digest": {
      "verified": true,
      "algorithm": "sha256",
      "value": "..."
    }
  }
}
```

## Markdown projection (`1.0`)

```text
# CodeClone Report
- Markdown schema: 1.0
- Source report schema: 2.1
...
## Overview
## Inventory
## Findings Summary
## Top Risks
## Suggestions
## Findings
## Metrics
## Integrity
```

## SARIF projection (`2.1.0`, profile `1.0`)

```json
{
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "version": "2.1.0",
  "runs": [
    {
      "originalUriBaseIds": {
        "%SRCROOT%": {
          "uri": "file:///repo/project/",
          "description": {
            "text": "The root of the scanned source tree."
          }
        }
      },
      "tool": {
        "driver": {
          "name": "codeclone",
          "version": "2.0.0b3",
          "rules": [
            {
              "id": "CCLONE001",
              "name": "codeclone.function-clone-group",
              "shortDescription": {
                "text": "Function clone group"
              },
              "fullDescription": {
                "text": "Multiple functions share the same normalized function body."
              },
              "help": {
                "text": "...",
                "markdown": "..."
              },
              "defaultConfiguration": {
                "level": "warning"
              },
              "helpUri": "https://orenlab.github.io/codeclone/",
              "properties": {
                "category": "clone",
                "kind": "clone_group",
                "precision": "high",
                "tags": [
                  "clone",
                  "clone_group",
                  "high"
                ]
              }
            }
          ]
        }
      },
      "artifacts": [
        {
          "location": {
            "uri": "codeclone/report/sarif.py",
            "uriBaseId": "%SRCROOT%"
          }
        }
      ],
      "invocations": [
        {
          "executionSuccessful": true,
          "workingDirectory": {
            "uri": "file:///repo/project/"
          }
        }
      ],
      "columnKind": "utf16CodeUnits",
      "properties": {
        "profileVersion": "1.0",
        "reportSchemaVersion": "2.1"
      },
      "results": [
        {
          "ruleId": "CCLONE001",
          "ruleIndex": 0,
          "baselineState": "new",
          "message": {
            "text": "Function clone group (Type-2), 2 occurrences across 2 files."
          },
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {
                  "uri": "codeclone/report/sarif.py",
                  "uriBaseId": "%SRCROOT%",
                  "index": 0
                },
                "region": {
                  "startLine": 1,
                  "endLine": 10
                }
              },
              "logicalLocations": [
                {
                  "fullyQualifiedName": "codeclone.report.sarif:render_sarif_report_document"
                }
              ],
              "message": {
                "text": "Representative occurrence"
              }
            }
          ],
          "relatedLocations": [],
          "partialFingerprints": {
            "primaryLocationLineHash": "0123456789abcdef:1"
          }
        }
      ]
    }
  ]
}
```

## TXT report sections

```text
REPORT METADATA
INVENTORY
FINDINGS SUMMARY
METRICS SUMMARY
DERIVED OVERVIEW
SUGGESTIONS
FUNCTION CLONES (NEW)
FUNCTION CLONES (KNOWN)
BLOCK CLONES (NEW)
BLOCK CLONES (KNOWN)
SEGMENT CLONES (NEW)
SEGMENT CLONES (KNOWN)
STRUCTURAL FINDINGS
DEAD CODE FINDINGS
DESIGN FINDINGS
INTEGRITY
```

## Refs

- `codeclone/baseline.py`
- `codeclone/cache.py`
- `codeclone/report/json_contract.py`
- `codeclone/report/serialize.py`
- `codeclone/report/markdown.py`
- `codeclone/report/sarif.py`
