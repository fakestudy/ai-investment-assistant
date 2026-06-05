# Python Agent FE Stream Design

## Goal

让 Python Agent 的 `/api/chat/stream` 直接输出 FE 已有的 `ChatStreamEvent`，并在首次消息时生成会话标题。

## Scope

- 请求兼容 FE：`conversationId`、`message`，以及可选 `generateTitle`。
- 响应顺序按真实执行过程输出：
  `message_created`、可选 `reasoning`、`tool_call`、`tool_result`、`delta`、可选 `title`、`done`。
- `tool_call_chunks` 必须合并成完整参数后再输出 `tool_call`。
- `ToolMessage` 输出为同一调用 ID 的 `tool_result`。
- 标题生成失败时回退为用户输入的前 60 个字符，不影响正文回答。
- FE 仅在当前标题为 `New chat` 时传 `generateTitle: true`。

## Non-goals

- 会话和消息持久化。
- 历史上下文、重新生成、编辑后重试。
- 流恢复和取消。

## Error Handling

- Agent 主流程异常输出 `error`，携带已创建的 assistant `messageId`。
- 标题生成异常只触发标题回退，不把已经完成的回答标记为失败。

