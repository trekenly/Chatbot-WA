from __future__ import annotations

from fastapi import APIRouter, Body
from jsonschema import Draft202012Validator

# TEMP schema: just enough to validate your wrapper shape.
# Next step we’ll replace this with your real NormalizedIntent + request schemas.
NORMALIZED_INTENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["intent", "payload"],
    "properties": {
        "intent": {"type": "string"},
        "confidence": {"type": "number"},
        "original_text": {"type": "string"},
        "detected_language": {"type": "string"},
        "locale": {"type": "string"},
        "time_zone": {"type": "string"},
        "currency": {"type": "string"},
        "payload": {"type": "object"},
    },
    "additionalProperties": True,
}

router = APIRouter(prefix="/busx/intent", tags=["busx-intent"])
_validator = Draft202012Validator(NORMALIZED_INTENT_SCHEMA)


@router.post("/validate")
def validate_intent(doc: dict = Body(...)) -> dict:
    errors = sorted(_validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        return {
            "ok": False,
            "errors": [
                {
                    "path": "/".join([str(p) for p in e.path]),
                    "message": e.message,
                    "schema_path": "/".join([str(p) for p in e.schema_path]),
                }
                for e in errors[:50]
            ],
        }
    return {"ok": True}
