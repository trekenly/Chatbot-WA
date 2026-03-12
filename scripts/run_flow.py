#!/usr/bin/env python3
"""Run the local /chat flow end-to-end (or only Step 1) for repeatable testing.

Usage:
  python scripts/run_flow.py --user t1 --date 2026-01-25 --pax 1 --trip 1 --seat 12 --gender M
  python scripts/run_flow.py --only-step1

This script talks to your local chatbot API (/chat), not directly to BusX.
"""

import argparse
import json
import sys
from typing import Any, Dict, List

import requests


def post_chat(base_url: str, user_id: str, text: str) -> Dict[str, Any]:
    r = requests.post(
        base_url,
        json={"user_id": user_id, "text": text},
        timeout=60,
    )
    r.raise_for_status()
    try:
        return r.json()
    except Exception as e:
        raise RuntimeError(f"Non-JSON response: {r.text[:200]}") from e


def print_actions(resp: Dict[str, Any]) -> None:
    actions = resp.get("actions") or []
    for a in actions:
        t = a.get("type")
        p = a.get("payload") or {}
        if t == "say":
            print(p.get("text", ""))
        elif t == "choose_one":
            print(p.get("title", "Choose:"))
            for opt in p.get("options", []):
                print("  " + opt.get("label", ""))
        elif t == "ask":
            print(p.get("prompt", ""))
        else:
            print(f"[{t}] {json.dumps(p, ensure_ascii=False)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/chat")
    ap.add_argument("--user", default="demo1")
    ap.add_argument("--date", default="2026-01-25")
    ap.add_argument("--pax", type=int, default=1)
    ap.add_argument("--trip", type=int, default=1)
    ap.add_argument("--seat", default="12")
    ap.add_argument("--gender", choices=["M", "F"], default="M")
    ap.add_argument("--only-step1", action="store_true")
    args = ap.parse_args()

    # 1) search trips
    resp = post_chat(args.base_url, args.user, f"{args.date} {args.pax}")
    print_actions(resp)

    # 2) pick trip
    resp = post_chat(args.base_url, args.user, str(args.trip))
    print_actions(resp)

    # 3) confirm -> load seat layout
    resp = post_chat(args.base_url, args.user, "confirm")
    print_actions(resp)

    # 4) pick seat
    resp = post_chat(args.base_url, args.user, str(args.seat))
    print_actions(resp)

    # set gender for mark_seats
    resp = post_chat(args.base_url, args.user, f"gender {args.gender}")
    print_actions(resp)

    # Step 1
    resp = post_chat(args.base_url, args.user, "mark")
    print_actions(resp)

    if args.only_step1:
        return 0

    # Step 2
    resp = post_chat(args.base_url, args.user, "reserve")
    print_actions(resp)

    # Step 3
    resp = post_chat(args.base_url, args.user, "pay")
    print_actions(resp)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
