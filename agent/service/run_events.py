import json
from collections.abc import AsyncIterator

from core.database import AsyncSessionLocal
from model.agent_run_event import AgentRunEvent
from repository.agent_run_event import list_run_events_after


async def stream_run_events(
    run_id: str,
    *,
    after_event_id: int,
) -> AsyncIterator[str]:
    async with AsyncSessionLocal() as session:
        events = await list_run_events_after(
            session,
            run_id=run_id,
            after_event_id=after_event_id,
        )

    for event in events:
        yield format_persisted_sse(event)


def format_persisted_sse(event: AgentRunEvent) -> str:
    payload = {"runId": event.agent_run_id, **event.payload}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.id}\ndata: {data}\n\n"
