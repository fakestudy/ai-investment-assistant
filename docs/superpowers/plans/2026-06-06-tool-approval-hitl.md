# 生产级工具审批 HITL 实施计划

> **供 Agent 执行者使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项实施。所有步骤使用复选框（`- [ ]`）跟踪。

**目标：** 为 Python Agent 对话链路实现生产级工具审批 HITL：仅白名单工具 `get_weather` 需要审批，仅支持批准/拒绝，审批 30 分钟自动过期，并支持跨刷新、跨服务重启的恢复、回放和历史审计。

**架构：** PostgreSQL 保存业务实体、SSE 事件日志和 Transactional Outbox，LangGraph PostgreSQL Checkpointer 保存可恢复执行状态，RabbitMQ 只负责至少一次投递启动、恢复和超时命令。HTTP API 只创建事务并订阅持久化事件；独立 worker 消费命令并驱动 LangGraph；前端以会话为维度维护运行状态和连接控制器。

**技术栈：** FastAPI、SQLAlchemy 2、Alembic、LangGraph、`langgraph-checkpoint-postgres`、PostgreSQL、RabbitMQ、`aio-pika`、SSE、Next.js 16、React 19、TypeScript、Zustand、Node Test Runner。

**设计依据：** `docs/superpowers/specs/2026-06-06-tool-approval-hitl-design.md`

---

## 文件边界

后端按责任拆分，避免继续扩张现有 `agent/service/chat.py`：

- `agent/model/agent_run.py`：运行状态、租约和单会话活跃运行约束。
- `agent/model/approval.py`：审批批次与逐项请求。
- `agent/model/agent_run_event.py`：可回放 SSE 事件。
- `agent/model/outbox_event.py`：事务消息。
- `agent/schema/chat.py`：前后端共用的运行、审批、SSE Pydantic 契约。
- `agent/repository/*.py`：只负责 SQL 查询、锁和持久化，不做流程编排。
- `agent/service/chat_run.py`：创建运行和历史输入快照。
- `agent/service/run_events.py`：事件写入、回放、稳定边界判断和 PostgreSQL 通知。
- `agent/service/approval.py`：人工决策和超时竞争事务。
- `agent/service/agent_factory.py`：模型、中间件、白名单和 checkpointer 组装。
- `agent/worker/run_executor.py`：LangGraph 启动/恢复和流事件投影。
- `agent/worker/outbox_publisher.py`：Outbox 发布。
- `agent/worker/command_consumer.py`：RabbitMQ 消费、租约和幂等控制。
- `agent/worker/main.py`：worker 进程入口。

前端按契约、状态和视图拆分：

- `web/features/chat/types.ts`：运行、审批、历史和 SSE 类型。
- `web/features/chat/api.ts`：三个 POST SSE 接口与 SSE `id` 解析。
- `web/features/chat/chat-event-reducer.ts`：按事件 ID 幂等归并消息和审批状态。
- `web/features/chat/store.ts`：每个会话独立的运行状态和 `AbortController`。
- `web/features/chat/components/approval-card.tsx`：批准/拒绝选择与提交。
- `web/features/chat/components/chat-message-timeline.tsx`：在持久化位置渲染审批卡。

---

### 任务 1：接入 RabbitMQ、Checkpointer 和独立进程配置

**文件：**
- 修改：`agent/pyproject.toml`
- 修改：`agent/uv.lock`
- 修改：`.env.example`
- 修改：`docker-compose.yml`
- 修改：`scripts/dev-start.sh`
- 修改：`scripts/dev-stop.sh`
- 修改：`scripts/check-dev.sh`
- 修改：`scripts/test-dev-config.sh`
- 修改：`Makefile`

- [ ] **步骤 1：先扩展脚本契约测试**

在 `scripts/test-dev-config.sh` 增加断言，明确本地环境必须启动 RabbitMQ、API、worker 和 outbox publisher：

```bash
assert_contains "$REPO_ROOT/docker-compose.yml" 'rabbitmq:' \
  "docker-compose.yml must define rabbitmq"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'worker.main' \
  "dev-start.sh must start agent worker"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'outbox_publisher' \
  "dev-start.sh must start outbox publisher"
assert_contains "$REPO_ROOT/scripts/dev-stop.sh" 'investment-rabbitmq' \
  "dev-stop.sh must stop rabbitmq"
assert_contains "$REPO_ROOT/.env.example" 'RABBITMQ_URL=' \
  ".env.example must define RABBITMQ_URL"
```

- [ ] **步骤 2：运行测试并确认按预期失败**

运行：

```bash
make test-dev-config
```

预期：失败信息指出缺少 RabbitMQ 服务、worker 入口或 `RABBITMQ_URL`。

- [ ] **步骤 3：增加依赖与配置**

执行：

```bash
cd agent
uv add "aio-pika>=9.5,<10" "langgraph-checkpoint-postgres>=3,<4"
```

在 `.env.example` 增加：

```dotenv
RABBITMQ_URL=amqp://investment:investment@localhost:5672/
AGENT_WORKER_ID=local-worker-1
AGENT_RUN_LEASE_SECONDS=60
OUTBOX_POLL_INTERVAL_MS=250
```

在 `docker-compose.yml` 增加 `rabbitmq:4-management`，配置持久卷、健康检查、管理端口 `15672`、AMQP 端口 `5672`，并设置默认用户名和密码为 `investment`。

- [ ] **步骤 4：把本地进程拆为 API、worker、outbox publisher**

`scripts/dev-start.sh` 新增独立 PID 和日志：

```bash
AGENT_API_PID_FILE="$RUN_DIR/agent-api.pid"
AGENT_WORKER_PID_FILE="$RUN_DIR/agent-worker.pid"
OUTBOX_PID_FILE="$RUN_DIR/outbox-publisher.pid"

nohup env PYTHONPYCACHEPREFIX=../.pycache uv run python main.py \
  >"$AGENT_API_LOG" 2>&1 &
nohup env PYTHONPYCACHEPREFIX=../.pycache uv run python -m worker.main \
  >"$AGENT_WORKER_LOG" 2>&1 &
nohup env PYTHONPYCACHEPREFIX=../.pycache uv run python -m worker.outbox_publisher \
  >"$OUTBOX_LOG" 2>&1 &
```

启动顺序固定为 PostgreSQL/RabbitMQ 健康后启动三个 Python 进程，再启动 Web。`scripts/dev-stop.sh` 对称停止三个 PID 与 RabbitMQ 容器。`make agent-dev` 只启动 API；新增 `agent-worker` 和 `outbox-publisher` 目标。

- [ ] **步骤 5：验证脚本**

运行：

```bash
make test-dev-config
docker compose config --quiet
```

预期：两条命令退出码均为 `0`。

- [ ] **步骤 6：提交**

```bash
git add agent/pyproject.toml agent/uv.lock .env.example docker-compose.yml \
  scripts/dev-start.sh scripts/dev-stop.sh scripts/check-dev.sh \
  scripts/test-dev-config.sh Makefile
git commit -m "build(agent): 接入 HITL 运行依赖与进程角色"
```

---

### 任务 2：建立运行、审批、事件和 Outbox 数据模型

**文件：**
- 新建：`agent/model/agent_run.py`
- 新建：`agent/model/approval.py`
- 新建：`agent/model/agent_run_event.py`
- 新建：`agent/model/outbox_event.py`
- 修改：`agent/model/message.py`
- 修改：`agent/model/message_part.py`
- 修改：`agent/model/tool_invocation.py`
- 修改：`agent/migrations/env.py`
- 新建：`agent/migrations/versions/<revision>_create_agent_hitl_tables.py`
- 新建：`agent/tests/test_hitl_models.py`

- [ ] **步骤 1：写模型与索引失败测试**

`agent/tests/test_hitl_models.py` 必须验证：

```python
def test_agent_run_has_required_state_and_lease_columns() -> None:
    assert set(AgentRun.__table__.columns.keys()) >= {
        "id", "conversation_id", "user_message_id", "assistant_message_id",
        "status", "version", "lease_owner", "lease_expires_at",
        "active_command_id", "error", "created_at", "updated_at", "completed_at",
    }

def test_message_part_can_reference_approval_batch() -> None:
    assert MessagePart.__table__.c.approval_batch_id.nullable

def test_active_run_unique_index_is_partial() -> None:
    index = next(
        item for item in AgentRun.__table__.indexes
        if item.name == "uq_agent_runs_active_conversation"
    )
    assert index.unique is True
    assert "awaiting_approval" in str(index.dialect_options["postgresql"]["where"])
```

同时断言：

- `approval_batches(agent_run_id, sequence)` 唯一。
- `approval_requests(approval_batch_id, order_index)` 唯一。
- `agent_run_events.id` 为单调递增 bigint。
- `outbox_events.id` 同时作为 MQ `message_id`。
- `tool_invocations.status` 数据库层不限制旧值，但应用类型覆盖六种状态。

- [ ] **步骤 2：运行模型测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_hitl_models -v
```

预期：因模型模块不存在而失败。

- [ ] **步骤 3：实现 SQLAlchemy 模型**

`AgentRun` 的活跃状态常量固定为：

```python
ACTIVE_RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "resume_queued",
    "resuming",
)
```

局部唯一索引：

```python
Index(
    "uq_agent_runs_active_conversation",
    "conversation_id",
    unique=True,
    postgresql_where=text(
        "status IN ('queued','running','awaiting_approval','resume_queued','resuming')"
    ),
)
```

`ApprovalRequest` 保存 `tool_name` 和 `args` 快照；`MessagePart.approval_batch_id` 使用 `ON DELETE SET NULL`；所有时间列使用带时区时间。

- [ ] **步骤 4：生成并审查 Alembic 迁移**

```bash
cd agent
uv run alembic revision --autogenerate -m "create agent hitl tables"
```

人工检查迁移包含五张新表、两个新外键、所需唯一索引和降级反向操作，不允许 Alembic 删除现有列。

- [ ] **步骤 5：执行模型和迁移验证**

```bash
cd agent
uv run python -m unittest tests.test_hitl_models tests.test_message_model -v
uv run alembic upgrade head
uv run alembic check
```

预期：测试全部通过，数据库升级成功，`alembic check` 输出无新迁移。

- [ ] **步骤 6：提交**

```bash
git add agent/model agent/migrations agent/tests/test_hitl_models.py \
  agent/tests/test_message_model.py
git commit -m "feat(agent): 建立 HITL 运行与审批实体"
```

---

### 任务 3：定义统一的后端审批、运行和历史契约

**文件：**
- 修改：`agent/schema/chat.py`
- 修改：`agent/schema/chat_conversations.py`
- 新建：`agent/tests/test_hitl_schemas.py`

- [ ] **步骤 1：写契约序列化失败测试**

测试必须覆盖：

```python
def test_approval_timeline_part_uses_frontend_aliases() -> None:
    payload = ApprovalTimelinePart(
        id="part-1",
        type="approval",
        order_index=2,
        batch=ApprovalBatchPayload(
            id="batch-1",
            status="pending",
            expires_at="2026-06-06T12:30:00Z",
            requests=[],
        ),
    ).model_dump(by_alias=True)
    assert payload["orderIndex"] == 2
    assert payload["batch"]["expiresAt"].endswith("Z")

def test_decision_request_accepts_only_approve_or_reject() -> None:
    with self.assertRaises(ValidationError):
        ApprovalDecisionRequest.model_validate({
            "decisions": [{"approvalRequestId": "r1", "decision": "edit"}],
            "afterEventId": 1,
        })
```

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_hitl_schemas -v
```

预期：缺少审批和运行 schema。

- [ ] **步骤 3：实现统一类型**

必须定义并复用：

```python
ApprovalDecision = Literal["pending", "approved", "rejected", "expired"]
ApprovalSubmissionDecision = Literal["approve", "reject"]
RunStatus = Literal[
    "queued", "running", "awaiting_approval",
    "resume_queued", "resuming", "completed", "failed",
]
```

新增：

- `ApprovalRequestPayload`
- `ApprovalBatchPayload`
- `ApprovalTimelinePart`
- `ActiveRunSummary`
- `ConversationMessagesResponse`，字段为 `messages` 和 `activeRun`
- `RunCreatedEvent`
- `ApprovalRequiredEvent`
- `ApprovalResolvedEvent`
- `ChatStreamResumeRequest`
- `ApprovalDecisionRequest`

所有持久化 SSE 事件都必须含 `runId`。`ChatStreamResponse` 的 discriminator 联合类型加入三个新事件。

- [ ] **步骤 4：运行 schema 回归测试**

```bash
cd agent
uv run python -m unittest tests.test_hitl_schemas tests.test_chat_stream -v
```

预期：全部通过。

- [ ] **步骤 5：提交**

```bash
git add agent/schema agent/tests/test_hitl_schemas.py
git commit -m "feat(agent): 定义 HITL 前后端统一契约"
```

---

### 任务 4：原子创建运行和启动 Outbox 命令

**文件：**
- 新建：`agent/repository/agent_run.py`
- 新建：`agent/repository/outbox_event.py`
- 新建：`agent/service/chat_run.py`
- 修改：`agent/controller/chat.py`
- 修改：`agent/main.py`
- 新建：`agent/tests/test_chat_run_service.py`

- [ ] **步骤 1：写事务边界失败测试**

使用真实 PostgreSQL 测试：

```python
async def test_create_run_commits_messages_run_and_outbox_together() -> None:
    result = await create_chat_run(session, request, id_factory=fake_ids)
    assert result.run.status == "queued"
    assert result.outbox.event_type == "agent.run.start"
    assert result.outbox.aggregate_id == result.run.id

async def test_second_active_run_in_same_conversation_conflicts() -> None:
    await create_chat_run(session, request, id_factory=fake_ids)
    with self.assertRaises(ConversationRunConflict):
        await create_chat_run(session, request, id_factory=other_ids)
```

增加回滚测试：在 Outbox `flush` 注入异常后，用户消息、助手消息和 `agent_runs` 均不存在。

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_chat_run_service -v
```

预期：缺少 `create_chat_run`。

- [ ] **步骤 3：实现单事务创建**

`create_chat_run()` 在调用方提供的一个 `AsyncSession` 中创建：

```python
ChatRunCreation(
    user_message=user_message,
    assistant_message=assistant_message,
    run=AgentRun(status="queued", version=0, ...),
    outbox=OutboxEvent(
        event_type="agent.run.start",
        aggregate_id=run_id,
        payload={"runId": run_id},
        status="pending",
        attempt_count=0,
        available_at=now,
    ),
)
```

捕获活跃运行唯一索引冲突并映射为 `409`。HTTP 层不得直接发布 RabbitMQ。

- [ ] **步骤 4：将 `/api/chat/stream` 改为创建后订阅**

控制器只做：

```python
creation = await create_chat_run(session, req)
await session.commit()
return StreamingResponse(
    stream_run_events(creation.run.id, after_event_id=0),
    media_type="text/event-stream",
)
```

数据库事务失败时在返回 `StreamingResponse` 前返回 HTTP 错误。

- [ ] **步骤 5：验证事务测试**

```bash
cd agent
uv run python -m unittest tests.test_chat_run_service -v
```

预期：全部通过。

- [ ] **步骤 6：提交**

```bash
git add agent/repository/agent_run.py agent/repository/outbox_event.py \
  agent/service/chat_run.py agent/controller/chat.py agent/main.py \
  agent/tests/test_chat_run_service.py
git commit -m "feat(agent): 原子创建对话运行与启动命令"
```

---

### 任务 5：实现持久化 SSE 事件日志与 POST 回放

**文件：**
- 新建：`agent/repository/agent_run_event.py`
- 新建：`agent/service/run_events.py`
- 修改：`agent/controller/chat.py`
- 修改：`agent/main.py`
- 新建：`agent/tests/test_run_event_stream.py`

- [ ] **步骤 1：写事件顺序和回放失败测试**

覆盖：

```python
async def test_append_event_assigns_monotonic_ids() -> None:
    first = await append_run_event(session, run_id, "run_created", payload)
    second = await append_run_event(session, run_id, "message_created", payload2)
    assert second.id > first.id

async def test_replay_returns_only_events_after_cursor() -> None:
    events = await list_run_events_after(session, run_id, after_event_id=first.id)
    assert [event.id for event in events] == [second.id]

def test_sse_frame_contains_id_and_run_id() -> None:
    frame = format_persisted_sse(event)
    assert frame.startswith(f"id: {event.id}\n")
    assert '"runId":"run-1"' in frame
```

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_run_event_stream -v
```

- [ ] **步骤 3：实现事件写入与通知**

每次事件插入和业务投影在同一事务中；提交后执行：

```sql
SELECT pg_notify('agent_run_events', :run_id)
```

`stream_run_events(run_id, after_event_id)` 循环执行：

1. 查询 `id > cursor` 的事件并按 `id ASC` 输出。
2. 更新 cursor。
3. 遇到 `done`、`error` 或 `approval_required` 后结束当前 HTTP 流。
4. 无事件时等待 PostgreSQL `LISTEN agent_run_events` 通知。
5. 每 15 秒输出 SSE comment `: heartbeat\n\n`，但不改变 cursor。

通知只负责唤醒；数据库查询才是事实来源，避免通知丢失导致事件丢失。

- [ ] **步骤 4：实现 POST 回放接口**

注册：

```python
api_router.post("/chat/stream/resume")(resume_stream_chat)
```

请求体：

```json
{"runId":"run-1","afterEventId":42}
```

接口验证 Run 存在后调用同一个 `stream_run_events()`，不得执行 LangGraph `Command(resume=...)`。

- [ ] **步骤 5：验证**

```bash
cd agent
uv run python -m unittest tests.test_run_event_stream -v
```

预期：事件 ID、游标过滤、稳定边界和 POST 路由测试全部通过。

- [ ] **步骤 6：提交**

```bash
git add agent/repository/agent_run_event.py agent/service/run_events.py \
  agent/controller/chat.py agent/main.py agent/tests/test_run_event_stream.py
git commit -m "feat(agent): 持久化并回放运行 SSE 事件"
```

---

### 任务 6：配置 PostgreSQL Checkpointer 和审批白名单 Agent

**文件：**
- 新建：`agent/core/checkpointer.py`
- 新建：`agent/service/agent_factory.py`
- 修改：`agent/service/chat.py`
- 修改：`agent/main.py`
- 新建：`agent/tests/test_agent_factory.py`

- [ ] **步骤 1：写白名单和 checkpointer 失败测试**

```python
def test_only_weather_requires_approve_or_reject() -> None:
    config = build_hitl_interrupt_config()
    assert config == {
        "get_weather": {"allowed_decisions": ["approve", "reject"]}
    }

def test_agent_receives_postgres_checkpointer() -> None:
    agent = build_agent(checkpointer=sentinel.checkpointer, model=fake_model)
    assert captured_create_agent_kwargs["checkpointer"] is sentinel.checkpointer
```

不得把 `get_deepseek_balance` 放入审批配置。

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_agent_factory -v
```

- [ ] **步骤 3：实现 checkpointer 生命周期**

`agent/core/checkpointer.py` 提供：

```python
@asynccontextmanager
async def open_checkpointer(database_url: str):
    async with AsyncPostgresSaver.from_conn_string(
        to_psycopg_url(database_url)
    ) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
```

FastAPI lifespan 只初始化 API 需要的共享资源；worker 进程单独初始化自己的 checkpointer，不共享跨进程对象。

- [ ] **步骤 4：抽离 Agent factory**

`build_agent()` 保留现有 PII middleware 和工具，只将 HITL 配置改为：

```python
HumanInTheLoopMiddleware(
    interrupt_on={
        "get_weather": {
            "allowed_decisions": ["approve", "reject"],
        }
    }
)
```

并把 `checkpointer` 传给 `create_agent()`。删除 `agent/service/chat.py` 中重复的 `get_agent()`，但暂时保留纯事件解析 helper，后续 worker 复用。

- [ ] **步骤 5：验证**

```bash
cd agent
uv run python -m unittest tests.test_agent_factory tests.test_deepseek_tools -v
```

- [ ] **步骤 6：提交**

```bash
git add agent/core/checkpointer.py agent/service/agent_factory.py \
  agent/service/chat.py agent/main.py agent/tests/test_agent_factory.py
git commit -m "feat(agent): 接入可恢复检查点与工具审批白名单"
```

---

### 任务 7：实现 Agent worker 的启动执行和事件投影

**文件：**
- 新建：`agent/worker/__init__.py`
- 新建：`agent/worker/run_executor.py`
- 新建：`agent/service/stream_projection.py`
- 修改：`agent/service/chat.py`
- 新建：`agent/tests/test_run_executor.py`
- 修改：`agent/tests/test_chat_stream.py`

- [ ] **步骤 1：写双流模式和持久化顺序失败测试**

```python
async def test_start_uses_run_id_as_thread_id_and_both_stream_modes() -> None:
    await executor.execute_start(command)
    fake_agent.astream.assert_called_once_with(
        {"messages": expected_messages},
        config={"configurable": {"thread_id": "run-1"}},
        stream_mode=["messages", "updates"],
    )

async def test_event_is_committed_before_it_is_visible() -> None:
    await executor.execute_start(command)
    assert recorder.calls.index("commit:event:delta") < recorder.calls.index(
        "notify:run-1"
    )
```

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_run_executor -v
```

- [ ] **步骤 3：实现运行 claim**

`claim_start_command()` 使用 `SELECT ... FOR UPDATE`，仅允许：

```text
queued -> running
```

同时设置：

```python
run.active_command_id = command.id
run.lease_owner = worker_id
run.lease_expires_at = now + timedelta(seconds=lease_seconds)
run.version += 1
```

相同 command 已完成或正在有效租约内执行时直接 ACK；租约过期时允许重新 claim。

- [ ] **步骤 4：实现流事件投影**

使用异步 `agent.astream()`，`stream_mode=["messages", "updates"]`。`stream_projection.py` 负责把 LangChain 消息转换成：

- `reasoning`
- `tool_call`
- `tool_result`
- `delta`
- `title`
- `done`
- `error`

每个事件都在同一事务中更新 `messages`、`message_parts`、`tool_invocations` 和 `agent_run_events`。不得在进程内先 `yield` 再写数据库。

正常结束：

```text
running/resuming -> completed
assistant message -> done
写 done 事件
清空租约
```

异常结束：

```text
running/resuming -> failed
assistant message -> error
未完成工具 -> error
写 error 事件
清空租约
```

- [ ] **步骤 5：验证**

```bash
cd agent
uv run python -m unittest tests.test_run_executor tests.test_chat_stream -v
```

- [ ] **步骤 6：提交**

```bash
git add agent/worker agent/service/stream_projection.py agent/service/chat.py \
  agent/tests/test_run_executor.py agent/tests/test_chat_stream.py
git commit -m "feat(agent): 由 worker 驱动并投影 Agent 运行"
```

---

### 任务 8：将 LangGraph interrupt 原子投影为审批批次

**文件：**
- 新建：`agent/repository/approval.py`
- 修改：`agent/worker/run_executor.py`
- 修改：`agent/service/stream_projection.py`
- 新建：`agent/tests/test_approval_interrupt.py`

- [ ] **步骤 1：写 interrupt 投影失败测试**

测试一个 interrupt 内两个工具请求：

```python
async def test_interrupt_creates_ordered_batch_and_timeout_command() -> None:
    result = await project_interrupt(session, run, interrupt, now=fixed_now)
    assert result.batch.sequence == 1
    assert result.batch.expires_at == fixed_now + timedelta(minutes=30)
    assert [item.order_index for item in result.requests] == [0, 1]
    assert all(item.decision == "pending" for item in result.requests)
    assert result.outbox.event_type == "approval.timeout.schedule"
    assert result.event.event_type == "approval_required"
```

再断言 SSE 结束于 `approval_required`，没有 `done`。

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_approval_interrupt -v
```

- [ ] **步骤 3：实现单事务 interrupt 投影**

在一个事务内完成：

- 创建 `approval_batches(status="pending")`
- 按 LangGraph 顺序创建 `approval_requests`
- 将对应 `tool_invocations.status` 改为 `awaiting_approval`
- 创建 `message_parts(type="approval", approval_batch_id=...)`
- 将 Run 改为 `awaiting_approval`
- 写 `approval_required` 事件
- 写 `approval.timeout.schedule` Outbox
- 清空 worker 租约

`interrupt_id` 和 `(agent_run_id, sequence)` 保证重复投影幂等。

- [ ] **步骤 4：验证**

```bash
cd agent
uv run python -m unittest tests.test_approval_interrupt tests.test_run_executor -v
```

- [ ] **步骤 5：提交**

```bash
git add agent/repository/approval.py agent/worker/run_executor.py \
  agent/service/stream_projection.py agent/tests/test_approval_interrupt.py
git commit -m "feat(agent): 持久化 Agent 审批中断"
```

---

### 任务 9：实现 Transactional Outbox 发布与 RabbitMQ 拓扑

**文件：**
- 新建：`agent/core/rabbitmq.py`
- 新建：`agent/worker/outbox_publisher.py`
- 新建：`agent/tests/test_outbox_publisher.py`
- 新建：`agent/tests/integration/test_rabbitmq_topology.py`

- [ ] **步骤 1：写发布确认和重试失败测试**

```python
async def test_marks_published_only_after_broker_confirm() -> None:
    await publisher.publish_pending_once()
    assert broker.confirmed_message_id == outbox.id
    assert refreshed.status == "published"

async def test_publish_failure_keeps_event_retryable() -> None:
    broker.raise_on_publish = RuntimeError("down")
    await publisher.publish_pending_once()
    assert refreshed.status == "pending"
    assert refreshed.attempt_count == 1
    assert refreshed.last_error == "down"
```

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_outbox_publisher -v
```

- [ ] **步骤 3：声明 RabbitMQ 拓扑**

`agent/core/rabbitmq.py` 固定声明：

```text
exchange: agent.commands (durable, topic)
queue: agent.run.commands (durable, quorum)
bindings: agent.run.start, agent.run.resume

exchange: approval.timeout (durable, direct)
queue: approval.timeout.delay (durable, quorum, TTL=1800000,
                               DLX=approval.timeout,
                               dead-letter-routing-key=approval.timeout.ready)
queue: approval.timeout.ready (durable, quorum)
```

所有消息：

```python
Message(
    body=json.dumps(payload).encode(),
    message_id=outbox.id,
    delivery_mode=DeliveryMode.PERSISTENT,
    content_type="application/json",
    type=outbox.event_type,
)
```

连接使用 `aio_pika.connect_robust()`，channel 开启 publisher confirms。

- [ ] **步骤 4：实现并发安全 Outbox 轮询**

查询使用 `FOR UPDATE SKIP LOCKED`，批量 claim `pending` 且 `available_at <= now` 的记录。发布确认后标记 `published`；失败后恢复 `pending`，使用有上限的指数退避更新 `available_at`：

```python
delay_seconds = min(60, 2 ** min(event.attempt_count, 6))
```

超时命令若发布时已超过 `expiresAt`，直接路由到 `approval.timeout.ready`。

- [ ] **步骤 5：运行单元与 RabbitMQ 集成测试**

```bash
docker compose up -d rabbitmq
cd agent
uv run python -m unittest tests.test_outbox_publisher -v
uv run python -m unittest tests.integration.test_rabbitmq_topology -v
```

预期：publisher confirm、失败重试、TTL/DLX 路由均通过。

- [ ] **步骤 6：提交**

```bash
git add agent/core/rabbitmq.py agent/worker/outbox_publisher.py \
  agent/tests/test_outbox_publisher.py agent/tests/integration/test_rabbitmq_topology.py
git commit -m "feat(agent): 通过 Outbox 可靠发布 RabbitMQ 命令"
```

---

### 任务 10：实现人工审批决策和恢复 SSE

**文件：**
- 新建：`agent/service/approval.py`
- 修改：`agent/controller/chat.py`
- 修改：`agent/main.py`
- 修改：`agent/worker/run_executor.py`
- 新建：`agent/tests/test_approval_service.py`
- 新建：`agent/tests/test_approval_api.py`

- [ ] **步骤 1：写完整批次校验和幂等失败测试**

覆盖：

- 少一个 request：`422`
- 同一 request 重复：`422`
- 不属于批次的 request：`422`
- 已过期：`409`
- 重复相同提交：返回已有结果，不新增 resume Outbox
- 已提交但决策不同：`409`

核心测试：

```python
async def test_manual_decisions_and_resume_outbox_commit_together() -> None:
    result = await submit_approval_decisions(session, batch_id, request)
    assert [item.decision for item in result.batch.requests] == [
        "approved", "rejected"
    ]
    assert result.batch.resolution_source == "manual"
    assert result.run.status == "resume_queued"
    assert result.outbox.event_type == "agent.run.resume"
```

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_approval_service tests.test_approval_api -v
```

- [ ] **步骤 3：实现锁批次事务**

`submit_approval_decisions()` 使用 `SELECT ... FOR UPDATE` 锁定批次和 Run，并且在一个事务中：

- 校验完整且唯一的 request 集合
- 保存 `approved/rejected` 和 `decided_at`
- 更新工具状态：批准为 `running`，拒绝为 `rejected`
- 批次改为 `resolved/manual`
- 写 `approval_resolved`
- Run 改为 `resume_queued`
- 创建稳定 ID 的 `agent.run.resume` Outbox

Outbox payload 必须包含 `runId`、`batchId`、`interruptId` 和按 `order_index` 排序的 LangGraph 决策。

- [ ] **步骤 4：实现审批 POST SSE**

注册：

```python
api_router.post("/chat/approval/decisions/{batch_id}")(
    submit_approval_decisions_stream
)
```

控制器提交事务后，从请求中的 `afterEventId` 订阅同一个 Run。返回内容先包含已持久化的 `approval_resolved`，然后继续等待 worker 恢复事件。

- [ ] **步骤 5：实现 LangGraph resume**

worker 调用：

```python
agent.astream(
    Command(resume={"decisions": ordered_decisions}),
    config={"configurable": {"thread_id": run.id}},
    stream_mode=["messages", "updates"],
)
```

执行前读取最新 checkpoint 并比较 `interrupt_id`：

- 匹配：执行 resume。
- 已消费：对齐业务状态并 ACK，不重复执行。
- 不同且仍有 interrupt：Run 标为 `failed`，写可诊断错误事件。

- [ ] **步骤 6：验证**

```bash
cd agent
uv run python -m unittest tests.test_approval_service tests.test_approval_api \
  tests.test_run_executor -v
```

- [ ] **步骤 7：提交**

```bash
git add agent/service/approval.py agent/controller/chat.py agent/main.py \
  agent/worker/run_executor.py agent/tests/test_approval_service.py \
  agent/tests/test_approval_api.py
git commit -m "feat(agent): 提交审批决策并恢复 Agent"
```

---

### 任务 11：实现 30 分钟自动过期与命令消费者

**文件：**
- 新建：`agent/worker/command_consumer.py`
- 修改：`agent/worker/main.py`
- 修改：`agent/service/approval.py`
- 新建：`agent/tests/test_command_consumer.py`
- 新建：`agent/tests/test_approval_timeout.py`

- [ ] **步骤 1：写超时竞争和重复投递失败测试**

```python
async def test_timeout_expires_all_pending_requests_and_enqueues_resume() -> None:
    result = await expire_approval_batch(session, batch_id, now=expires_at)
    assert result.batch.status == "expired"
    assert result.batch.resolution_source == "timeout"
    assert all(item.decision == "expired" for item in result.requests)
    assert result.run.status == "resume_queued"
    assert result.outbox.event_type == "agent.run.resume"

async def test_timeout_loses_to_manual_resolution_without_side_effects() -> None:
    result = await expire_approval_batch(session, resolved_batch_id, now=expires_at)
    assert result is None
    assert await count_resume_outbox(session, resolved_batch_id) == 1
```

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_approval_timeout tests.test_command_consumer -v
```

- [ ] **步骤 3：实现超时事务**

超时消费者重新读取并锁定 PostgreSQL：

- 已解决：ACK，无操作。
- pending 且 `now >= expires_at`：所有 pending request 改为 `expired`，工具改为 `expired`，批次改为 `expired/timeout`，写 `approval_resolved`，Run 改为 `resume_queued`，创建 resume Outbox。
- pending 但未到期：NACK 不重入原队列；创建一个新的 timeout schedule Outbox，payload 保持同一 `batchId` 和原始 `expiresAt`。

传给 LangGraph 的每一项仍是：

```json
{"type":"reject","message":"Approval timed out after 30 minutes"}
```

- [ ] **步骤 4：实现 RabbitMQ 消费与手动 ACK**

`command_consumer.py`：

- `agent.run.start` 调 `execute_start`
- `agent.run.resume` 调 `execute_resume`
- `approval.timeout.ready` 调 `expire_approval_batch`
- 业务成功或已幂等完成后 ACK
- 临时数据库/网络错误 NACK 并 requeue
- 不可恢复的 payload 错误记录后 ACK，避免毒消息无限循环

不得在 handler 成功前 ACK。

- [ ] **步骤 5：验证**

```bash
cd agent
uv run python -m unittest tests.test_approval_timeout \
  tests.test_command_consumer tests.test_run_executor -v
```

- [ ] **步骤 6：提交**

```bash
git add agent/worker/command_consumer.py agent/worker/main.py \
  agent/service/approval.py agent/tests/test_command_consumer.py \
  agent/tests/test_approval_timeout.py
git commit -m "feat(agent): 自动过期审批并幂等消费命令"
```

---

### 任务 12：让历史消息返回审批过程和活跃 Run

**文件：**
- 修改：`agent/repository/message.py`
- 修改：`agent/repository/agent_run.py`
- 修改：`agent/service/chat_conversations.py`
- 修改：`agent/controller/chat_conversations.py`
- 修改：`agent/tests/test_chat_conversations.py`

- [ ] **步骤 1：写历史审批和活跃运行失败测试**

历史响应固定为：

```json
{
  "messages": [
    {
      "timelineParts": [
        {
          "type": "approval",
          "batch": {
            "status": "expired",
            "resolutionSource": "timeout",
            "requests": [
              {"decision": "expired", "toolName": "get_weather"}
            ]
          }
        }
      ]
    }
  ],
  "activeRun": {
    "runId": "run-1",
    "status": "awaiting_approval",
    "lastEventId": 42,
    "assistantMessageId": "assistant-1",
    "approvalBatch": {}
  }
}
```

测试批准、拒绝和过期三种历史状态，确保请求顺序来自 `order_index`。

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd agent
uv run python -m unittest tests.test_chat_conversations -v
```

- [ ] **步骤 3：预加载审批关系并投影**

`repository/message.py` 对 approval part 使用 `selectinload` 预加载批次和 requests，避免逐条 N+1。`_to_timeline_part()` 增加 `type == "approval"` 分支，并与实时 `approval_required` 复用同一个 `to_approval_batch_payload()`。

`get_conversation_messages()` 同时查询活跃 Run、其最后事件 ID 和当前 pending batch。

- [ ] **步骤 4：验证**

```bash
cd agent
uv run python -m unittest tests.test_chat_conversations tests.test_hitl_schemas -v
```

- [ ] **步骤 5：提交**

```bash
git add agent/repository/message.py agent/repository/agent_run.py \
  agent/service/chat_conversations.py agent/controller/chat_conversations.py \
  agent/tests/test_chat_conversations.py
git commit -m "feat(agent): 在历史消息中返回审批审计过程"
```

---

### 任务 13：升级前端类型、SSE 解析和三个 POST 接口

**文件：**
- 修改：`web/features/chat/types.ts`
- 修改：`web/features/chat/api.ts`
- 修改：`web/features/chat/api.test.ts`
- 新建：`web/features/chat/chat-event-reducer.ts`
- 新建：`web/features/chat/chat-event-reducer.test.ts`

- [ ] **步骤 1：写 POST 和 SSE ID 失败测试**

`api.test.ts` 必须断言：

```typescript
test("resumeChatStream uses POST run cursor payload", async () => {
  await resumeChatStream(
    { runId: "run-1", afterEventId: 42 },
    options,
  );
  assert.equal(calls[0].init?.method, "POST");
  assert.equal(
    calls[0].init?.body,
    JSON.stringify({ runId: "run-1", afterEventId: 42 }),
  );
});

test("readSseResponse exposes numeric event id", async () => {
  // 输入包含 `id: 43`
  assert.equal(received[0].eventId, 43);
});
```

审批提交 URL 必须为 `/api/chat/approval/decisions/batch-1`，body 中 `decisions` 在前、`afterEventId` 在后。

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd web
pnpm dlx tsx --test features/chat/api.test.ts
```

- [ ] **步骤 3：定义前端契约**

新增：

```typescript
export type ApprovalRequest = {
  id: string;
  toolInvocationId: string;
  toolName: string;
  args: Record<string, unknown>;
  decision: "pending" | "approved" | "rejected" | "expired";
  decidedAt?: string;
};

export type ApprovalBatch = {
  id: string;
  status: "pending" | "resolved" | "expired";
  expiresAt: string;
  resolutionSource?: "manual" | "timeout";
  resolvedAt?: string;
  requests: ApprovalRequest[];
};

export type ConversationRunState = {
  runId: string;
  assistantMessageId: string;
  status: "streaming" | "awaiting_approval" | "resuming";
  lastEventId?: number;
  approvalBatch?: ApprovalBatch;
};
```

`ChatTimelinePart` 增加 `approval`；工具状态增加 `awaiting_approval/rejected/expired`；`ChatStreamEvent` 每项含 `runId`，客户端包装为：

```typescript
type ReceivedChatStreamEvent = {
  eventId?: number;
  event: ChatStreamEvent;
};
```

- [ ] **步骤 4：实现三个 POST SSE 方法**

```typescript
streamChat(request, options)
resumeChatStream({ runId, afterEventId }, options)
submitApprovalDecisions(batchId, { decisions, afterEventId }, options)
```

统一走 `readSseResponse()`，解析 `id:` 和多行 `data:`。`409` 抛出带 `status` 的 `ChatApiError`，供 store 触发历史刷新。

- [ ] **步骤 5：实现纯 reducer**

`chat-event-reducer.ts` 只做无副作用归并：

- `eventId <= lastEventId`：忽略。
- `run_created`：建立会话运行状态。
- `approval_required`：插入/更新 approval timeline part，状态改为 `awaiting_approval`。
- `approval_resolved`：卡片改只读，状态改为 `resuming`。
- `done/error`：移除活跃运行状态。

- [ ] **步骤 6：验证**

```bash
cd web
pnpm dlx tsx --test features/chat/api.test.ts \
  features/chat/chat-event-reducer.test.ts
```

- [ ] **步骤 7：提交**

```bash
git add web/features/chat/types.ts web/features/chat/api.ts \
  web/features/chat/api.test.ts web/features/chat/chat-event-reducer.ts \
  web/features/chat/chat-event-reducer.test.ts
git commit -m "feat(web): 接入 HITL SSE 与审批接口契约"
```

---

### 任务 14：将前端流状态改为按会话隔离

**文件：**
- 修改：`web/features/chat/store.ts`
- 修改：`web/features/chat/store.test.ts`
- 修改：`web/features/chat/chat-ui-state.ts`
- 修改：`web/features/chat/chat-ui-state.test.ts`
- 修改：`web/features/chat/components/chat-input.tsx`

- [ ] **步骤 1：写并发会话和恢复失败测试**

覆盖：

```typescript
test("different conversations keep independent stream controllers", async () => {
  await store.sendMessageTo("conversation-1", "first");
  await store.sendMessageTo("conversation-2", "second");
  assert.equal(Object.keys(store.runsByConversationId).length, 2);
  assert.notEqual(
    store.controllersByConversationId["conversation-1"],
    store.controllersByConversationId["conversation-2"],
  );
});

test("pending approval locks only its conversation", () => {
  assert.equal(isConversationInputLocked(state, "conversation-1"), true);
  assert.equal(isConversationInputLocked(state, "conversation-2"), false);
});
```

再测试历史 `activeRun.status` 为 `running/resuming` 时调用 POST resume；为 `awaiting_approval` 时直接恢复卡片，不发 resume 请求。

- [ ] **步骤 2：运行测试并确认失败**

```bash
cd web
pnpm dlx tsx --test features/chat/store.test.ts \
  features/chat/chat-ui-state.test.ts
```

- [ ] **步骤 3：替换全局流字段**

删除：

```typescript
isStreaming
streamingConversationId
streamingMessageId
abortController
```

替换为：

```typescript
runsByConversationId: Record<string, ConversationRunState>;
controllersByConversationId: Record<string, AbortController>;
```

`startConversationStream()` 只中止同一会话的旧 controller，不影响其他会话。事件通过 `reduceChatStreamEvent()` 按 `eventId` 幂等处理。

- [ ] **步骤 4：实现历史恢复**

`listMessages()` 返回 `ConversationMessagesResponse`。选择会话时：

```text
无 activeRun -> 只加载历史
awaiting_approval -> 恢复 runsByConversationId 和审批卡
queued/running/resume_queued/resuming -> POST /chat/stream/resume
completed/failed -> 不恢复连接
```

前端不得用 `message.status === "streaming"` 推断 Run 身份。

- [ ] **步骤 5：更新输入锁**

`ChatInput` 使用：

```typescript
const isLocked = useChatStore((state) =>
  isConversationInputLocked(state, state.activeConversationId),
);
```

`streaming`、`awaiting_approval`、`resuming` 均锁定当前会话。断开 SSE 不解锁业务运行；只有 `done/error` 或刷新后无 active Run 才解锁。

- [ ] **步骤 6：验证**

```bash
cd web
pnpm dlx tsx --test features/chat/store.test.ts \
  features/chat/chat-ui-state.test.ts \
  features/chat/chat-event-reducer.test.ts
```

- [ ] **步骤 7：提交**

```bash
git add web/features/chat/store.ts web/features/chat/store.test.ts \
  web/features/chat/chat-ui-state.ts web/features/chat/chat-ui-state.test.ts \
  web/features/chat/components/chat-input.tsx
git commit -m "feat(web): 按会话隔离 Agent 运行状态"
```

---

### 任务 15：实现审批卡片、历史只读展示和端到端验收

**文件：**
- 新建：`web/features/chat/components/approval-card.tsx`
- 新建：`web/features/chat/components/approval-card-state.ts`
- 新建：`web/features/chat/components/approval-card-state.test.ts`
- 修改：`web/features/chat/components/chat-message-timeline.tsx`
- 修改：`web/features/chat/components/chat-message-item.tsx`
- 修改：`web/features/chat/store.ts`
- 修改：`web/features/chat/components/tool-invocation-card-state.ts`
- 修改：`web/features/chat/components/tool-invocation-card-state.test.ts`
- 新建：`agent/tests/integration/test_hitl_flow.py`
- 修改：`agent/README.md`

- [ ] **步骤 1：写审批卡状态失败测试**

纯状态 helper 必须验证：

```typescript
test("submit stays disabled until every request is selected", () => {
  assert.equal(canSubmitApproval(batch, { r1: "approve" }), false);
  assert.equal(
    canSubmitApproval(batch, { r1: "approve", r2: "reject" }),
    true,
  );
});

test("resolved and expired batches are read only", () => {
  assert.equal(isApprovalReadOnly(resolvedBatch), true);
  assert.equal(isApprovalReadOnly(expiredBatch), true);
});
```

- [ ] **步骤 2：运行前端测试并确认失败**

```bash
cd web
pnpm dlx tsx --test features/chat/components/approval-card-state.test.ts
```

- [ ] **步骤 3：实现审批卡**

每个 request 显示：

- 工具名
- 只读 JSON 参数
- “批准”和“拒绝”单选
- 已提交后的最终结果

批次显示：

- `expiresAt`
- 提交中禁用全部控件
- 全部选择后才允许一次提交
- `resolutionSource === "timeout"` 显示“30 分钟未处理，已自动拒绝”

不得提供参数编辑输入框。`ApprovalCard` 调用 store 的：

```typescript
submitApproval(batchId, selections)
```

store 从当前 Run 的 `lastEventId` 发审批 POST SSE；收到 `409` 时重新加载该会话历史和 active Run。

- [ ] **步骤 4：在时间线的持久化位置渲染**

`chat-message-timeline.tsx` 分支：

```tsx
if (part.type === "approval") {
  return (
    <ChainOfThoughtStep key={part.id} label="工具审批">
      <ApprovalCard batch={part.batch} conversationId={message.conversationId} />
    </ChainOfThoughtStep>
  );
}
```

历史与实时事件必须使用同一组件。工具卡为 `awaiting_approval`、`rejected`、`expired` 增加明确文案。

- [ ] **步骤 5：写后端端到端 HITL 测试**

`test_hitl_flow.py` 使用真实 PostgreSQL、RabbitMQ 和测试 Agent，验证：

1. `POST /api/chat/stream` 首个持久化事件是 `run_created`。
2. `get_weather` interrupt 返回 `approval_required` 且没有 `done`。
3. 审批 POST 返回 `approval_resolved` 和后续 `done`。
4. 断开后 POST resume 只回放 `afterEventId` 之后事件。
5. 模拟 API/worker 重启后 pending interrupt 仍可恢复。
6. 超时消息经 DLX 后自动拒绝并恢复。
7. 同一会话第二个 Run 返回 `409`，不同会话可并发。

测试环境允许把 TTL 参数注入为 1 秒，但生产常量和 Compose 拓扑仍固定 30 分钟。

- [ ] **步骤 6：运行完整验证**

```bash
docker compose up -d postgres rabbitmq
cd agent
uv run alembic upgrade head
uv run python -m unittest discover -s tests -p 'test_*.py' -v
cd ../web
pnpm dlx tsx --test features/chat/**/*.test.ts
pnpm lint
pnpm build
cd ..
make test-dev-config
```

预期：

- Python 测试 `OK`
- TypeScript 测试全部通过
- Biome 无错误
- Next.js build 退出码 `0`
- 开发脚本测试输出 `PASS: dev config scripts`

- [ ] **步骤 7：更新运行说明**

`agent/README.md` 写明：

```text
API: uv run python main.py
Worker: uv run python -m worker.main
Outbox publisher: uv run python -m worker.outbox_publisher
RabbitMQ management: http://localhost:15672
```

同时说明 PostgreSQL 是业务状态真相，RabbitMQ 消息可能重复，不能用队列长度推断审批状态。

- [ ] **步骤 8：提交**

```bash
git add web/features/chat agent/tests/integration/test_hitl_flow.py agent/README.md
git commit -m "feat(hitl): 完成工具审批交互与端到端恢复"
```

---

## 完成判定

只有以下证据全部成立，才能判定本计划完成：

- `get_weather` 会中断并只允许批准/拒绝；其他工具不触发审批。
- 审批批次、逐项决策、Run、SSE 事件和 Outbox 在 PostgreSQL 可审计。
- API 断连不会取消 Agent；POST resume 能按事件 ID 精确回放。
- API、worker 或 RabbitMQ 重启后，未完成运行仍能继续。
- 30 分钟超时由 RabbitMQ TTL + DLX 触发，不依赖全表扫描。
- 同一会话最多一个活跃 Run，不同会话可并发。
- 前端只锁定有活跃 Run 的会话，多个会话可同时流式执行。
- 实时与历史使用相同审批卡，已决和超时状态只读。
- 完整后端测试、前端测试、lint、build、Alembic 和开发脚本验证全部通过。
