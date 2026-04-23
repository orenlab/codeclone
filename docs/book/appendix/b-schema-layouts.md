# Appendix B. Schema Layouts

## Purpose

Compact structural layouts for baseline/cache/report contracts in `2.0.0b6`.

## Baseline schema (`2.1`)

```json
{
  "meta": {
    "generator": { "name": "codeclone", "version": "2.0.0b6" },
    "schema_version": "2.1",
    "fingerprint_version": "1",
    "python_tag": "cp313",
    "created_at": "2026-03-11T00:00:00Z",
    "payload_sha256": "...",
    "metrics_payload_sha256": "...",
    "api_surface_payload_sha256": "..."
  },
  "clones": {
    "functions": ["<fingerprint>|<loc_bucket>"],
    "blocks": ["<block_hash>|<block_hash>|<block_hash>|<block_hash>"]
  },
  "metrics": { "...": "optional embedded metrics snapshot" },
  "api_surface": { "...": "optional embedded public API snapshot" }
}
```

Compact embedded `api_surface` symbol layout:

```json
{
  "module": "pkg.mod",
  "filepath": "pkg/mod.py",
  "symbols": [
    {
      "local_name": "PublicClass.method",
      "kind": "method",
      "start_line": 10,
      "end_line": 14,
      "params": [],
      "returns_hash": "",
      "exported_via": "name"
    }
  ]
}
```

Notes:

- `local_name` is stored on disk to avoid repeating the containing module path.
- `filepath` is stored as a baseline-directory-relative wire path when
  possible, rather than as a machine-local absolute path.
- Runtime reconstructs canonical full qualnames as `module:local_name` before
  API-surface diffing and restores runtime filepaths from the wire path.

## Standalone metrics-baseline schema (`1.2`)

```json
{
  "meta": {
    "generator": { "name": "codeclone", "version": "2.0.0b6" },
    "schema_version": "1.2",
    "python_tag": "cp313",
    "created_at": "2026-03-11T00:00:00Z",
    "payload_sha256": "...",
    "api_surface_payload_sha256": "..."
  },
  "metrics": { "...": "metrics snapshot" },
  "api_surface": {
    "modules": [
      {
        "module": "pkg.mod",
        "filepath": "pkg/mod.py",
        "all_declared": [],
        "symbols": [
          {
            "local_name": "run",
            "kind": "function",
            "start_line": 10,
            "end_line": 14,
            "params": [],
            "returns_hash": "",
            "exported_via": "name"
          }
        ]
      }
    ]
  }
}
```

## Cache schema (`2.5`)

```json
{
  "v": "2.5",
  "payload": {
    "py": "cp313",
    "fp": "1",
    "ap": {
      "min_loc": 10,
      "min_stmt": 6,
      "block_min_loc": 20,
      "block_min_stmt": 8,
      "segment_min_loc": 20,
      "segment_min_stmt": 10,
      "collect_api_surface": false
    },
    "files": {
      "codeclone/cache/store.py": {
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
- Cached public-API symbol payloads preserve declaration order for `params`;
  canonicalization must not rewrite callable signature order.
- `u` row decoder accepts both legacy 11-column rows and canonical 17-column rows
  (legacy rows map new structural fields to neutral defaults).

## Report schema (`2.9`)

```json
{
  "report_schema_version": "2.9",
  "meta": {
    "codeclone_version": "2.0.0b6",
    "project_name": "codeclone",
    "scan_root": ".",
    "analysis_mode": "full",
    "report_mode": "full",
    "analysis_profile": {
      "min_loc": 10,
      "min_stmt": 6,
      "block_min_loc": 20,
      "block_min_stmt": 8,
      "segment_min_loc": 20,
      "segment_min_stmt": 10
    },
    "analysis_thresholds": {
      "design_findings": {
        "complexity": { "metric": "cyclomatic_complexity", "operator": ">", "value": 20 },
        "coupling": { "metric": "cbo", "operator": ">", "value": 10 },
        "cohesion": { "metric": "lcom4", "operator": ">=", "value": 4 }
      }
    },
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
      "analysis_started_at_utc": "2026-03-11T08:36:29Z",
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
        "dead_code": 0,
        "clones": 1
      }
    },
    "groups": {
      "clones": {
        "functions": [],
        "blocks": [],
        "segments": [],
        "suppressed": {
          "functions": [
            {
              "...": "..."
            }
          ],
          "blocks": [],
          "segments": []
        }
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
      },
      "overloaded_modules": {
        "total": 0,
        "candidates": 0,
        "population_status": "limited",
        "top_score": 0.0,
        "average_score": 0.0
      },
      "coverage_adoption": {
        "modules": 0,
        "params_total": 0,
        "params_annotated": 0,
        "param_permille": 0,
        "returns_total": 0,
        "returns_annotated": 0,
        "return_permille": 0,
        "public_symbol_total": 0,
        "public_symbol_documented": 0,
        "docstring_permille": 0,
        "typing_any_count": 0
      },
      "coverage_join": {
        "status": "ok",
        "source": "coverage.xml",
        "files": 0,
        "units": 0,
        "measured_units": 0,
        "overall_executable_lines": 0,
        "overall_covered_lines": 0,
        "overall_permille": 0,
        "missing_from_report_units": 0,
        "coverage_hotspots": 0,
        "scope_gap_hotspots": 0,
        "hotspot_threshold_percent": 50,
        "invalid_reason": null
      },
      "api_surface": {
        "enabled": false,
        "modules": 0,
        "public_symbols": 0,
        "added": 0,
        "breaking": 0,
        "strict_types": false
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
      "overloaded_modules": {
        "summary": {
          "total": 0,
          "candidates": 0,
          "population_status": "limited",
          "top_score": 0.0,
          "average_score": 0.0
        },
        "detection": {
          "version": "1",
          "scope": "report_only",
          "strategy": "project_relative_composite"
        },
        "items": []
      },
      "coverage_adoption": {
        "summary": {
          "modules": 0,
          "params_total": 0,
          "params_annotated": 0,
          "param_permille": 0,
          "baseline_diff_available": false,
          "param_delta": 0,
          "returns_total": 0,
          "returns_annotated": 0,
          "return_permille": 0,
          "return_delta": 0,
          "public_symbol_total": 0,
          "public_symbol_documented": 0,
          "docstring_permille": 0,
          "docstring_delta": 0,
          "typing_any_count": 0
        },
        "items": []
      },
      "coverage_join": {
        "summary": {
          "status": "ok",
          "source": "coverage.xml",
          "files": 0,
          "units": 0,
          "measured_units": 0,
          "overall_executable_lines": 0,
          "overall_covered_lines": 0,
          "overall_permille": 0,
          "missing_from_report_units": 0,
          "coverage_hotspots": 0,
          "scope_gap_hotspots": 0,
          "hotspot_threshold_percent": 50,
          "invalid_reason": null
        },
        "items": []
      },
      "api_surface": {
        "summary": {
          "enabled": false,
          "baseline_diff_available": false,
          "modules": 0,
          "public_symbols": 0,
          "added": 0,
          "breaking": 0,
          "strict_types": false
        },
        "items": []
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
      },
      "directory_hotspots": {
        "...": "..."
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
- Source report schema: 2.9
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
          "version": "2.0.0b6",
          "rules": [
            {
              "id": "CCLONE001",
              "name": "codeclone.CCLONE001",
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
      "automationDetails": {
        "id": "codeclone/full/2026-03-11T08:36:32Z"
      },
      "artifacts": [
        {
          "location": {
            "uri": "codeclone/report/renderers/sarif.py",
            "uriBaseId": "%SRCROOT%"
          }
        }
      ],
      "invocations": [
        {
          "executionSuccessful": true,
          "startTimeUtc": "2026-03-11T08:36:29Z",
          "workingDirectory": {
            "uri": "file:///repo/project/"
          }
        }
      ],
      "properties": {
        "profileVersion": "1.0",
        "reportSchemaVersion": "2.9"
      },
      "results": [
        {
          "kind": "fail",
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
                  "uri": "codeclone/report/renderers/sarif.py",
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
          "properties": {
            "primaryPath": "codeclone/report/renderers/sarif.py",
            "primaryQualname": "codeclone.report.sarif:render_sarif_report_document",
            "primaryRegion": "1:10"
          },
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

- `codeclone/baseline/clone_baseline.py`
- `codeclone/cache/store.py`
- `codeclone/report/document/builder.py`
- `codeclone/report/renderers/text.py`
- `codeclone/report/renderers/markdown.py`
- `codeclone/report/renderers/sarif.py`
