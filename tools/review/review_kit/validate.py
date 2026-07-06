"""JSON Schema validation for review packets and artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from review_kit.policy import KIT_ROOT

_SCHEMA_DIR = KIT_ROOT / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    path = _SCHEMA_DIR / name
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        msg = f"Invalid schema document: {path}"
        raise SystemExit(msg)
    return loaded


def validate_packet(packet: dict[str, Any]) -> list[str]:
    return _validate(packet, "packet-v3.schema.json")


def validate_artifact(artifact: dict[str, Any]) -> list[str]:
    return _validate(artifact, "artifact-v3.schema.json")


def validate_document(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        return [f"Document root must be an object: {path}"]
    version = loaded.get("packet_version")
    if version == "3":
        return validate_packet(loaded)
    if loaded.get("review_contract_version") == 3:
        return validate_artifact(loaded)
    return [f"Unsupported document type: {path}"]


def _validate(document: dict[str, Any], schema_name: str) -> list[str]:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - environment guard
        msg = "jsonschema is required for review kit validation"
        raise SystemExit(msg) from exc
    schema = _load_schema(schema_name)
    if schema_name == "artifact-v3.schema.json":
        schema = dict(schema)
        defs = dict(schema.get("$defs", {}))
        defs["review_packet"] = _load_schema("packet-v3.schema.json")
        schema["$defs"] = defs
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    return [error.message for error in errors]
