import json
from typing import Any


def to_sse(event: Any, *, event_id: int | None = None) -> str:
    payload = event.model_dump(by_alias=True, exclude_none=True)
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {json.dumps(payload, ensure_ascii=False)}\n\n"
