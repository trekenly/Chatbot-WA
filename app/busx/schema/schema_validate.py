"""JSON Schema validation for BusX LLM-normalized intents.

- Schemas live next to this module as `*.schema.json`.
- `$ref` uses absolute `$id` URLs (e.g. https://busx.example/schemas/Foo.schema.json).
- We pre-load all schemas into an in-memory registry so validation never performs
  network I/O.

Public API:
  - validate_normalized_intent(payload) -> list[str]
  - validate_by_schema_filename(schema_filename, payload) -> list[str]
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parent
ROOT_SCHEMA_FILENAME = "NormalizedIntent.schema.json"


def _read_json(p: Path) -> Dict[str, Any]:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_registry_and_schemas() -> Tuple[Registry, Dict[str, Dict[str, Any]]]:
    """Load all `*.schema.json` files into a referencing Registry."""

    schemas: Dict[str, Dict[str, Any]] = {}
    registry = Registry()

    for fp in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = _read_json(fp)
        if not isinstance(schema, dict):
            continue
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id.strip():
            schemas[fp.name] = schema
            registry = registry.with_resource(schema_id, Resource.from_contents(schema))
        else:
            # Still keep it addressable by filename, but it can't be a $ref target.
            schemas[fp.name] = schema

    if ROOT_SCHEMA_FILENAME not in schemas:
        raise RuntimeError(
            f"Root schema '{ROOT_SCHEMA_FILENAME}' not found in {SCHEMA_DIR}. "
            "Expected `*.schema.json` files to be present."
        )

    return registry, schemas


def _validator_for_schema(schema: Dict[str, Any]) -> Draft202012Validator:
    registry, _ = _load_registry_and_schemas()
    return Draft202012Validator(schema, registry=registry)


def _format_error(err: ValidationError) -> str:
    """Human-friendly one-line error, includes JSON path."""
    path = "$." + ".".join(str(p) for p in err.path) if err.path else "$"
    msg = err.message
    return f"{path}: {msg}"


def validate_by_schema_filename(schema_filename: str, payload: Any) -> List[str]:
    """Validate payload against one of the bundled schema files.

    Returns a list of error strings. Empty list means valid.
    """
    _, schemas = _load_registry_and_schemas()
    schema = schemas.get(schema_filename)
    if schema is None:
        return [f"Unknown schema file: {schema_filename}"]

    v = _validator_for_schema(schema)
    errors = sorted(v.iter_errors(payload), key=lambda e: list(e.path))
    return [_format_error(e) for e in errors]


def validate_normalized_intent(payload: Any) -> List[str]:
    """Validate a NormalizedIntent wrapper payload."""
    return validate_by_schema_filename(ROOT_SCHEMA_FILENAME, payload)
