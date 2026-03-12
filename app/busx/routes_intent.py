from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from app.busx.schema_validate import validate_payload

router = APIRouter(prefix="/busx", tags=["busx"])


@router.post("/intent/validate")
def validate_intent(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    ok, err = validate_payload("NormalizedIntent.schema.json", payload)
    return {"ok": ok, "error": err}
