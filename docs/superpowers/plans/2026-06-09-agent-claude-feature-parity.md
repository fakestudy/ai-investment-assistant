# Agent Claude Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 补齐当前前端已经暴露但 `agent_claude` 未实现或半实现的聊天能力，并完成上一轮计划中的契约收敛、结构拆分、错误边界、配置校验、文档更新和测试拆分。

**Architecture:** 当前仍保持 `web -> agent_claude -> Claude Agent SDK -> PostgreSQL`，不引入 Go BFF、RPC 或 Eino。`agent_claude` 新增 run/event/approval 业务层，让前端的 `activeRun`、resume、approval、cancel、edit/regenerate 都有真实后端状态来源；Claude SDK session 继续负责普通多轮上下文，run/event log 负责前端流式状态和 SSE replay。

**Tech Stack:** FastAPI、SQLAlchemy 2 AsyncSession、Alembic、PostgreSQL、`claude-agent-sdk`、SSE、unittest、Next.js 16、React 19、Zustand、Node Test Runner、Biome。

---

## Scope

本计划实现当前前端已经调用或渲染的能力：

- `GET /api/conversation/messages/{conversation_id}` 返回 `activeRun`。
- `POST /api/chat/stream/resume` 支持按 `runId + afterEventId` 回放和继续订阅。
- `POST /api/chat/approval/decisions/{batch_id}` 支持审批决策并恢复等待中的工具调用。
- `PATCH /api/messages/{messageId}` 支持编辑用户消息。
- `POST /api/chat/streams/{messageId}/cancel` 支持取消正在运行的 assistant 输出。
- `POST /api/chat/stream` 对 `parentMessageId` 和 `regenerateFromMessageId` 有真实语义，不再静默忽略。
- `agent_claude/service/chat.py` 按责任拆分。
- 错误响应不泄漏原始异常。
- 启动/构建 runtime 时校验关键配置。
- 更新架构文档，说明当前实现与未来 Go BFF/RPC 边界。
- 拆分过大的测试文件，保留覆盖率。

## Non-goals

- 不实现 Go BFF。
- 不设计 Go 到 Python 的 RPC contract。
- 不引入 Eino。
- 不把 Go 作为 Agent runtime。
- 不迁移旧 `backend/` Go 聊天实现。
- 不承诺 Claude SDK 在服务进程重启后从半轮 LLM 输出中间继续执行。服务重启后，已持久化的 SSE 事件可以 replay；仍未完成的 in-flight run 应标记为 `failed`，前端可用 regenerate 重新发起。

## Current Gaps

| 前端能力 | 当前前端入口 | 当前 `agent_claude` 状态 | 本计划目标 |
| --- | --- | --- | --- |
| active run | `web/features/chat/store.ts` 读取 `activeRun` | 历史接口固定 `None` | 从 `agent_runs` 投影真实状态 |
| resume stream | `POST /api/chat/stream/resume` | 路由返回 410 | 按事件 ID 回放并订阅 live run |
| approval | `POST /api/chat/approval/decisions/{batchId}` | 路由返回 410 | 写入审批决策并恢复等待中的工具调用 |
| edit message | `PATCH /api/messages/{messageId}` | 无路由 | 只允许编辑 user message 并返回投影 |
| cancel stream | `POST /api/chat/streams/{messageId}/cancel` | 无路由 | 取消 live task，落库 partial answer，关闭 active run |
| regenerate | `regenerateFromMessageId` | schema 接收但 controller 忽略 | 找到前一条 user message，截断后续并重新生成 |
| parent continuation | `parentMessageId` | schema 接收但 controller 忽略 | 从指定 user message 处截断分支并重新生成 |
| error boundary | SSE `error.message` | 返回 `str(exc)` | 客户端安全文案，服务端日志保留细节 |
| config validation | `build_options()` | 缺配置时请求中失败 | 启动或构建 options 时快速失败 |

## Coverage Of Previous Plan Items

- 上一条计划 2：契约收敛。由 Task 1、Task 3、Task 5、Task 6 覆盖。
- 上一条计划 3：拆分 `service/chat.py`。由 Task 2 覆盖。
- 上一条计划 4：错误边界。由 Task 8 覆盖。
- 上一条计划 5：配置校验。由 Task 8 覆盖。
- 上一条计划 6：文档和测试拆分。由 Task 9、Task 10 覆盖。

## File Structure

### Backend files

- Modify `agent_claude/main.py`: 注册新增 frontend-compatible routes。
- Modify `agent_claude/controller/chat.py`: controller 只做 HTTP 入参校验、调用 service、返回 SSE/JSON。
- Modify `agent_claude/schema/chat.py`: 增加 `ActiveRunSummary`、approval schemas、run events、edit/cancel request/response。
- Modify `agent_claude/model/message.py`: 保留 `seq` 作为编辑/重生成截断依据。
- Create `agent_claude/model/agent_run.py`: run 状态、active run 约束、取消标记。
- Create `agent_claude/model/agent_run_event.py`: 持久化 SSE event log，支持 replay。
- Create `agent_claude/model/approval.py`: approval batch 和 approval request。
- Create `agent_claude/migrations/versions/20260609_0002_create_run_event_approval_tables.py`: 新增 run/event/approval 表。
- Create `agent_claude/repository/agent_run.py`: run 创建、状态更新、active run 查询。
- Create `agent_claude/repository/agent_run_event.py`: event append、after-event replay、last event 查询。
- Create `agent_claude/repository/approval.py`: approval batch 创建、决策写入、状态查询。
- Modify `agent_claude/repository/message.py`: 增加编辑、按 seq 截断、查找前一条 user message。
- Create `agent_claude/service/sse.py`: SSE encode/decode helpers。
- Create `agent_claude/service/sdk_events.py`: Claude SDK message 解析。
- Create `agent_claude/service/stream_persistence.py`: message、reasoning、tool、title 投影持久化。
- Create `agent_claude/service/run_events.py`: event log 写入、订阅、replay、heartbeat。
- Create `agent_claude/service/run_manager.py`: in-process run task registry、cancel、resume subscription。
- Create `agent_claude/service/approval_gate.py`: Claude SDK `can_use_tool` approval gate。
- Create `agent_claude/service/chat_stream.py`: 新的普通聊天编排入口。
- Modify `agent_claude/service/chat.py`: 保留兼容导出，委托到 `chat_stream.py`。
- Modify `agent_claude/service/history.py`: 历史消息投影同时返回 active run。
- Modify `agent_claude/service/runtime.py`: 增加配置校验、approval gate 注入点。
- Create `agent_claude/tests/test_run_models.py`: run/event/approval model 和 migration contract。
- Create `agent_claude/tests/test_run_events.py`: replay、event id、subscription 行为。
- Create `agent_claude/tests/test_stream_resume.py`: resume API 行为。
- Create `agent_claude/tests/test_message_edit_regenerate.py`: edit/regenerate/parent semantics。
- Create `agent_claude/tests/test_approval_flow.py`: approval_required、decision、resume behavior。
- Create `agent_claude/tests/test_cancel_stream.py`: cancel route 和 run 状态。
- Modify `agent_claude/tests/test_chat_stream.py`: 保留流式核心 happy path，迁移细分用例。
- Modify `agent_claude/tests/test_history_api.py`: activeRun 和新增 route contract。
- Modify `agent_claude/tests/test_runtime.py`: 配置校验与 safe error 行为。

### Frontend files

- Modify `web/features/chat/types.ts`: 若后端字段收敛后类型缺口存在，在这里补齐。
- Modify `web/features/chat/api.ts`: 保持现有 path；只调整错误解析和字段兼容。
- Modify `web/features/chat/store.ts`: 处理 cancel、resume、approval 的真实后端错误边界。
- Modify `web/features/chat/store.test.ts`: 从 mock backend 角度覆盖新增真实契约。
- Modify `web/features/chat/api.test.ts`: 新增 error payload 和 endpoint contract 覆盖。

### Docs

- Modify `docs/project/ARCHITECTURE.md`: 更新当前 `agent_claude` runtime 能力和限制。
- Modify `docs/project/PLAN_CHAT.md`: 更新聊天链路任务状态。
- Modify `README.md`: 更新本地验证命令和功能边界。

---

## Task 1: Add Contract Tests For Frontend Feature Parity

**Files:**
- Modify: `agent_claude/tests/test_history_api.py`
- Create: `agent_claude/tests/test_stream_resume.py`
- Create: `agent_claude/tests/test_message_edit_regenerate.py`
- Create: `agent_claude/tests/test_approval_flow.py`
- Create: `agent_claude/tests/test_cancel_stream.py`
- Modify: `web/features/chat/api.test.ts`

- [x] **Step 1: Write failing route registration tests**

In `agent_claude/tests/test_history_api.py`, extend `test_app_registers_frontend_compatible_messages_route` so it also asserts:

```python
self.assertIn("/api/messages/{message_id}", paths)
self.assertIn("/api/chat/streams/{message_id}/cancel", paths)
```

Keep existing assertions for `/api/chat/stream/resume` and `/api/chat/approval/decisions/{batch_id}`.

- [x] **Step 2: Write failing activeRun projection test**

Add a test that patches `history.get_conversation_messages()` to return:

```python
ConversationMessagesResponse(
    messages=[],
    activeRun={
        "runId": "run-1",
        "status": "running",
        "assistantMessageId": "assistant-1",
        "lastEventId": 12,
    },
)
```

Expected HTTP JSON:

```json
{
  "messages": [],
  "activeRun": {
    "runId": "run-1",
    "status": "running",
    "assistantMessageId": "assistant-1",
    "lastEventId": 12
  }
}
```

- [x] **Step 3: Write failing resume endpoint test**

Create `agent_claude/tests/test_stream_resume.py` with a FastAPI `TestClient` test:

```python
def test_resume_stream_replays_events_after_cursor() -> None:
    from main import app

    async def fake_resume_chat_stream(req):
        yield "id: 13\\ndata: {\"type\":\"delta\",\"runId\":\"run-1\",\"messageId\":\"assistant-1\",\"text\":\"hello\"}\\n\\n"

    with patch("controller.chat.resume_chat_stream", fake_resume_chat_stream):
        response = TestClient(app).post(
            "/api/chat/stream/resume",
            json={"runId": "run-1", "afterEventId": 12},
        )

    assert response.status_code == 200
    assert "id: 13" in response.text
    assert "\"delta\"" in response.text
```

- [x] **Step 4: Write failing edit/regenerate tests**

Create `agent_claude/tests/test_message_edit_regenerate.py` with tests for:

- `PATCH /api/messages/{messageId}` returns edited user message.
- `POST /api/chat/stream` with `parentMessageId` calls the service with `parent_message_id`.
- `POST /api/chat/stream` with `regenerateFromMessageId` calls the service with `regenerate_from_message_id`.

- [x] **Step 5: Write failing approval and cancel tests**

Create `agent_claude/tests/test_approval_flow.py` asserting `POST /api/chat/approval/decisions/{batch_id}` returns SSE rather than 410 when service is patched.

Create `agent_claude/tests/test_cancel_stream.py` asserting `POST /api/chat/streams/{message_id}/cancel` calls service and returns 204.

- [x] **Step 6: Run tests and verify failure**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_history_api tests.test_stream_resume tests.test_message_edit_regenerate tests.test_approval_flow tests.test_cancel_stream -v
```

Expected: failures identify missing schemas, routes, or service functions.

---

## Task 2: Split Chat Stream Responsibilities Without Behavior Change

**Files:**
- Create: `agent_claude/service/sse.py`
- Create: `agent_claude/service/sdk_events.py`
- Create: `agent_claude/service/stream_persistence.py`
- Create: `agent_claude/service/chat_stream.py`
- Modify: `agent_claude/service/chat.py`
- Modify: `agent_claude/tests/test_chat_stream.py`

- [x] **Step 1: Move SSE serialization**

Create `agent_claude/service/sse.py`:

```python
import json
from typing import Any


def to_sse(event: Any, *, event_id: int | None = None) -> str:
    payload = event.model_dump(by_alias=True, exclude_none=True)
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

Replace `_to_sse(...)` calls in `service/chat.py` with `to_sse(...)`.

- [x] **Step 2: Move SDK event parsing**

Create `agent_claude/service/sdk_events.py` and move these functions from `service/chat.py` unchanged:

- `_extract_session_id`
- `_is_content_block_delta_event`
- `_record_tool_call`
- `_record_tool_json_delta`
- `_pop_ready_tool_call`
- `_extract_tool_call`
- `_extract_tool_result`
- `_extract_text_deltas`
- `_extract_thinking_deltas`
- `_extract_result_error_message`
- `_extract_input_json_delta`
- `_extract_content_block_index`
- `_tool_state_key`
- `_calculate_latency_ms`

Import them from `service.chat`.

- [x] **Step 3: Move persistence helpers**

Create `agent_claude/service/stream_persistence.py` and move these functions from `service/chat.py` unchanged:

- `_persist_reasoning_delta`
- `_persist_tool_call`
- `_persist_tool_result`
- `_persist_title`
- `_project_stream_message`
- `_project_tool_invocation`
- `_format_datetime`

Import them from `service.chat`.

- [x] **Step 4: Rename orchestration module**

Create `agent_claude/service/chat_stream.py` containing `_StreamState` and `stream_chat(...)`.

Keep `agent_claude/service/chat.py` as a compatibility wrapper:

```python
from service.chat_stream import stream_chat

__all__ = ["stream_chat"]
```

- [x] **Step 5: Verify no behavior change**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_chat_stream -v
```

Expected: existing chat stream tests pass without changing assertions.

---

## Task 3: Add Run, Event, And Approval Persistence

**Files:**
- Create: `agent_claude/model/agent_run.py`
- Create: `agent_claude/model/agent_run_event.py`
- Create: `agent_claude/model/approval.py`
- Create: `agent_claude/repository/agent_run.py`
- Create: `agent_claude/repository/agent_run_event.py`
- Create: `agent_claude/repository/approval.py`
- Create: `agent_claude/migrations/versions/20260609_0002_create_run_event_approval_tables.py`
- Create: `agent_claude/tests/test_run_models.py`

- [x] **Step 1: Write failing model tests**

`agent_claude/tests/test_run_models.py` must assert:

```python
def test_run_event_and_approval_tables_are_registered() -> None:
    expected = {
        "agent_runs",
        "agent_run_events",
        "approval_batches",
        "approval_requests",
    }
    assert expected.issubset(set(Base.metadata.tables))
```

Also assert `AgentRun.__table__.c.status`, `AgentRun.__table__.c.cancel_requested_at`, `AgentRun.__table__.c.assistant_message_id`, and `AgentRunEvent.__table__.c.id` exist.

- [x] **Step 2: Implement models**

`AgentRun` columns:

- `id: str`
- `conversation_id: str`
- `assistant_message_id: str`
- `status: str`
- `last_event_id: int | None`
- `cancel_requested_at: datetime | None`
- `error: str | None`
- `created_at: datetime`
- `updated_at: datetime`
- `completed_at: datetime | None`

Active statuses:

```python
ACTIVE_RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "resume_queued",
    "resuming",
)
```

`AgentRunEvent` columns:

- `id: BigInteger Identity primary key`
- `run_id: str`
- `conversation_id: str`
- `message_id: str | None`
- `event_type: str`
- `payload: dict`
- `created_at: datetime`

`ApprovalBatch` columns:

- `id: str`
- `run_id: str`
- `message_id: str`
- `status: str`
- `expires_at: datetime`
- `resolved_at: datetime | None`
- `resolution_source: str | None`
- `created_at: datetime`

`ApprovalRequest` columns:

- `id: str`
- `approval_batch_id: str`
- `tool_invocation_id: str`
- `tool_name: str`
- `args: dict`
- `decision: str`
- `decided_at: datetime | None`
- `created_at: datetime`

- [x] **Step 3: Implement repository helpers**

Repository functions:

```python
async def create_run(session, *, run: AgentRun) -> AgentRun: ...
async def get_active_run_by_conversation_id(session, conversation_id: str) -> AgentRun | None: ...
async def get_run_by_id(session, run_id: str) -> AgentRun | None: ...
async def update_run_status(session, *, run_id: str, status: str, error: str | None = None) -> AgentRun: ...
async def request_cancel(session, *, assistant_message_id: str) -> AgentRun | None: ...
async def append_run_event(session, *, event: AgentRunEvent) -> AgentRunEvent: ...
async def list_run_events_after(session, *, run_id: str, after_event_id: int) -> list[AgentRunEvent]: ...
async def create_approval_batch(session, *, batch: ApprovalBatch, requests: list[ApprovalRequest]) -> ApprovalBatch: ...
async def resolve_approval_batch(session, *, batch_id: str, decisions: dict[str, str]) -> ApprovalBatch: ...
```

- [x] **Step 4: Add migration**

Create migration `20260609_0002_create_run_event_approval_tables.py` with four new tables and indexes:

- `ix_agent_runs_conversation_id`
- `ix_agent_runs_assistant_message_id`
- `ix_agent_run_events_run_id_id`
- `ix_approval_batches_run_id`
- `ix_approval_requests_batch_id`

- [x] **Step 5: Verify models and migration**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_run_models -v
mise exec -- uv run alembic upgrade head
```

Expected: tests pass and migration upgrades from current head.

---

## Task 4: Implement Run Event Log, Replay, And Subscription

**Files:**
- Create: `agent_claude/service/run_events.py`
- Create: `agent_claude/tests/test_run_events.py`

- [x] **Step 1: Write failing event log tests**

Create tests for:

- Appending an event returns an integer `event_id`.
- `format_persisted_event()` emits SSE with `id:`.
- `replay_events_after(run_id, after_event_id)` skips older events.

- [x] **Step 2: Implement event formatter**

`service/run_events.py`:

```python
from collections.abc import AsyncIterator
from service.sse import to_sse


def format_persisted_event(event) -> str:
    return to_sse(event.payload_model, event_id=event.id)
```

Use a helper to convert `event.payload` back into `ChatStreamEvent` via `schema.chat.ChatStreamEventAdapter`.

- [x] **Step 3: Implement in-process subscription registry**

Create a module-level registry:

```python
_subscribers: dict[str, set[asyncio.Queue[int]]] = {}
```

When an event is appended, push its id to queues for that run. Subscribers load event rows by id before yielding SSE.

- [x] **Step 4: Implement replay plus live subscribe**

Public function:

```python
async def stream_run_events(*, run_id: str, after_event_id: int) -> AsyncIterator[str]:
    for event in await load_events_after(run_id, after_event_id):
        yield format_persisted_event(event)
    async for event in subscribe_to_live_events(run_id):
        yield format_persisted_event(event)
```

Break when run status is terminal and all events after cursor have been yielded.

- [x] **Step 5: Verify run event tests**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_run_events -v
```

Expected: event replay and live subscription tests pass.

---

## Task 5: Implement ActiveRun, Stream Resume, And Background Execution

**Files:**
- Create: `agent_claude/service/run_manager.py`
- Modify: `agent_claude/service/chat_stream.py`
- Modify: `agent_claude/service/history.py`
- Modify: `agent_claude/controller/chat.py`
- Modify: `agent_claude/schema/chat.py`
- Modify: `agent_claude/main.py`
- Modify: `agent_claude/tests/test_stream_resume.py`
- Modify: `agent_claude/tests/test_history_api.py`

- [x] **Step 1: Add schema types**

Add Pydantic models:

```python
class ActiveRunSummary(FrontendModel):
    run_id: str = Field(alias="runId")
    status: Literal["queued", "running", "awaiting_approval", "resume_queued", "resuming", "completed", "failed"]
    last_event_id: int | None = Field(default=None, alias="lastEventId")
    assistant_message_id: str = Field(alias="assistantMessageId")
    approval_batch: ApprovalBatch | None = Field(default=None, alias="approvalBatch")


class ChatStreamResumeRequest(FrontendModel):
    run_id: str = Field(alias="runId")
    after_event_id: int = Field(alias="afterEventId")
```

Change `ConversationMessagesResponse.active_run` from `None` to `ActiveRunSummary | None`.

- [x] **Step 2: Create run before execution**

`run_manager.start_chat_run(...)` must:

1. Validate conversation.
2. Create or reuse user message according to request mode.
3. Create assistant message with status `streaming`.
4. Create `AgentRun(status="running")`.
5. Append `run_created`.
6. Append `message_created`.
7. Start an asyncio task that consumes Claude SDK and appends persisted events.
8. Return `stream_run_events(run_id=run.id, after_event_id=0)`.

- [x] **Step 3: Persist every SSE event**

The executor must append these event types before yielding to subscribers:

- `run_created`
- `message_created`
- `reasoning`
- `tool_call`
- `tool_result`
- `delta`
- `title`
- `done`
- `error`

Each event payload must include `runId` when the frontend type requires it.

- [x] **Step 4: Implement resume endpoint**

Controller:

```python
async def resume_stream_chat(req: ChatStreamResumeRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_run_events(run_id=req.run_id, after_event_id=req.after_event_id),
        media_type="text/event-stream",
    )
```

Route:

```python
app.add_api_route("/api/chat/stream/resume", resume_stream_chat, methods=["POST"], response_model=None)
```

- [x] **Step 5: Project activeRun in history**

`history.get_conversation_messages(...)` must query `get_active_run_by_conversation_id(...)`. If active run exists, return:

```python
ActiveRunSummary(
    run_id=run.id,
    status=run.status,
    last_event_id=run.last_event_id,
    assistant_message_id=run.assistant_message_id,
    approval_batch=current_pending_batch_or_none,
)
```

- [x] **Step 6: Verify resume and history tests**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_stream_resume tests.test_history_api -v
```

Expected: activeRun is returned for active runs and resume emits event IDs.

---

## Task 6: Implement Edit, Parent Continuation, And Regenerate

**Files:**
- Modify: `agent_claude/repository/message.py`
- Modify: `agent_claude/controller/chat.py`
- Modify: `agent_claude/schema/chat.py`
- Modify: `agent_claude/service/chat_stream.py`
- Modify: `agent_claude/main.py`
- Modify: `agent_claude/tests/test_message_edit_regenerate.py`

- [x] **Step 1: Implement edit message route**

Add schema:

```python
class EditMessageRequest(BaseModel):
    content: str
```

Controller must reject blank content and non-user messages with `400`.

Route:

```python
app.add_api_route("/api/messages/{message_id}", edit_message, methods=["PATCH"], response_model=None)
```

- [x] **Step 2: Add repository helpers**

Add:

```python
async def edit_user_message(session, *, message_id: str, content: str) -> Message: ...
async def delete_messages_after_seq(session, *, conversation_id: str, seq: int) -> None: ...
async def get_previous_user_message_before_seq(session, *, conversation_id: str, seq: int) -> Message | None: ...
async def get_message_in_conversation(session, *, conversation_id: str, message_id: str) -> Message | None: ...
```

- [x] **Step 3: Implement `parentMessageId` semantics**

When `StreamChatRequest.parent_message_id` exists:

1. Load that message.
2. Require role `user`.
3. Delete messages with larger `seq` in the same conversation.
4. Invalidate the conversation's `agent_session` mapping so Claude SDK does not continue an old branch.
5. Use edited parent content as the prompt.
6. Do not create a duplicate user message.

- [x] **Step 4: Implement `regenerateFromMessageId` semantics**

When `StreamChatRequest.regenerate_from_message_id` exists:

1. Load that message.
2. Require role `assistant`.
3. Find the nearest previous user message.
4. Delete the target assistant message and later messages.
5. Invalidate the conversation's `agent_session` mapping.
6. Use previous user message content as the prompt.
7. Do not create an empty user message.

- [x] **Step 5: Use linear history for branch restart**

For normal send, continue using `resume=sdk_session_id`.

For edit/regenerate branch restart, start Claude SDK without `resume`. Build a compact prompt from persisted messages that remain before the new assistant message:

```text
Previous conversation:
User: ...
Assistant: ...

Current user request:
...
```

This is necessary because the existing SDK session transcript contains the deleted branch.

- [x] **Step 6: Verify edit/regenerate tests**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_message_edit_regenerate -v
```

Expected: edit route returns updated user message; parent/regenerate do not create duplicate user messages and do invalidate old SDK session.

---

## Task 7: Implement Cancel Stream

**Files:**
- Modify: `agent_claude/service/run_manager.py`
- Modify: `agent_claude/controller/chat.py`
- Modify: `agent_claude/main.py`
- Modify: `agent_claude/tests/test_cancel_stream.py`

- [x] **Step 1: Implement run registry cancellation**

`RunManager` keeps:

```python
_tasks_by_run_id: dict[str, asyncio.Task[None]]
_run_id_by_assistant_message_id: dict[str, str]
```

`cancel_run_by_assistant_message_id(message_id)` must:

1. Mark run `cancel_requested_at`.
2. Cancel live task if present.
3. Persist assistant message with current partial content and status `done`.
4. Append `done`.
5. Mark run status `completed`.

- [x] **Step 2: Add route**

Controller:

```python
async def cancel_chat_stream(message_id: str) -> Response:
    await cancel_run_by_assistant_message_id(message_id)
    return Response(status_code=204)
```

Route:

```python
app.add_api_route("/api/chat/streams/{message_id}/cancel", cancel_chat_stream, methods=["POST"], response_model=None)
```

- [x] **Step 3: Verify cancellation test**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_cancel_stream -v
```

Expected: route returns 204 and run status becomes terminal.

---

## Task 8: Implement Approval Flow And Error/Config Boundaries

**Files:**
- Create: `agent_claude/service/approval_gate.py`
- Modify: `agent_claude/service/runtime.py`
- Modify: `agent_claude/service/run_manager.py`
- Modify: `agent_claude/controller/chat.py`
- Modify: `agent_claude/core/config.py`
- Modify: `agent_claude/tests/test_approval_flow.py`
- Modify: `agent_claude/tests/test_runtime.py`

- [x] **Step 1: Add approval config**

Add settings:

```python
approval_required_tools: tuple[str, ...]
```

Read from:

```text
AGENT_CLAUDE_APPROVAL_TOOLS=WebFetch,Grep
```

Default is an empty tuple. Empty means approval infrastructure is available but no default read-only tool is paused.

Important SDK constraint: in `claude-agent-sdk 0.2.91`, `can_use_tool` is invoked only when CLI permission resolution reaches `ask`. Tools already listed in `allowed_tools` are auto-approved and do not enter `can_use_tool`. Therefore any tool configured in `AGENT_CLAUDE_APPROVAL_TOOLS` must be removed from `allowed_tools` and handled through `can_use_tool`, otherwise approval UI will never be reached.

- [x] **Step 2: Add Claude SDK permission gate**

`approval_gate.py` exposes:

```python
def build_can_use_tool(run_context: RunContext):
    async def can_use_tool(tool_name, tool_input, context):
        if tool_name not in run_context.approval_required_tools:
            return PermissionResultAllow()
        batch = await create_and_emit_approval_required(run_context, tool_name, tool_input)
        decision = await wait_for_approval_decision(batch.id)
        if decision == "approve":
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message="Tool execution rejected by user")
    return can_use_tool
```

Use the installed SDK dataclasses, not plain dictionaries:

```python
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
```

`PermissionResultAllow()` allows the tool, `PermissionResultAllow(updated_input=...)` allows with edited input, and `PermissionResultDeny(message=...)` denies.

- [x] **Step 3: Emit `approval_required` event**

When the permission gate pauses a tool:

1. Create pending `ApprovalBatch`.
2. Create one `ApprovalRequest`.
3. Append `approval_required` run event with a timeline `approval` part.
4. Set run status `awaiting_approval`.
5. Wait for decision from `POST /api/chat/approval/decisions/{batch_id}`.

- [x] **Step 4: Implement approval decision route**

Controller accepts:

```python
class SubmitApprovalDecisionsRequest(FrontendModel):
    decisions: list[ApprovalDecisionRequest]
    after_event_id: int = Field(alias="afterEventId")
```

Behavior:

1. Validate all requests in the batch have one decision.
2. Persist decisions.
3. Append `approval_resolved`.
4. Set run status `resuming`.
5. Resolve in-process approval future.
6. Return `stream_run_events(run_id=batch.run_id, after_event_id=req.after_event_id)`.

- [x] **Step 5: Add safe error boundary**

Any unexpected exception in run execution must:

1. Log exception with stack trace.
2. Persist assistant status `error`.
3. Append error event with safe message:

```text
Agent run failed. Check server logs for details.
```

4. Mark run `failed`.

Do not send `str(exc)` to the client.

- [x] **Step 6: Add config validation**

Add:

```python
def validate_runtime_settings() -> None:
    settings = get_settings()
    if not settings.anthropic_auth_token:
        raise RuntimeError("ANTHROPIC_AUTH_TOKEN is required")
    if not settings.anthropic_model:
        raise RuntimeError("ANTHROPIC_MODEL is required")
```

Call this from app startup or before `ClaudeAgentOptions` is built. Tests should patch settings to avoid requiring real secrets.

- [x] **Step 7: Verify approval and runtime tests**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
mise exec -- uv run python -m unittest tests.test_approval_flow tests.test_runtime -v
```

Expected: approval route emits `approval_resolved`; runtime tests verify safe errors and config validation.

---

## Task 9: Update Frontend Contracts And Tests

**Files:**
- Modify: `web/features/chat/types.ts`
- Modify: `web/features/chat/api.ts`
- Modify: `web/features/chat/store.ts`
- Modify: `web/features/chat/api.test.ts`
- Modify: `web/features/chat/store.test.ts`

- [x] **Step 1: Keep endpoint paths stable**

Do not change these frontend paths:

- `/api/chat/stream`
- `/api/chat/stream/resume`
- `/api/chat/approval/decisions/{batchId}`
- `/api/messages/{messageId}`
- `/api/chat/streams/{messageId}/cancel`

The backend must adapt to the current frontend surface.

- [x] **Step 2: Add error payload parsing**

`ChatApiError` should preserve status and optional backend `message/detail` text. Store-facing error text remains user-safe.

- [x] **Step 3: Align activeRun handling**

Ensure `selectConversation()` resumes only when `activeRun.status` is `queued`, `running`, `resume_queued`, or `resuming`. It must not resume `awaiting_approval`.

- [x] **Step 4: Verify frontend unit tests**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/web
pnpm exec tsx --test features/chat/api.test.ts features/chat/store.test.ts features/chat/chat-event-reducer.test.ts
pnpm lint
```

Expected: chat API/store/reducer tests pass and Biome reports no errors.

---

## Task 10: Update Docs And Split Tests

**Files:**
- Modify: `docs/project/ARCHITECTURE.md`
- Modify: `docs/project/PLAN_CHAT.md`
- Modify: `README.md`
- Modify: `agent_claude/tests/test_chat_stream.py`
- Create: `agent_claude/tests/test_sdk_events.py`
- Create: `agent_claude/tests/test_stream_persistence.py`
- Create: `agent_claude/tests/test_sse.py`

- [x] **Step 1: Update architecture docs**

`docs/project/ARCHITECTURE.md` must state:

- Current chain is still `web -> agent_claude`.
- Go service is not in the current runtime path.
- Go future role is business BFF only.
- `agent_claude` now owns run/event/approval state for the Python Agent path.
- `agent_runs` and `agent_run_events` are frontend run state and SSE replay storage.
- Claude SDK `SessionStore` is agent transcript storage.
- These two storage layers are not substitutes.

- [x] **Step 2: Update chat plan docs**

`docs/project/PLAN_CHAT.md` must mark:

- Basic chat complete.
- Tool permission hardening complete.
- Frontend feature parity implemented after this plan is executed.
- Go BFF/RPC deferred until a real business API requires it.

- [x] **Step 3: Split tests by responsibility**

Move tests from `test_chat_stream.py`:

- SDK parsing tests -> `test_sdk_events.py`
- Persistence projection tests -> `test_stream_persistence.py`
- SSE formatting tests -> `test_sse.py`
- End-to-end stream orchestration tests remain in `test_chat_stream.py`

- [x] **Step 4: Run full verification**

Run:

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant
make test-dev-config
cd agent_claude
mise exec -- uv run python -m unittest discover -s tests -p 'test_*.py' -v
cd ../web
pnpm exec tsx --test features/chat/api.test.ts features/chat/store.test.ts features/chat/chat-event-reducer.test.ts
pnpm lint
```

Expected:

- Dev config checks pass.
- `agent_claude` tests pass.
- Frontend chat tests pass.
- Biome lint passes.

---

## Acceptance Criteria

- `agent_claude` 默认工具权限仍不包含 `Task/Write/Edit/Bash`。
- 所有当前前端调用的 chat endpoints 在 `agent_claude` 中都有对应 route。
- `activeRun` 来自真实 `agent_runs`，不是 mock 或固定 `None`。
- `resume` 能按 `afterEventId` replay 已持久化事件。
- 普通正在运行的 run 可以被 resume endpoint 继续订阅。
- `approval_required` 和 `approval_resolved` 能被前端 reducer 正确消费。
- `PATCH /api/messages/{messageId}` 只允许编辑 user message。
- `parentMessageId` 和 `regenerateFromMessageId` 不再被忽略。
- cancel 会关闭 active run，并把 assistant message 从 `streaming` 变成终态。
- 客户端错误文案不包含原始异常。
- 缺少关键 Anthropic 配置时快速失败。
- `service/chat.py` 不再承载 SDK 解析、SSE、持久化、run 管理全部职责。
- 文档明确当前 Python Agent 与未来 Go BFF/RPC 的边界。

## Execution Order

1. Task 1: Contract tests.
2. Task 2: Mechanical split with no behavior change.
3. Task 3: Run/event/approval persistence.
4. Task 4: Event replay and subscription.
5. Task 5: ActiveRun and resume.
6. Task 6: Edit/regenerate/parent semantics.
7. Task 7: Cancel.
8. Task 8: Approval, error boundary, config validation.
9. Task 9: Frontend contract tests.
10. Task 10: Docs and test split.

## Risk Notes

- `regenerateFromMessageId` and `parentMessageId` require invalidating old Claude SDK session state. If this is skipped, the model may continue from deleted branch content.
- `resume` is a frontend SSE replay/subscription capability. It is not the same as Claude SDK transcript resume.
- Approval with Claude SDK depends on permission resolution. `can_use_tool` does not run for tools in `allowed_tools`, so approval-required tools must be withheld from the default allowlist and returned through `PermissionResultAllow` / `PermissionResultDeny`.
- In-process run tasks survive frontend refresh but not service restart. Restart handling must mark active runs as `failed` on startup or first query so the UI does not show a permanently running state.
- Full crash-safe mid-run resume requires a durable workflow/checkpoint runtime and is a later Python Agent runtime decision, not a Go BFF responsibility.

## Self-Review

- Spec coverage: all previously identified missing and half-implemented frontend capabilities map to one or more tasks.
- Placeholder scan: this plan does not rely on unspecified future work for current frontend parity.
- Type consistency: frontend field names remain camelCase at API boundaries; Python internal names remain snake_case with Pydantic aliases.
- Scope check: Go BFF/RPC and Eino remain outside this implementation plan.
