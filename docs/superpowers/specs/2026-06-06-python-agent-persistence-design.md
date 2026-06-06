# Python Agent Persistence Design

## Goal

Bring the Python Agent persistence model closer to the existing Go Backend MVP for Agent conversations.

This design covers only these four items:

- Persist tool calls in `tool_invocations`.
- Persist assistant messages as `streaming` before model output starts, then update to `done` or `error`.
- Persist reasoning and tool steps in `message_parts` as an ordered timeline.
- Return `toolInvocations` and `timelineParts` from conversation message history.

This design explicitly excludes stream cancel, stream resume, `parentMessageId`, and `regenerateFromMessageId`.

## Current State

Python already emits frontend-compatible stream events:

- `message_created`
- `reasoning`
- `tool_call`
- `tool_result`
- `delta`
- `title`
- `done`
- `error`

Python currently persists:

- user messages before model streaming starts
- final assistant message after stream completion
- assistant `content`
- assistant `reasoning`
- assistant final `status`

Python does not currently persist:

- tool invocation records
- ordered reasoning/tool timeline parts
- assistant messages while still `streaming`

## Recommended Approach

Use the existing Go Backend shape as the source of truth, but implement only the persistence subset needed by Python.

Alternatives considered:

- Only add `tool_invocations`: too small, because history still cannot reconstruct the Agent timeline.
- Add stream manager now: too large, because cancel/resume requires runtime state and new APIs.
- Add `tool_invocations`, `message_parts`, and assistant streaming persistence now: best fit for the requested four-item scope.

## Data Model

Add `ToolInvocation` model:

- `id`: string primary key, using the LangChain tool call id when available.
- `message_id`: foreign key to `messages.id`, cascade delete.
- `tool_name`: string.
- `args`: JSON.
- `result`: JSON nullable.
- `error`: text nullable.
- `latency_ms`: integer nullable.
- `status`: `running`, `completed`, or `error`.
- `created_at`: timezone-aware datetime.

Add `MessagePart` model:

- `id`: string primary key.
- `message_id`: foreign key to `messages.id`, cascade delete.
- `type`: `reasoning` or `tool`.
- `order_index`: integer.
- `text`: text, used by reasoning parts.
- `tool_invocation_id`: nullable foreign key to `tool_invocations.id`, used by tool parts.
- `created_at`: timezone-aware datetime.

Keep `messages.reasoning` as the final flattened reasoning string for simple history/context use.

## Repository Layer

Add `repository/tool_invocation.py`:

- `create_tool_invocation(session, invocation)`
- `update_tool_invocation(session, *, invocation_id, result, error, latency_ms, status)`

Add `repository/message_part.py`:

- `create_message_part(session, part)`
- `update_message_part_text(session, *, part_id, text)`

Extend `repository/message.py`:

- add `update_message(session, *, message_id, content, reasoning, status)`
- update `get_messages_by_conversation_id` to eager-load tool invocations and parts for history API use.

Repository remains responsible for `flush()`. Service remains responsible for `commit()`.

## Service Flow

`iter_chat_events_with_persistence` should become the persistence coordinator.

On `message_created`:

- create assistant `Message` immediately
- set `role="assistant"`
- set `content=""`
- set `reasoning=""`
- set `status="streaming"`
- commit before yielding or immediately after receiving the event

On `reasoning`:

- append text to in-memory `assistant_reasoning`
- write/update `message_parts`
- if the previous part is also `reasoning`, update that part text instead of creating a new part
- if the previous part is not `reasoning`, create a new reasoning part with the next `order_index`

On `tool_call`:

- create `ToolInvocation` with `status="running"`
- create a `MessagePart` with `type="tool"` and `tool_invocation_id`
- commit before yielding the event where practical, so history can observe the running tool call

On `tool_result`:

- update the corresponding `ToolInvocation`
- set `status="completed"` when result is present
- set `status="error"` when error is present
- store latency if available

On `delta`:

- append text to in-memory `assistant_content`
- do not write every delta to DB, to avoid excessive writes

On `done`:

- update assistant message with final `content`, final `reasoning`, and `status="done"`

On `error`:

- update assistant message with partial `content`, partial `reasoning`, and `status="error"`

## History API

`get_conversation_messages` should return each `ChatMessage` with:

- existing message fields
- `toolInvocations`
- `timelineParts`

The returned shape should reuse the existing schema in `schema/chat.py`:

- `ToolInvocation`
- `ReasoningTimelinePart`
- `ToolTimelinePart`
- `ChatMessage`

Timeline ordering must use `order_index asc`.

Tool invocation ordering should use `created_at asc`.

## Transaction Boundary

Each stream event persistence operation may use a short-lived DB session, matching the current design that avoids holding a DB session during model streaming.

This keeps the current property:

- model streaming does not monopolize a database connection
- each durable event commits independently
- partial data survives if the stream fails after a tool call or reasoning part

## Error Handling

If tool persistence fails, the stream should fail rather than silently diverge from the database.

If final message update fails, emit an `error` event if possible.

If the model raises, persist assistant partial output as `error`.

## Tests

Add or update focused tests for:

- assistant message is persisted as `streaming` when `message_created` is observed
- final assistant message is updated to `done`
- tool call creates `ToolInvocation(status="running")`
- tool result updates invocation to `completed` or `error`
- reasoning and tool steps produce ordered `MessagePart` rows
- history API returns `toolInvocations` and `timelineParts`

## Non-Goals

Do not implement:

- stream cancellation
- stream resume
- event replay cache
- `parentMessageId`
- `regenerateFromMessageId`
- persistent checkpoints
