# Python Agent Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Python Agent tool calls, assistant streaming state, ordered message timeline parts, and return the full history shape expected by the frontend.

**Architecture:** Keep the existing Python 5-layer direction: Controller -> Service -> Repository -> Model -> Core/Database. Add focused SQLAlchemy models and repositories for tool invocations and message parts, then make `service.chat.iter_chat_events_with_persistence` coordinate short-lived DB sessions around stream events without holding a session during model streaming.

**Tech Stack:** Python 3.14 target, FastAPI, SQLAlchemy 2.0 AsyncSession, Alembic, psycopg v3, Pydantic.

---

## File Structure

- Create `agent/model/tool_invocation.py`: SQLAlchemy model for persisted tool calls.
- Create `agent/model/message_part.py`: SQLAlchemy model for ordered reasoning/tool timeline rows.
- Modify `agent/model/message.py`: add relationships to `ToolInvocation` and `MessagePart`.
- Modify `agent/migrations/env.py`: import the new models so Alembic autogenerate can detect them.
- Create `agent/migrations/versions/<revision>_create_tool_invocations_and_message_parts.py`: migration for both new tables.
- Create `agent/repository/tool_invocation.py`: create and update tool invocation rows.
- Create `agent/repository/message_part.py`: create and update message part rows.
- Modify `agent/repository/message.py`: add message update and eager-loading for history.
- Modify `agent/service/chat.py`: persist assistant `streaming`, tool calls, message parts, and final assistant update.
- Modify `agent/service/chat_conversations.py`: include `toolInvocations` and `timelineParts` in returned `ChatMessage`.
- Modify `agent/tests/test_chat_stream.py`: cover stream persistence behavior.
- Modify `agent/tests/test_chat_conversations.py`: cover full history response.

## Task 1: Add Models And Migration

**Files:**
- Create: `agent/model/tool_invocation.py`
- Create: `agent/model/message_part.py`
- Modify: `agent/model/message.py`
- Modify: `agent/migrations/env.py`
- Create: `agent/migrations/versions/<revision>_create_tool_invocations_and_message_parts.py`
- Test: `agent/tests/test_message_model.py`

- [ ] **Step 1: Write failing model tests**

Add tests that validate both models are registered in SQLAlchemy metadata.

```python
from model.base import Base


def test_tool_invocations_table_is_registered() -> None:
    table = Base.metadata.tables["tool_invocations"]

    assert table.c.id.primary_key
    assert "message_id" in table.c
    assert "tool_name" in table.c
    assert "args" in table.c
    assert "result" in table.c
    assert "error" in table.c
    assert "latency_ms" in table.c
    assert "status" in table.c
    assert "created_at" in table.c


def test_message_parts_table_is_registered() -> None:
    table = Base.metadata.tables["message_parts"]

    assert table.c.id.primary_key
    assert "message_id" in table.c
    assert "type" in table.c
    assert "order_index" in table.c
    assert "text" in table.c
    assert "tool_invocation_id" in table.c
    assert "created_at" in table.c
```

- [ ] **Step 2: Run model tests and verify failure**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_message_model -v
```

Expected: FAIL with missing `tool_invocations` or `message_parts` table.

- [ ] **Step 3: Add `ToolInvocation` model**

Create `agent/model/tool_invocation.py`:

```python
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    message = relationship("Message", back_populates="tool_invocations")
```

- [ ] **Step 4: Add `MessagePart` model**

Create `agent/model/message_part.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MessagePart(Base):
    __tablename__ = "message_parts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_invocation_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("tool_invocations.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    message = relationship("Message", back_populates="timeline_parts")
    tool_invocation = relationship("ToolInvocation")
```

- [ ] **Step 5: Add relationships to `Message`**

Modify `agent/model/message.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    tool_invocations = relationship(
        "ToolInvocation",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    timeline_parts = relationship(
        "MessagePart",
        back_populates="message",
        cascade="all, delete-orphan",
    )
```

- [ ] **Step 6: Register models in Alembic**

Modify `agent/migrations/env.py`:

```python
import_module("model.conversation")
import_module("model.message")
import_module("model.tool_invocation")
import_module("model.message_part")
```

- [ ] **Step 7: Generate migration**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run alembic revision --autogenerate -m "create tool invocations and message parts"
```

Expected: a new file under `agent/migrations/versions/`.

- [ ] **Step 8: Inspect migration**

Ensure the migration only creates `tool_invocations`, `message_parts`, and related indexes/foreign keys. It must not drop existing tables.

- [ ] **Step 9: Run model tests**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_message_model -v
```

Expected: PASS.

## Task 2: Add Repositories

**Files:**
- Create: `agent/repository/tool_invocation.py`
- Create: `agent/repository/message_part.py`
- Modify: `agent/repository/message.py`
- Test: `agent/tests/test_chat_stream.py`

- [ ] **Step 1: Write failing repository-level persistence test**

Add an async test in `ChatEventStreamTest` that passes through the service, then assert repository-visible rows exist.

```python
async def _test_persists_tool_invocation_and_timeline_parts(self) -> None:
    conversation_id = "conversation-tool-persistence"
    async with AsyncSessionLocal() as session:
        await session.merge(
            Conversation(
                id=conversation_id,
                title="Tool persistence",
                created_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                updated_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    request = ChatStreamRequest.model_validate(
        {"conversationId": conversation_id, "message": "查天气"}
    )
    chunks = [
        (
            AIMessageChunk(
                content="",
                additional_kwargs={"reasoning_content": "先查工具。"},
            ),
            {"langgraph_node": "model"},
        ),
        (
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "get_weather",
                        "args": '{"city":"北京"}',
                        "id": "call-weather-persisted",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
                response_metadata={"finish_reason": "tool_calls"},
            ),
            {"langgraph_node": "model"},
        ),
        (
            ToolMessage(
                content='{"weather":"sunny"}',
                name="get_weather",
                tool_call_id="call-weather-persisted",
            ),
            {"langgraph_node": "tools"},
        ),
        (AIMessageChunk(content="今天晴。"), {"langgraph_node": "model"}),
    ]

    events = [
        event
        async for event in iter_chat_events_with_persistence(
            request,
            session_factory=AsyncSessionLocal,
            agent=FakeAgent(chunks),
            message_id_factory=lambda: "assistant-tool-persisted",
            now_factory=lambda: datetime(2026, 6, 5, 12, 1, tzinfo=UTC),
        )
    ]

    async with AsyncSessionLocal() as session:
        invocation_rows = await session.execute(select(ToolInvocation))
        invocations = invocation_rows.scalars().all()
        part_rows = await session.execute(
            select(MessagePart).order_by(MessagePart.order_index.asc())
        )
        parts = part_rows.scalars().all()

        assert events[-1] == {"type": "done", "messageId": "assistant-tool-persisted"}
        assert len(invocations) == 1
        assert invocations[0].id == "call-weather-persisted"
        assert invocations[0].tool_name == "get_weather"
        assert invocations[0].args == {"city": "北京"}
        assert invocations[0].result == '{"weather":"sunny"}'
        assert invocations[0].status == "completed"
        assert [part.type for part in parts] == ["reasoning", "tool"]
        assert parts[0].text == "先查工具。"
        assert parts[1].tool_invocation_id == "call-weather-persisted"

    async with AsyncSessionLocal() as session:
        await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
        await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
        await session.commit()
```

Also add imports:

```python
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_chat_stream.ChatEventStreamTest -v
```

Expected: FAIL because repositories and service persistence are missing.

- [ ] **Step 3: Create tool invocation repository**

Create `agent/repository/tool_invocation.py`:

```python
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from model.tool_invocation import ToolInvocation


async def create_tool_invocation(
    session: AsyncSession,
    invocation: ToolInvocation,
) -> ToolInvocation:
    session.add(invocation)
    await session.flush()
    return invocation


async def update_tool_invocation(
    session: AsyncSession,
    *,
    invocation_id: str,
    result: Any | None,
    error: str | None,
    latency_ms: int | None,
    status: str,
) -> ToolInvocation | None:
    invocation = await session.get(ToolInvocation, invocation_id)
    if invocation is None:
        return None

    invocation.result = result
    invocation.error = error
    invocation.latency_ms = latency_ms
    invocation.status = status
    await session.flush()
    return invocation
```

- [ ] **Step 4: Create message part repository**

Create `agent/repository/message_part.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from model.message_part import MessagePart


async def create_message_part(
    session: AsyncSession,
    part: MessagePart,
) -> MessagePart:
    session.add(part)
    await session.flush()
    return part


async def update_message_part_text(
    session: AsyncSession,
    *,
    part_id: str,
    text: str,
) -> MessagePart | None:
    part = await session.get(MessagePart, part_id)
    if part is None:
        return None

    part.text = text
    await session.flush()
    return part
```

- [ ] **Step 5: Extend message repository**

Modify `agent/repository/message.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
```

Add:

```python
async def update_message(
    session: AsyncSession,
    *,
    message_id: str,
    content: str,
    reasoning: str,
    status: str,
) -> Message | None:
    message = await session.get(Message, message_id)
    if message is None:
        return None

    message.content = content
    message.reasoning = reasoning
    message.status = status
    await session.flush()
    return message
```

Update query:

```python
result = await session.execute(
    select(Message)
    .where(Message.conversation_id == conversation_id)
    .options(
        selectinload(Message.tool_invocations),
        selectinload(Message.timeline_parts).selectinload(MessagePart.tool_invocation),
    )
    .order_by(Message.created_at.asc())
)
```

Then sort loaded collections in service DTO mapping instead of relying on relationship order.

## Task 3: Persist Stream Events

**Files:**
- Modify: `agent/service/chat.py`
- Test: `agent/tests/test_chat_stream.py`

- [ ] **Step 1: Add explicit streaming-status test**

Update `_test_persists_user_and_final_assistant_message_after_stream_done` to expect the assistant row is created and eventually updated. Keep the final assertion:

```python
self.assertEqual(messages[1].id, "assistant-persisted")
self.assertEqual(messages[1].content, "你好！")
self.assertEqual(messages[1].reasoning, "先思考。")
self.assertEqual(messages[1].status, "done")
```

Add a separate unit-style test with mocked `create_message` and `update_message` to verify call order:

```python
def test_persists_assistant_as_streaming_before_final_update(self) -> None:
    # Use AsyncMock around repository calls and a FakeAgent with one delta.
    # Assert create_message is called for assistant status="streaming"
    # before update_message is called with status="done".
```

- [ ] **Step 2: Run stream tests and verify failure**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_chat_stream.ChatEventStreamTest -v
```

Expected: FAIL because assistant is still inserted only at the end.

- [ ] **Step 3: Import new models and repositories**

Modify `agent/service/chat.py` imports:

```python
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from repository.message import (
    create_message,
    get_messages_by_conversation_id,
    update_message,
)
from repository.message_part import create_message_part, update_message_part_text
from repository.tool_invocation import (
    create_tool_invocation,
    update_tool_invocation,
)
```

- [ ] **Step 4: Add timeline state helper**

Add near persistence helpers:

```python
class TimelineState:
    def __init__(self) -> None:
        self.next_order_index = 0
        self.last_part_id: str | None = None
        self.last_part_type: str | None = None
        self.last_part_text = ""
```

- [ ] **Step 5: Replace final assistant insert with streaming create and final update**

In `iter_chat_events_with_persistence`:

- on `message_created`, call a new `_create_assistant_message_with_new_session`
- on `done/error`, call `_update_assistant_message_with_new_session`
- keep `assistant_content` and `assistant_reasoning` in memory

Use this concrete flow:

```python
if event_type == "message_created":
    message = event["message"]
    assistant_id = message["id"]
    assistant_created_at = _parse_frontend_datetime(message["createdAt"])
    await _create_assistant_message_with_new_session(
        session_factory=session_factory,
        message_id=assistant_id,
        conversation_id=request.conversation_id,
        created_at=assistant_created_at,
    )
elif event_type == "tool_call":
    await _persist_tool_call_with_new_session(
        session_factory=session_factory,
        invocation=event["invocation"],
        now_factory=now_factory,
        timeline_state=timeline_state,
    )
elif event_type == "tool_result":
    await _persist_tool_result_with_new_session(
        session_factory=session_factory,
        invocation=event["invocation"],
    )
elif event_type == "reasoning":
    assistant_reasoning.append(event["text"])
    await _persist_reasoning_part_with_new_session(
        session_factory=session_factory,
        message_id=assistant_id,
        text=event["text"],
        now_factory=now_factory,
        timeline_state=timeline_state,
    )
elif event_type == "delta":
    assistant_content.append(event["text"])
elif event_type == "error":
    assistant_status = "error"

if event_type in {"done", "error"}:
    await _update_assistant_message_with_new_session(
        session_factory=session_factory,
        message_id=assistant_id or message_id_factory(),
        content="".join(assistant_content),
        reasoning="".join(assistant_reasoning),
        status=assistant_status,
    )
```

- [ ] **Step 6: Add helper functions**

Add focused helpers:

```python
async def _create_assistant_message_with_new_session(
    *,
    session_factory: Callable[[], Any],
    message_id: str,
    conversation_id: str,
    created_at: datetime,
) -> None:
    async with session_factory() as session:
        try:
            await create_message(
                session,
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content="",
                    reasoning="",
                    status="streaming",
                    created_at=created_at,
                ),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _update_assistant_message_with_new_session(
    *,
    session_factory: Callable[[], Any],
    message_id: str,
    content: str,
    reasoning: str,
    status: str,
) -> None:
    async with session_factory() as session:
        try:
            await update_message(
                session=session,
                message_id=message_id,
                content=content,
                reasoning=reasoning,
                status=status,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _persist_tool_call_with_new_session(
    *,
    session_factory: Callable[[], Any],
    invocation: dict[str, Any],
    now_factory: Callable[[], datetime],
    timeline_state: TimelineState,
) -> None:
    async with session_factory() as session:
        try:
            persisted = await create_tool_invocation(
                session,
                ToolInvocation(
                    id=invocation["id"],
                    message_id=invocation["messageId"],
                    tool_name=invocation["toolName"],
                    args=invocation.get("args") or {},
                    result=None,
                    error=None,
                    latency_ms=None,
                    status="running",
                    created_at=now_factory(),
                ),
            )
            await create_message_part(
                session,
                MessagePart(
                    id=str(uuid4()),
                    message_id=persisted.message_id,
                    type="tool",
                    order_index=timeline_state.next_order_index,
                    text="",
                    tool_invocation_id=persisted.id,
                    created_at=now_factory(),
                ),
            )
            timeline_state.next_order_index += 1
            timeline_state.last_part_id = None
            timeline_state.last_part_type = "tool"
            timeline_state.last_part_text = ""
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _persist_tool_result_with_new_session(
    *,
    session_factory: Callable[[], Any],
    invocation: dict[str, Any],
) -> None:
    async with session_factory() as session:
        try:
            await update_tool_invocation(
                session=session,
                invocation_id=invocation["id"],
                result=invocation.get("result"),
                error=invocation.get("error"),
                latency_ms=invocation.get("latencyMs"),
                status=invocation["status"],
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _persist_reasoning_part_with_new_session(
    *,
    session_factory: Callable[[], Any],
    message_id: str | None,
    text: str,
    now_factory: Callable[[], datetime],
    timeline_state: TimelineState,
) -> None:
    if message_id is None or text == "":
        return

    async with session_factory() as session:
        try:
            if timeline_state.last_part_type == "reasoning" and timeline_state.last_part_id:
                timeline_state.last_part_text += text
                await update_message_part_text(
                    session=session,
                    part_id=timeline_state.last_part_id,
                    text=timeline_state.last_part_text,
                )
            else:
                part = await create_message_part(
                    session,
                    MessagePart(
                        id=str(uuid4()),
                        message_id=message_id,
                        type="reasoning",
                        order_index=timeline_state.next_order_index,
                        text=text,
                        tool_invocation_id=None,
                        created_at=now_factory(),
                    ),
                )
                timeline_state.next_order_index += 1
                timeline_state.last_part_id = part.id
                timeline_state.last_part_type = "reasoning"
                timeline_state.last_part_text = text
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 7: Run stream tests**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_chat_stream -v
```

Expected: PASS.

## Task 4: Return Full History Shape

**Files:**
- Modify: `agent/service/chat_conversations.py`
- Test: `agent/tests/test_chat_conversations.py`

- [ ] **Step 1: Write failing history response test**

Add a test that creates one assistant message, one invocation, and two timeline parts, then calls the API:

```python
def test_lists_messages_with_tool_invocations_and_timeline_parts(self) -> None:
    payload = asyncio.run(self._seed_message_with_tool_timeline())
    client = TestClient(create_app())

    response = client.get(f"/api/conversation/messages/{payload['conversation_id']}")

    self.assertEqual(response.status_code, 200)
    messages = response.json()
    assistant = next(item for item in messages if item["role"] == "assistant")
    self.assertEqual(assistant["toolInvocations"][0]["id"], "tool-history-1")
    self.assertEqual(assistant["timelineParts"][0]["type"], "reasoning")
    self.assertEqual(assistant["timelineParts"][1]["type"], "tool")
    self.assertEqual(
        assistant["timelineParts"][1]["invocation"]["id"],
        "tool-history-1",
    )
```

- [ ] **Step 2: Run history test and verify failure**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_chat_conversations -v
```

Expected: FAIL because history DTO does not include `toolInvocations` or `timelineParts`.

- [ ] **Step 3: Add DTO conversion helpers**

Modify `agent/service/chat_conversations.py`:

```python
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation
from schema.chat import (
    ChatMessage,
    ReasoningTimelinePart,
    ToolInvocation as ToolInvocationSchema,
    ToolTimelinePart,
)
```

Add:

```python
def _to_tool_invocation(invocation: ToolInvocation) -> ToolInvocationSchema:
    return ToolInvocationSchema(
        id=invocation.id,
        message_id=invocation.message_id,
        tool_name=invocation.tool_name,
        args=invocation.args,
        result=invocation.result,
        error=invocation.error,
        latency_ms=invocation.latency_ms,
        status=invocation.status,
        created_at=invocation.created_at.isoformat(),
    )
```

Add:

```python
def _to_timeline_part(part: MessagePart):
    if part.type == "tool" and part.tool_invocation is not None:
        return ToolTimelinePart(
            id=part.id,
            type="tool",
            order_index=part.order_index,
            invocation=_to_tool_invocation(part.tool_invocation),
        )
    return ReasoningTimelinePart(
        id=part.id,
        type="reasoning",
        order_index=part.order_index,
        text=part.text,
    )
```

- [ ] **Step 4: Return full message DTO**

Replace inline `ChatMessage` construction with `_to_chat_message(message)`:

```python
def _to_chat_message(message: Message) -> ChatMessage:
    tool_invocations = sorted(
        message.tool_invocations,
        key=lambda invocation: (invocation.created_at, invocation.id),
    )
    timeline_parts = sorted(
        message.timeline_parts,
        key=lambda part: (part.order_index, part.id),
    )

    return ChatMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        reasoning=message.reasoning,
        tool_invocations=[_to_tool_invocation(item) for item in tool_invocations],
        timeline_parts=[_to_timeline_part(part) for part in timeline_parts],
        status=message.status,
        created_at=message.created_at.isoformat(),
    )
```

- [ ] **Step 5: Run history tests**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_chat_conversations -v
```

Expected: PASS.

## Task 5: Verify Migration And Full Test Set

**Files:**
- No new files.
- Verify all files touched by Tasks 1-4.

- [ ] **Step 1: Run Alembic upgrade**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run alembic upgrade head
```

Expected: upgrade succeeds and creates `tool_invocations` and `message_parts`.

- [ ] **Step 2: Run focused tests**

Run:

```bash
cd /Users/bytedance/Desktop/ai-investment-assistant/agent
uv run python -m unittest tests.test_message_model tests.test_chat_stream tests.test_chat_conversations -v
```

Expected: PASS.

- [ ] **Step 3: Run diagnostics**

Run diagnostics on modified Python files:

```text
GetDiagnostics for agent/model/tool_invocation.py
GetDiagnostics for agent/model/message_part.py
GetDiagnostics for agent/model/message.py
GetDiagnostics for agent/repository/message.py
GetDiagnostics for agent/repository/tool_invocation.py
GetDiagnostics for agent/repository/message_part.py
GetDiagnostics for agent/service/chat.py
GetDiagnostics for agent/service/chat_conversations.py
```

Expected: no new diagnostics.

- [ ] **Step 4: Commit implementation**

Use the repository commit convention with a concise Chinese Conventional Commit title:

```bash
git add agent docs/superpowers/specs/2026-06-06-python-agent-persistence-design.md docs/superpowers/plans/2026-06-06-python-agent-persistence.md
git commit -m "feat: 补齐 Python Agent 过程持久化"
```
