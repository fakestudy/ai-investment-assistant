# Backend 数据表结构

本文档整理当前 Go `backend` 层的数据库表结构。

数据表由 GORM `AutoMigrate` 自动创建，模型定义来自 `backend/internal/store/models.go`，迁移入口来自 `backend/internal/store/store.go`。

## 总览

当前后端共注册 4 个持久化模型，因此默认会生成 4 张表：

| GORM 模型 | 默认表名 | 用途 |
| --- | --- | --- |
| `Conversation` | `conversations` | 会话表 |
| `Message` | `messages` | 消息表 |
| `ToolInvocation` | `tool_invocations` | 工具调用记录表 |
| `MessagePart` | `message_parts` | 消息分片表 |

> 说明：表名为 GORM 默认命名规则推导结果，代码中没有显式定义 `TableName()`。

## 1. conversations

对应模型：`Conversation`

用途：保存一轮对话会话的基础信息。

| 字段 | Go 类型 | GORM 约束 | 含义 |
| --- | --- | --- | --- |
| `id` | `string` | `primaryKey` | 会话 ID，主键 |
| `title` | `string` | 无显式约束 | 会话标题 |
| `created_at` | `time.Time` | 无显式约束 | 创建时间 |
| `updated_at` | `time.Time` | 无显式约束 | 更新时间 |

模型中的关联字段：

| 字段 | Go 类型 | 数据库字段 | 含义 |
| --- | --- | --- | --- |
| `Messages` | `[]Message` | 不直接生成字段 | 一个会话下的消息列表 |

关联关系：

| 关系 | 外键 | 删除行为 |
| --- | --- | --- |
| `Conversation` 1 对多 `Message` | `messages.conversation_id` | 删除会话时级联删除消息 |

## 2. messages

对应模型：`Message`

用途：保存会话中的单条消息，包括用户消息、助手消息，以及消息级别的状态和 reasoning 内容。

| 字段 | Go 类型 | GORM 约束 | 含义 |
| --- | --- | --- | --- |
| `id` | `string` | `primaryKey` | 消息 ID，主键 |
| `conversation_id` | `string` | `index;not null` | 所属会话 ID，外键，带索引，非空 |
| `role` | `string` | 无显式约束 | 消息角色，例如 user / assistant |
| `content` | `string` | 无显式约束 | 消息正文 |
| `reasoning` | `string` | 无显式约束 | 模型思考内容或 reasoning 文本 |
| `status` | `string` | 无显式约束 | 消息状态 |
| `created_at` | `time.Time` | 无显式约束 | 创建时间 |

模型中的关联字段：

| 字段 | Go 类型 | 数据库字段 | 含义 |
| --- | --- | --- | --- |
| `Conversation` | `Conversation` | 不直接生成业务字段 | 所属会话对象 |
| `ToolInvocations` | `[]ToolInvocation` | 不直接生成字段 | 当前消息关联的工具调用列表 |
| `Parts` | `[]MessagePart` | 不直接生成字段 | 当前消息关联的消息分片列表 |

关联关系：

| 关系 | 外键 | 删除行为 |
| --- | --- | --- |
| `Message` 多对一 `Conversation` | `messages.conversation_id` | 依赖 `Conversation.Messages` 的级联配置 |
| `Message` 1 对多 `ToolInvocation` | `tool_invocations.message_id` | 删除消息时级联删除工具调用 |
| `Message` 1 对多 `MessagePart` | `message_parts.message_id` | 删除消息时级联删除消息分片 |

## 3. tool_invocations

对应模型：`ToolInvocation`

用途：保存 Agent / LLM 在生成某条消息时发生的工具调用，包括工具名、参数、结果、错误、耗时和状态。

| 字段 | Go 类型 | GORM 约束 | 含义 |
| --- | --- | --- | --- |
| `id` | `string` | `primaryKey` | 工具调用 ID，主键 |
| `message_id` | `string` | `index;not null` | 所属消息 ID，外键，带索引，非空 |
| `tool_name` | `string` | 无显式约束 | 工具名称 |
| `args` | `datatypes.JSON` | 无显式约束 | 工具调用入参，Postgres 下通常映射为 JSONB |
| `result` | `datatypes.JSON` | 无显式约束 | 工具调用结果，Postgres 下通常映射为 JSONB |
| `error` | `string` | 无显式约束 | 工具调用错误信息 |
| `latency_ms` | `int64` | 无显式约束 | 工具调用耗时，单位毫秒 |
| `status` | `string` | 无显式约束 | 工具调用状态 |
| `created_at` | `time.Time` | 无显式约束 | 创建时间 |

模型中的关联字段：

| 字段 | Go 类型 | 数据库字段 | 含义 |
| --- | --- | --- | --- |
| `Message` | `Message` | 不直接生成业务字段 | 所属消息对象 |

关联关系：

| 关系 | 外键 | 删除行为 |
| --- | --- | --- |
| `ToolInvocation` 多对一 `Message` | `tool_invocations.message_id` | 依赖 `Message.ToolInvocations` 的级联配置 |

## 4. message_parts

对应模型：`MessagePart`

用途：保存一条消息内部更细粒度的内容片段，例如文本片段、工具调用相关片段，或未来扩展的结构化 part。

| 字段 | Go 类型 | GORM 约束 | 含义 |
| --- | --- | --- | --- |
| `id` | `string` | `primaryKey` | 消息分片 ID，主键 |
| `message_id` | `string` | `index;not null` | 所属消息 ID，外键，带索引，非空 |
| `type` | `string` | 无显式约束 | 分片类型 |
| `order_index` | `int` | 无显式约束 | 分片在消息内的展示顺序 |
| `text` | `string` | 无显式约束 | 分片文本内容 |
| `tool_invocation_id` | `*string` | 无显式约束 | 可选关联的工具调用 ID |
| `created_at` | `time.Time` | 无显式约束 | 创建时间 |

模型中的关联字段：

| 字段 | Go 类型 | 数据库字段 | 含义 |
| --- | --- | --- | --- |
| `Message` | `Message` | 不直接生成业务字段 | 所属消息对象 |
| `ToolInvocation` | `*ToolInvocation` | 不直接生成业务字段 | 可选关联的工具调用对象 |

关联关系：

| 关系 | 外键 | 删除行为 |
| --- | --- | --- |
| `MessagePart` 多对一 `Message` | `message_parts.message_id` | 依赖 `Message.Parts` 的级联配置 |
| `MessagePart` 可选关联 `ToolInvocation` | `message_parts.tool_invocation_id` | 代码中未显式声明级联删除 |

## 表关系图

```text
conversations
  id
  └── messages.conversation_id
        messages
          id
          ├── tool_invocations.message_id
          │     tool_invocations
          │       id
          │       └── message_parts.tool_invocation_id optional
          └── message_parts.message_id
                message_parts
```

## 关键设计点

### Conversation

`Conversation` 是对话容器，主要负责聚合消息。

它本身只保存标题和时间信息，不保存完整对话内容。

### Message

`Message` 是聊天记录的核心表。

如果只做最简单的聊天记录存储，理论上 `content` 和 `reasoning` 已经可以覆盖大部分展示需求。

### ToolInvocation

`ToolInvocation` 把工具调用从消息正文中拆出来，适合做结构化查询和调试。

例如后续可以单独查询：

| 问题 | 依赖字段 |
| --- | --- |
| 某条消息调用了哪些工具 | `message_id`, `tool_name` |
| 哪些工具调用失败了 | `status`, `error` |
| 工具平均耗时是多少 | `latency_ms` |
| 某次工具调用的参数和结果是什么 | `args`, `result` |

### MessagePart

`MessagePart` 把一条消息拆成多个片段，适合表达复杂 AI 消息结构。

例如：

| 顺序 | type | text / 关联 |
| --- | --- | --- |
| 1 | `reasoning` | 思考内容 |
| 2 | `tool_call` | 关联某条 `tool_invocations.id` |
| 3 | `text` | 最终回答 |

## 当前设计的取舍

当前 4 表设计更偏向“可观测 Agent 对话系统”，而不是最小聊天应用。

优点：

| 设计 | 收益 |
| --- | --- |
| 工具调用独立成表 | 方便排查、统计、重放和状态追踪 |
| 消息分片独立成表 | 方便表达复杂消息时间线 |
| 外键和级联删除 | 会话、消息删除时更容易保持数据一致 |

代价：

| 设计 | 成本 |
| --- | --- |
| 多表结构 | 查询和写入逻辑更复杂 |
| `message_parts` | 如果当前只展示纯文本，收益不明显 |
| `tool_invocations` | 如果暂不需要工具调用统计，可能偏重 |

如果当前目标是严格 MVP，可以考虑简化为：

| 表 | 字段方向 |
| --- | --- |
| `conversations` | 保存会话标题和时间 |
| `messages` | 保存消息正文、reasoning、状态、工具调用 JSON、parts JSON |

等未来真的需要工具调用检索、复杂消息渲染或 Agent trace 时，再把 JSON 字段迁移成独立表。
