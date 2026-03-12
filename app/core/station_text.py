from __future__ import annotations

from typing import Any, Mapping


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def stop_thai_name(stop: Any) -> str:
    """Best-effort Thai station name lookup without raising errors."""
    if stop is None:
        return ""

    if isinstance(stop, Mapping):
        for key in (
            "thai_name",
            "name_th",
            "th_name",
            "stop_name_th",
            "station_name_th",
            "terminal_name_th",
            "thai",
        ):
            value = _text(stop.get(key))
            if value:
                return value

    for key in (
        "thai_name",
        "name_th",
        "th_name",
        "stop_name_th",
        "station_name_th",
        "terminal_name_th",
        "thai",
    ):
        value = _text(getattr(stop, key, ""))
        if value:
            return value

    return ""


def stop_english_name(stop: Any) -> str:
    if stop is None:
        return ""

    if isinstance(stop, Mapping):
        for key in (
            "display_name",
            "name_en",
            "english_name",
            "stop_name",
            "station_name",
            "terminal_name",
            "name",
            "title",
        ):
            value = _text(stop.get(key))
            if value:
                return value

    for key in (
        "display_name",
        "name_en",
        "english_name",
        "stop_name",
        "station_name",
        "terminal_name",
        "name",
        "title",
    ):
        value = _text(getattr(stop, key, ""))
        if value:
            return value

    return ""


def taxi_hint(stop: Any) -> str:
    en = stop_english_name(stop)
    th = stop_thai_name(stop)
    if en and th:
        return f"Say '{en}' or show '{th}' to the taxi driver."
    if en:
        return f"Say '{en}' to the taxi driver."
    if th:
        return f"Show '{th}' to the taxi driver."
    return ""
