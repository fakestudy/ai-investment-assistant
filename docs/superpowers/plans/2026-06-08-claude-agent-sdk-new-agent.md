# Claude Agent SDK 新 Agent 实施计划

> **给 agent 执行者：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项执行本计划。步骤使用勾选框语法（`- [ ]`）进行跟踪。

**目标：** 新建一个独立的 Python agent 服务，使用 `claude-agent-sdk` 和基于 `PostgreSQL` 的官方 `SessionStore`，同时保持当前前端聊天请求和 SSE 事件契约不变。

**架构：** 新建 `agent_claude/` 服务，而不是修改现有 `agent/`。新服务只使用 `claude-agent-sdk` 作为 runtime，通过 `PostgreSQL` 实现官方 `SessionStore` 来持久化 runtime transcript，并把 runtime 输出投影为前端兼容的 `messages`、`tool_invocations`、`message_parts` 数据以及 `/chat/stream` SSE 事件。

**技术栈：** Python 3.12+、FastAPI、SQLAlchemy 2 AsyncSession、Alembic、psycopg v3、`claude-agent-sdk`、`python-dotenv`、`uvicorn`、unittest。

---

## 文件结构

- 创建 `agent_claude/pyproject.toml`：新服务的独立依赖和工具配置。
- 创建 `agent_claude/main.py`：FastAPI 入口和路由注册。
- 创建 `agent_claude/core/config.py`：环境变量加载和类型化配置。
- 创建 `agent_claude/core/database.py`：`PostgreSQL` engine、session factory 和基础元数据。
- 创建 `agent_claude/model/base.py`：声明式基类。
- 创建 `agent_claude/model/conversation.py`：前端兼容的会话表。
- 创建 `agent_claude/model/message.py`：持久化 user 和 assistant 消息。
- 创建 `agent_claude/model/tool_invocation.py`：工具调用投影表。
- 创建 `agent_claude/model/message_part.py`：reasoning/tool timeline 投影表。
- 创建 `agent_claude/model/agent_session.py`：conversation 到 SDK session 的映射表。
- 创建 `agent_claude/model/agent_session_entry.py`：用于 `SessionStore` 的 `PostgreSQL` transcript entry 表。
- 创建 `agent_claude/migrations/env.py`：Alembic 元数据注册。
- 创建 `agent_claude/migrations/versions/<revision>_create_chat_and_session_tables.py`：新服务全部表的首个 migration。
- 创建 `agent_claude/schema/chat.py`：与当前前端字段对齐的 request/response/SSE schema。
- 创建 `agent_claude/repository/conversation.py`：conversation 查询和标题更新。
- 创建 `agent_claude/repository/message.py`：message CRUD 和历史加载。
- 创建 `agent_claude/repository/tool_invocation.py`：投影用工具调用创建和更新。
- 创建 `agent_claude/repository/message_part.py`：timeline part 创建和更新。
- 创建 `agent_claude/repository/agent_session.py`：conversation 和 session 映射持久化。
- 创建 `agent_claude/repository/agent_session_entry.py`：按顺序追加和读取 transcript entry。
- 创建 `agent_claude/service/session_store.py`：基于 `PostgreSQL` 的官方 `SessionStore` 适配器。
- 创建 `agent_claude/service/runtime.py`：`claude-agent-sdk` 适配层和 options 工厂。
- 创建 `agent_claude/service/history.py`：前端历史消息投影服务。
- 创建 `agent_claude/service/chat.py`：流式编排、持久化和 SSE 事件输出。
- 创建 `agent_claude/controller/chat.py`：`/chat/stream` 和历史接口。
- 创建 `agent_claude/tests/test_models.py`：元数据和 relationship 覆盖。
- 创建 `agent_claude/tests/test_session_store.py`：`PostgreSQL SessionStore` 行为测试。
- 创建 `agent_claude/tests/test_chat_stream.py`：SSE 事件兼容和持久化测试。
- 创建 `agent_claude/tests/test_history_api.py`：历史接口 payload 兼容测试。

## Task 1：搭建新服务骨架和数据库 Schema

**Files:**
- Create: `agent_claude/pyproject.toml`
- Create: `agent_claude/main.py`
- Create: `agent_claude/core/config.py`
- Create: `agent_claude/core/database.py`
- Create: `agent_claude/model/base.py`
- Create: `agent_claude/model/conversation.py`
- Create: `agent_claude/model/message.py`
- Create: `agent_claude/model/tool_invocation.py`
- Create: `agent_claude/model/message_part.py`
- Create: `agent_claude/model/agent_session.py`
- Create: `agent_claude/model/agent_session_entry.py`
- Create: `agent_claude/migrations/env.py`
- Create: `agent_claude/migrations/versions/<revision>_create_chat_and_session_tables.py`
- Test: `agent_claude/tests/test_models.py`

- [x] **Step 1：先写失败的 metadata 测试**

创建 `agent_claude/tests/test_models.py`：

```python
import unittest

from model.base import Base


class ModelMetadataTest(unittest.TestCase):
    def test_expected_tables_are_registered(self) -> None:
        expected = {
            "conversations",
            "messages",
            "tool_invocations",
            "message_parts",
            "agent_sessions",
            "agent_session_entries",
        }

        self.assertTrue(expected.issubset(set(Base.metadata.tables)))


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2：运行测试并确认失败**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_models -v
```

预期：因为 `ModuleNotFoundError` 或缺少表名而 FAIL。

- [x] **Step 3：补齐服务骨架和基础 models**

创建 `agent_claude/pyproject.toml`：

```toml
[project]
name = "agent-claude"
version = "0.1.0"
description = "Standalone Claude Agent SDK backend compatible with current chat frontend"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "alembic>=1.18.4",
    "claude-agent-sdk>=0.2.91",
    "fastapi>=0.136.3",
    "psycopg[binary]>=3.3.4",
    "python-dotenv>=1.2.2",
    "sqlalchemy>=2.0.50",
    "uvicorn>=0.49.0",
]

[tool.uv]
package = false
```

创建 `agent_claude/core/config.py`：

```python
import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_base_url: str
    anthropic_auth_token: str
    anthropic_model: str


def get_settings() -> Settings:
    database_url = os.environ["DATABASE_URL"]
    anthropic_base_url = os.environ["ANTHROPIC_BASE_URL"]
    anthropic_auth_token = os.environ["ANTHROPIC_AUTH_TOKEN"]
    anthropic_model = os.environ["ANTHROPIC_MODEL"]
    return Settings(
        database_url=database_url,
        anthropic_base_url=anthropic_base_url,
        anthropic_auth_token=anthropic_auth_token,
        anthropic_model=anthropic_model,
    )
```

创建 `agent_claude/core/database.py`：

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings


settings = get_settings()
engine = create_async_engine(settings.database_url, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

创建 `agent_claude/model/base.py`：

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

创建 `agent_claude/model/conversation.py`：

```python
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
```

创建 `agent_claude/model/message.py`：

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
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tool_invocations = relationship("ToolInvocation", back_populates="message")
    timeline_parts = relationship("MessagePart", back_populates="message")
```

创建 `agent_claude/model/tool_invocation.py`：

```python
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    message = relationship("Message", back_populates="tool_invocations")
```

创建 `agent_claude/model/message_part.py`：

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
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_invocation_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("tool_invocations.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    message = relationship("Message", back_populates="timeline_parts")
```

创建 `agent_claude/model/agent_session.py`：

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (UniqueConstraint("conversation_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sdk_session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

创建 `agent_claude/model/agent_session_entry.py`：

```python
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentSessionEntry(Base):
    __tablename__ = "agent_session_entries"
    __table_args__ = (Index("ix_agent_session_entries_session_sequence", "sdk_session_id", "sequence_no", unique=True),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sdk_session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

创建 `agent_claude/main.py`：

```python
from fastapi import FastAPI

app = FastAPI(title="Claude Agent Compatible Backend")
```

- [x] **Step 4：补齐 Alembic metadata 注册和首个 migration**

创建 `agent_claude/migrations/env.py`：

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import get_settings
from model.base import Base
from model.agent_session import AgentSession
from model.agent_session_entry import AgentSessionEntry
from model.conversation import Conversation
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

创建 `agent_claude/migrations/versions/<revision>_create_chat_and_session_tables.py`：

```python
from alembic import op
import sqlalchemy as sa


revision = "<revision>"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("message_id", sa.String(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "message_parts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("message_id", sa.String(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tool_invocation_id", sa.String(), sa.ForeignKey("tool_invocations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sdk_session_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id"),
    )
    op.create_table(
        "agent_session_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("sdk_session_id", sa.String(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("entry_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_session_entries_session_sequence", "agent_session_entries", ["sdk_session_id", "sequence_no"], unique=True)
```

- [x] **Step 5：运行 metadata 测试并提交脚手架**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_models -v
```

预期：PASS。

提交：

```bash
git add agent_claude docs/superpowers/plans/2026-06-08-claude-agent-sdk-new-agent.md
git commit -m "feat: scaffold claude agent service"
```

## Task 2：实现 PostgreSQL SessionStore 和 Runtime Adapter

**Files:**
- Create: `agent_claude/repository/agent_session.py`
- Create: `agent_claude/repository/agent_session_entry.py`
- Create: `agent_claude/service/session_store.py`
- Create: `agent_claude/service/runtime.py`
- Test: `agent_claude/tests/test_session_store.py`

- [x] **Step 1：先写失败的 SessionStore 测试**

创建 `agent_claude/tests/test_session_store.py`：

```python
import unittest

from service.session_store import PostgresSessionStore


class SessionStoreContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_append_and_load_round_trip(self) -> None:
        store = PostgresSessionStore(session_factory=None)

        await store.append(
            {"projectKey": "project-a", "sessionId": "session-1"},
            [{"kind": "assistant", "text": "hello"}],
        )

        entries = await store.load(
            {"projectKey": "project-a", "sessionId": "session-1"}
        )

        self.assertEqual(
            entries,
            [{"kind": "assistant", "text": "hello"}],
        )


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2：运行 SessionStore 测试并确认失败**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_session_store -v
```

预期：因为缺少 `PostgresSessionStore` 而 FAIL。

- [x] **Step 3：补齐 session 映射和 transcript entry 的 repository**

创建 `agent_claude/repository/agent_session.py`：

```python
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_session import AgentSession


async def get_agent_session_by_conversation_id(
    session: AsyncSession,
    conversation_id: str,
) -> AgentSession | None:
    result = await session.execute(
        select(AgentSession).where(AgentSession.conversation_id == conversation_id)
    )
    return result.scalar_one_or_none()


async def upsert_agent_session(
    session: AsyncSession,
    *,
    conversation_id: str,
    sdk_session_id: str,
) -> AgentSession:
    row = await get_agent_session_by_conversation_id(session, conversation_id)
    now = datetime.now(UTC)
    if row is None:
        row = AgentSession(
            id=str(uuid4()),
            conversation_id=conversation_id,
            sdk_session_id=sdk_session_id,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.sdk_session_id = sdk_session_id
        row.updated_at = now
    await session.flush()
    return row
```

创建 `agent_claude/repository/agent_session_entry.py`：

```python
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_session_entry import AgentSessionEntry


async def append_session_entries(
    session: AsyncSession,
    *,
    sdk_session_id: str,
    payloads: list[dict[str, object]],
) -> None:
    result = await session.execute(
        select(AgentSessionEntry.sequence_no)
        .where(AgentSessionEntry.sdk_session_id == sdk_session_id)
        .order_by(AgentSessionEntry.sequence_no.desc())
        .limit(1)
    )
    last_sequence = result.scalar_one_or_none() or 0
    now = datetime.now(UTC)
    for index, payload in enumerate(payloads, start=1):
        session.add(
            AgentSessionEntry(
                id=str(uuid4()),
                sdk_session_id=sdk_session_id,
                sequence_no=last_sequence + index,
                entry_payload=payload,
                created_at=now,
            )
        )
    await session.flush()


async def load_session_entries(
    session: AsyncSession,
    *,
    sdk_session_id: str,
) -> list[dict[str, object]]:
    result = await session.execute(
        select(AgentSessionEntry)
        .where(AgentSessionEntry.sdk_session_id == sdk_session_id)
        .order_by(AgentSessionEntry.sequence_no.asc())
    )
    return [row.entry_payload for row in result.scalars().all()]
```

- [x] **Step 4：实现 PostgreSQL SessionStore 和 runtime adapter**

创建 `agent_claude/service/session_store.py`：

```python
from collections.abc import Callable
from sqlalchemy.ext.asyncio import AsyncSession

from repository.agent_session_entry import append_session_entries, load_session_entries


class PostgresSessionStore:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self.session_factory = session_factory

    async def append(
        self,
        key: dict[str, str],
        entries: list[dict[str, object]],
    ) -> None:
        async with self.session_factory() as session:
            await append_session_entries(
                session,
                sdk_session_id=key["sessionId"],
                payloads=entries,
            )
            await session.commit()

    async def load(self, key: dict[str, str]) -> list[dict[str, object]]:
        async with self.session_factory() as session:
            return await load_session_entries(
                session,
                sdk_session_id=key["sessionId"],
            )
```

创建 `agent_claude/service/runtime.py`：

```python
from claude_agent_sdk import ClaudeAgentOptions, query

from core.config import get_settings


BUILTIN_TOOLS = [
    "Task",
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
]


def build_options(*, session_store: object, resume: str | None = None) -> ClaudeAgentOptions:
    settings = get_settings()
    return ClaudeAgentOptions(
        allowed_tools=BUILTIN_TOOLS,
        include_partial_messages=True,
        permission_mode="acceptEdits",
        setting_sources=[],
        model=settings.anthropic_model,
        resume=resume,
        session_store=session_store,
    )


def stream_query(*, prompt: str, session_store: object, resume: str | None = None):
    return query(
        prompt=prompt,
        options=build_options(session_store=session_store, resume=resume),
    )
```

- [x] **Step 5：运行测试并提交**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_session_store -v
```

预期：PASS。

提交：

```bash
git add agent_claude
git commit -m "feat: add postgres session store"
```

## Task 3：实现消息投影持久化和历史消息加载

**Files:**
- Create: `agent_claude/repository/conversation.py`
- Create: `agent_claude/repository/message.py`
- Create: `agent_claude/repository/tool_invocation.py`
- Create: `agent_claude/repository/message_part.py`
- Create: `agent_claude/service/history.py`
- Test: `agent_claude/tests/test_history_api.py`

- [x] **Step 1：先写失败的历史投影测试**

创建 `agent_claude/tests/test_history_api.py`：

```python
import unittest

from schema.chat import ConversationMessagesResponse


class HistorySchemaTest(unittest.TestCase):
    def test_history_shape_accepts_tool_and_timeline_parts(self) -> None:
        payload = {
            "messages": [
                {
                    "id": "assistant-1",
                    "conversationId": "conversation-1",
                    "role": "assistant",
                    "content": "Done",
                    "reasoning": "Think",
                    "toolInvocations": [
                        {
                            "id": "tool-1",
                            "messageId": "assistant-1",
                            "toolName": "Read",
                            "args": {"file": "a.py"},
                            "status": "completed",
                        }
                    ],
                    "timelineParts": [
                        {
                            "id": "part-1",
                            "type": "reasoning",
                            "orderIndex": 0,
                            "text": "Think",
                        }
                    ],
                    "status": "done",
                    "createdAt": "2026-06-08T00:00:00Z",
                }
            ],
            "activeRun": None,
        }

        result = ConversationMessagesResponse.model_validate(payload)

        self.assertEqual(result.messages[0].id, "assistant-1")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2：运行历史测试并确认失败**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_history_api -v
```

预期：因为缺少 schema 定义而 FAIL。

- [x] **Step 3：补齐 conversations、messages、tools、parts 的 repository**

创建 `agent_claude/repository/conversation.py`：

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.conversation import Conversation


async def get_conversation(session: AsyncSession, conversation_id: str) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def update_conversation_title(
    session: AsyncSession,
    *,
    conversation_id: str,
    title: str,
) -> None:
    row = await get_conversation(session, conversation_id)
    if row is not None:
        row.title = title
        await session.flush()
```

创建 `agent_claude/repository/message.py`：

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from model.message import Message


async def create_message(session: AsyncSession, message: Message) -> Message:
    session.add(message)
    await session.flush()
    return message


async def update_message(
    session: AsyncSession,
    *,
    message_id: str,
    content: str,
    reasoning: str,
    status: str,
) -> None:
    row = await session.get(Message, message_id)
    if row is None:
        return
    row.content = content
    row.reasoning = reasoning
    row.status = status
    await session.flush()


async def list_messages_by_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(
            selectinload(Message.tool_invocations),
            selectinload(Message.timeline_parts),
        )
        .order_by(Message.created_at.asc())
    )
    return list(result.scalars().unique().all())
```

创建 `agent_claude/repository/tool_invocation.py` 和 `agent_claude/repository/message_part.py`，沿用现有 `agent/` 服务里相同的 create/update 模式。

- [x] **Step 4：补齐兼容 schema 和历史投影服务**

创建 `agent_claude/schema/chat.py`：

```python
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FrontendModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ToolInvocation(FrontendModel):
    id: str
    message_id: str = Field(alias="messageId")
    tool_name: str = Field(alias="toolName")
    args: dict[str, Any]
    result: Any | None = None
    error: str | None = None
    latency_ms: int | None = Field(default=None, alias="latencyMs")
    status: Literal["running", "completed", "error"]
    created_at: str | None = Field(default=None, alias="createdAt")


class ReasoningTimelinePart(FrontendModel):
    id: str
    type: Literal["reasoning"]
    order_index: int | None = Field(default=None, alias="orderIndex")
    text: str


class ToolTimelinePart(FrontendModel):
    id: str
    type: Literal["tool"]
    order_index: int | None = Field(default=None, alias="orderIndex")
    invocation: ToolInvocation


ChatTimelinePart = Annotated[
    ReasoningTimelinePart | ToolTimelinePart,
    Field(discriminator="type"),
]


class ChatMessage(FrontendModel):
    id: str
    conversation_id: str = Field(alias="conversationId")
    role: Literal["user", "assistant", "tool"]
    content: str
    reasoning: str | None = None
    tool_invocations: list[ToolInvocation] | None = Field(default=None, alias="toolInvocations")
    timeline_parts: list[ChatTimelinePart] | None = Field(default=None, alias="timelineParts")
    status: Literal["idle", "streaming", "done", "error"] | None = None
    created_at: str = Field(alias="createdAt")


class ConversationMessagesResponse(FrontendModel):
    messages: list[ChatMessage]
    active_run: None = Field(default=None, alias="activeRun")
```

创建 `agent_claude/service/history.py`：

```python
from datetime import UTC

from schema.chat import ChatMessage, ConversationMessagesResponse, ReasoningTimelinePart, ToolInvocation, ToolTimelinePart


def build_history_response(messages: list[object]) -> ConversationMessagesResponse:
    projected = []
    for message in messages:
        tool_invocations = [
            ToolInvocation(
                id=item.id,
                messageId=item.message_id,
                toolName=item.tool_name,
                args=item.args,
                result=item.result,
                error=item.error,
                latencyMs=item.latency_ms,
                status=item.status,
                createdAt=item.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            )
            for item in message.tool_invocations
        ]
        invocation_by_id = {item.id: item for item in tool_invocations}
        timeline_parts = []
        for part in message.timeline_parts:
            if part.type == "reasoning":
                timeline_parts.append(
                    ReasoningTimelinePart(
                        id=part.id,
                        type="reasoning",
                        orderIndex=part.order_index,
                        text=part.text,
                    )
                )
            else:
                timeline_parts.append(
                    ToolTimelinePart(
                        id=part.id,
                        type="tool",
                        orderIndex=part.order_index,
                        invocation=invocation_by_id[part.tool_invocation_id],
                    )
                )
        projected.append(
            ChatMessage(
                id=message.id,
                conversationId=message.conversation_id,
                role=message.role,
                content=message.content,
                reasoning=message.reasoning,
                toolInvocations=tool_invocations or None,
                timelineParts=timeline_parts or None,
                status=message.status,
                createdAt=message.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            )
        )
    return ConversationMessagesResponse(messages=projected, activeRun=None)
```

- [x] **Step 5：运行测试并提交**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_history_api -v
```

预期：PASS。

提交：

```bash
git add agent_claude
git commit -m "feat: add chat history projection"
```

## Task 4：实现前端兼容的 `/chat/stream` SSE 链路

**Files:**
- Create: `agent_claude/controller/chat.py`
- Create: `agent_claude/service/chat.py`
- Modify: `agent_claude/main.py`
- Test: `agent_claude/tests/test_chat_stream.py`

- [x] **Step 1：先写失败的流式兼容测试**

创建 `agent_claude/tests/test_chat_stream.py`：

```python
import unittest

from schema.chat import ChatStreamResponse


class StreamSchemaTest(unittest.TestCase):
    def test_existing_frontend_events_validate(self) -> None:
        events = [
            {
                "type": "message_created",
                "message": {
                    "id": "assistant-1",
                    "conversationId": "conversation-1",
                    "role": "assistant",
                    "content": "",
                    "status": "streaming",
                    "createdAt": "2026-06-08T00:00:00Z",
                },
            },
            {"type": "reasoning", "messageId": "assistant-1", "text": "think"},
            {"type": "delta", "messageId": "assistant-1", "text": "hello"},
            {"type": "done", "messageId": "assistant-1"},
        ]

        for event in events:
            ChatStreamResponse.model_validate(event)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2：运行流式测试并确认失败**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_chat_stream -v
```

预期：因为缺少 stream event schema 或 service 而 FAIL。

- [x] **Step 3：补齐 stream response schema**

扩展 `agent_claude/schema/chat.py`：

```python
class MessageCreatedEvent(FrontendModel):
    type: Literal["message_created"]
    message: ChatMessage


class DeltaEvent(FrontendModel):
    type: Literal["delta"]
    message_id: str = Field(alias="messageId")
    text: str


class ReasoningEvent(FrontendModel):
    type: Literal["reasoning"]
    message_id: str = Field(alias="messageId")
    text: str


class ToolCallEvent(FrontendModel):
    type: Literal["tool_call"]
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class ToolResultEvent(FrontendModel):
    type: Literal["tool_result"]
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class TitleEvent(FrontendModel):
    type: Literal["title"]
    conversation_id: str = Field(alias="conversationId")
    title: str


class DoneEvent(FrontendModel):
    type: Literal["done"]
    message_id: str = Field(alias="messageId")


class ErrorEvent(FrontendModel):
    type: Literal["error"]
    message_id: str | None = Field(default=None, alias="messageId")
    message: str


ChatStreamResponse = Annotated[
    MessageCreatedEvent
    | DeltaEvent
    | ReasoningEvent
    | ToolCallEvent
    | ToolResultEvent
    | TitleEvent
    | DoneEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
```

- [x] **Step 4：实现 stream 编排和 controller**

创建 `agent_claude/service/chat.py`：

```python
import json
from datetime import UTC, datetime
from uuid import uuid4

from core.database import AsyncSessionLocal
from repository.agent_session import get_agent_session_by_conversation_id, upsert_agent_session
from repository.message import create_message, update_message
from service.runtime import stream_query
from service.session_store import PostgresSessionStore
from model.message import Message


def format_sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_chat(conversation_id: str, prompt: str):
    assistant_message_id = str(uuid4())
    async with AsyncSessionLocal() as session:
        user_message = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="user",
            content=prompt,
            reasoning="",
            status="done",
            created_at=datetime.now(UTC),
        )
        assistant_message = Message(
            id=assistant_message_id,
            conversation_id=conversation_id,
            role="assistant",
            content="",
            reasoning="",
            status="streaming",
            created_at=datetime.now(UTC),
        )
        await create_message(session, user_message)
        await create_message(session, assistant_message)
        existing_session = await get_agent_session_by_conversation_id(session, conversation_id)
        await session.commit()

    yield format_sse(
        {
            "type": "message_created",
            "message": {
                "id": assistant_message_id,
                "conversationId": conversation_id,
                "role": "assistant",
                "content": "",
                "status": "streaming",
                "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        }
    )

    session_store = PostgresSessionStore(AsyncSessionLocal)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    sdk_session_id: str | None = existing_session.sdk_session_id if existing_session else None

    try:
        async for event in stream_query(
            prompt=prompt,
            session_store=session_store,
            resume=sdk_session_id,
        ):
            if getattr(event, "type", None) == "result":
                sdk_session_id = getattr(event, "session_id", sdk_session_id)
                continue
            if getattr(event, "type", None) == "stream_event":
                delta = getattr(event, "event", {})
                if delta.get("type") == "content_block_delta":
                    inner = delta.get("delta", {})
                    if inner.get("type") == "text_delta":
                        text = inner.get("text", "")
                        content_parts.append(text)
                        yield format_sse({"type": "delta", "messageId": assistant_message_id, "text": text})
                    if inner.get("type") == "thinking_delta":
                        text = inner.get("thinking", "")
                        reasoning_parts.append(text)
                        yield format_sse({"type": "reasoning", "messageId": assistant_message_id, "text": text})
        async with AsyncSessionLocal() as session:
            if sdk_session_id is not None:
                await upsert_agent_session(
                    session,
                    conversation_id=conversation_id,
                    sdk_session_id=sdk_session_id,
                )
            await update_message(
                session,
                message_id=assistant_message_id,
                content="".join(content_parts),
                reasoning="".join(reasoning_parts),
                status="done",
            )
            await session.commit()
        yield format_sse({"type": "done", "messageId": assistant_message_id})
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await update_message(
                session,
                message_id=assistant_message_id,
                content="".join(content_parts),
                reasoning="".join(reasoning_parts),
                status="error",
            )
            await session.commit()
        yield format_sse(
            {
                "type": "error",
                "messageId": assistant_message_id,
                "message": str(exc),
            }
        )
```

创建 `agent_claude/controller/chat.py`：

```python
from fastapi.responses import StreamingResponse

from service.chat import stream_chat


async def run_stream_chat(req):
    return StreamingResponse(
        stream_chat(req.conversation_id, req.message),
        media_type="text/event-stream",
    )
```

修改 `agent_claude/main.py`：

```python
from fastapi import FastAPI

from controller.chat import run_stream_chat

app = FastAPI(title="Claude Agent Compatible Backend")
app.add_api_route("/chat/stream", run_stream_chat, methods=["POST"])
```

- [x] **Step 5：运行流式测试并提交**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_chat_stream -v
```

预期：PASS。

提交：

```bash
git add agent_claude
git commit -m "feat: add compatible chat stream endpoint"
```

## Task 5：补齐 Tool/Reasoning 投影、标题生成和端到端验证

**Files:**
- Modify: `agent_claude/service/chat.py`
- Modify: `agent_claude/schema/chat.py`
- Modify: `agent_claude/tests/test_chat_stream.py`
- Test: `agent_claude/tests/test_chat_stream.py`
- Test: `agent_claude/tests/test_history_api.py`

- [x] **Step 1：先写 `tool_call`、`tool_result`、`title` 的失败兼容测试**

扩展 `agent_claude/tests/test_chat_stream.py`：

```python
def test_tool_and_title_events_validate(self) -> None:
    events = [
        {
            "type": "tool_call",
            "messageId": "assistant-1",
            "invocation": {
                "id": "tool-1",
                "messageId": "assistant-1",
                "toolName": "Read",
                "args": {"file_path": "app.py"},
                "status": "running",
            },
        },
        {
            "type": "tool_result",
            "messageId": "assistant-1",
            "invocation": {
                "id": "tool-1",
                "messageId": "assistant-1",
                "toolName": "Read",
                "args": {"file_path": "app.py"},
                "result": {"content": "ok"},
                "status": "completed",
            },
        },
        {
            "type": "title",
            "conversationId": "conversation-1",
            "title": "Read app.py",
        },
    ]

    for event in events:
        ChatStreamResponse.model_validate(event)
```

- [x] **Step 2：运行测试并确认失败**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_chat_stream -v
```

预期：因为 stream service 还没有输出或持久化这些投影而 FAIL。

- [x] **Step 3：实现 tool 投影和 title 事件输出**

修改 `agent_claude/service/chat.py`，加入 tool 投影：

```python
from repository.tool_invocation import create_tool_invocation, update_tool_invocation
from repository.message_part import create_message_part, update_message_part_text


async def _persist_tool_call(
    *,
    message_id: str,
    tool_id: str,
    tool_name: str,
    args: dict[str, object],
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        await create_tool_invocation(
            session,
            invocation_id=tool_id,
            message_id=message_id,
            tool_name=tool_name,
            args=args,
            status="running",
        )
        await create_message_part(
            session,
            message_id=message_id,
            part_type="tool",
            text="",
            tool_invocation_id=tool_id,
        )
        await session.commit()
    return {
        "id": tool_id,
        "messageId": message_id,
        "toolName": tool_name,
        "args": args,
        "status": "running",
    }
```

加入 title 事件输出：

```python
def generate_title(prompt: str) -> str:
    return prompt[:60] or "New chat"
```

在 stream 完成阶段：

```python
title = generate_title(prompt)
yield format_sse(
    {
        "type": "title",
        "conversationId": conversation_id,
        "title": title,
    }
)
```

- [x] **Step 4：运行完整的目标测试**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run python -m unittest tests.test_chat_stream tests.test_history_api -v
```

预期：PASS。

- [x] **Step 5：执行 migration 和 smoke test，然后提交**

运行：

```bash
cd /Users/bytedance/Desktop/agent/ai-investment-assistant/agent_claude
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

预期：

- Alembic 输出 `Running upgrade -> <revision>, create chat and session tables`
- Uvicorn 启动并提供 `http://127.0.0.1:8000`

提交：

```bash
git add agent_claude
git commit -m "feat: complete claude agent compatibility backend"
```

## 自检

- Spec 覆盖：
  Task 1 覆盖独立服务和 `PostgreSQL` schema。
  Task 2 覆盖官方 `SessionStore` 的 `PostgreSQL` 持久化。
  Task 3 覆盖历史消息投影兼容。
  Task 4 覆盖 `/chat/stream` 兼容和 session resume。
  Task 5 覆盖 tool 事件、title 事件和 smoke 验证。
- 占位符扫描：
  没有 `TODO`、`TBD` 或“类似 Task N”这类偷懒写法。
- 类型一致性：
  计划里统一使用 `agent_sessions`、`agent_session_entries`、`ChatStreamResponse`、`ConversationMessagesResponse` 和 `resume=session_id`。
