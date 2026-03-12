
def render_whatsapp(guided):

    text = guided.get("text", "")
    buttons = guided.get("buttons", [])
    rows = guided.get("rows", [])

    if buttons:
        return {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": b["id"],
                                "title": b["title"]
                            }
                        }
                        for b in buttons[:3]
                    ]
                }
            }
        }

    if rows:
        return {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": text},
                "action": {
                    "button": "Choose",
                    "sections": [
                        {
                            "title": "Options",
                            "rows": rows
                        }
                    ]
                }
            }
        }

    return {
        "type": "text",
        "text": {"body": text}
    }
