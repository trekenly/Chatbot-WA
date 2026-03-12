"""Typed contracts for BusX buyer chat.

The goal: keep the *wire contract* small and stable.

Frontend rule: `ask` is the single source of truth for what UI to show next.
Backend rule: never infer UI state from previous UI behavior.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class InboundChat(BaseModel):
    user_id: str
    text: str = ""

    # Optional metadata from the client / UI
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    currency: Optional[str] = None

    # Safe test mode: only parse+validate intent, don't hit ticketing APIs
    intent_only: bool = False


class Action(BaseModel):
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class AskOption(BaseModel):
    value: str
    label: str
    description: Optional[str] = None


class Ask(BaseModel):
    """Authoritative next-input instruction.

    - type='field': user should provide a value for `field`.
    - type='choice': user should pick an option (value) from `options`.
    - type='seatmap': web UI may render a tappable seat grid; submission is still
      normal text (e.g. "12,13").
    """

    type: Literal["field", "choice", "seatmap"]
    field: Optional[str] = None
    prompt: Optional[str] = None
    options: List[AskOption] = Field(default_factory=list)

    # seatmap extras (only used when type == 'seatmap')
    seats: Any = None
    pax: Optional[int] = None
    selected: List[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Internal orchestrator output (actions + opaque state)."""

    actions: List[Action]
    state: Dict[str, Any] = Field(default_factory=dict)


class ChatEnvelope(BaseModel):
    """Wire response returned by /buyer/chat."""

    say: str
    ask: Optional[Ask] = None
    actions: List[Action] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)

    # Backwards compatibility for older clients
    message: Optional[str] = None
    menu: Optional[List[Dict[str, Any]]] = None
    expect: Optional[Dict[str, Any]] = None
