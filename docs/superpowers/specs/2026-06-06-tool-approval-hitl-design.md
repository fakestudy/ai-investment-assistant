# Tool Approval HITL Design

## 1. Goal

Add production-grade tool approval to the Python Agent chat path.

The first version supports:

- approval only for explicitly configured tools
- `get_weather` as the only approval-required tool
- `approve` and `reject` decisions
- multiple tool requests reviewed individually and submitted as one batch
- PostgreSQL-backed Agent checkpoints
- page refresh and service restart recovery
- a 30-minute approval timeout that automatically rejects pending tools
- inline approval cards in both live streams and message history
- concurrent runs across different conversations

The first version does not support:

- editing tool arguments
- answering on behalf of a tool
- workflow-node approval
- approver identity or authorization
- multiple active runs in the same conversation

The approval domain should remain extensible to workflow-node approval, but no
workflow approval behavior is implemented now.

## 2. Current Problems

The current code configures:

```python
HumanInTheLoopMiddleware(interrupt_on={"get_weather": True})
```

but does not provide the infrastructure required by a complete HITL flow:

- no LangGraph checkpointer
- no stable `thread_id`
- no handling of `__interrupt__`
- no durable run or approval state
- no approval submission API
- no resume command
- no stream event replay
- no frontend approval state
- no historical approval projection

With the current `stream_mode="messages"` path, the interrupt is not exposed to
the frontend and the stream can incorrectly reach its normal completion path.

## 3. Architecture

Use five ownership layers:

1. **LangGraph PostgreSQL Checkpointer**
   - Stores resumable Agent execution state.
   - Uses `agent_runs.id` as LangGraph `thread_id`.
   - Is managed by LangGraph, not by project ORM repositories.

2. **PostgreSQL business entities**
   - Store runs, approval batches, individual decisions, stream events, and
     transactional outbox messages.
   - Are the source of truth for business status and history.

3. **RabbitMQ command transport**
   - Delivers start, resume, and approval-timeout commands.
   - Uses at-least-once delivery.
   - Never acts as the source of truth for run or approval status.

4. **Agent workers**
   - Consume commands, claim runs transactionally, invoke or resume LangGraph,
     and persist resulting events.

5. **HTTP/SSE API**
   - Creates commands transactionally.
   - Streams persisted events to the frontend.
   - Does not own the Agent execution lifecycle.

This separates execution truth, business truth, command delivery, and client
transport.

## 4. Data Model

### 4.1 `agent_runs`

One row represents one Agent execution triggered by one user message.

Fields:

| Field | Meaning |
| --- | --- |
| `id` | Run ID and LangGraph `thread_id` |
| `conversation_id` | Owning conversation |
| `user_message_id` | Triggering user message |
| `assistant_message_id` | Assistant message being produced |
| `status` | Run state |
| `version` | Optimistic concurrency version |
| `lease_owner` | Worker currently owning execution |
| `lease_expires_at` | Worker lease expiry used for crash recovery |
| `active_command_id` | Stable command currently being executed |
| `error` | Terminal failure detail |
| `created_at` | Creation time |
| `updated_at` | Last state transition |
| `completed_at` | Terminal completion time |

Statuses:

```text
queued
running
awaiting_approval
resume_queued
resuming
completed
failed
```

A partial unique index on `conversation_id` prevents more than one run in
`queued`, `running`, `awaiting_approval`, `resume_queued`, or `resuming`.

Different conversations may have active runs concurrently.

### 4.2 `approval_batches`

One row represents one LangGraph interrupt. A run may produce multiple batches
sequentially.

Fields:

| Field | Meaning |
| --- | --- |
| `id` | Batch ID |
| `agent_run_id` | Owning run |
| `assistant_message_id` | Message containing the approval timeline part |
| `interrupt_id` | LangGraph interrupt ID |
| `sequence` | Batch order inside the run |
| `status` | Batch state |
| `expires_at` | Creation time plus 30 minutes |
| `resolution_source` | `manual` or `timeout` |
| `created_at` | Creation time |
| `resolved_at` | Resolution time |

Statuses:

```text
pending
resolved
expired
```

### 4.3 `approval_requests`

One row represents one tool call requiring approval within a batch.

Fields:

| Field | Meaning |
| --- | --- |
| `id` | Approval request ID |
| `approval_batch_id` | Owning batch |
| `tool_invocation_id` | Existing tool invocation |
| `order_index` | Decision order required by LangGraph |
| `tool_name` | Tool name snapshot |
| `args` | Tool arguments snapshot |
| `decision` | Individual decision |
| `decided_at` | Decision time |

Decisions:

```text
pending
approved
rejected
expired
```

The first version stores no approver ID. Authentication and approver identity
may be added later through a separate migration.

### 4.4 `agent_run_events`

This is the durable SSE replay log.

Fields:

| Field | Meaning |
| --- | --- |
| `id` | Monotonic event ID used as SSE `id` |
| `agent_run_id` | Owning run |
| `event_type` | Frontend event type |
| `payload` | JSON event payload |
| `created_at` | Event creation time |

All live events are persisted before delivery. A disconnected client resumes
from `afterEventId` without affecting Agent execution.

### 4.5 `outbox_events`

This table solves the PostgreSQL and RabbitMQ dual-write problem.

Fields:

| Field | Meaning |
| --- | --- |
| `id` | Outbox event ID and MQ message ID |
| `event_type` | Command type |
| `aggregate_id` | Run or approval batch ID |
| `payload` | JSON command payload |
| `status` | `pending`, `publishing`, or `published` |
| `attempt_count` | Publish attempts |
| `available_at` | Earliest publish time |
| `published_at` | Confirmed publish time |
| `last_error` | Latest publish failure |
| `created_at` | Creation time |

The outbox publisher uses RabbitMQ publisher confirms. It marks an event
`published` only after broker confirmation. Duplicate delivery is allowed.

### 4.6 Existing Entity Changes

Extend `tool_invocations.status`:

```text
awaiting_approval
running
completed
error
rejected
expired
```

Add nullable `approval_batch_id` to `message_parts`.

An approval interrupt creates a `message_parts` row with `type="approval"` so
the decision process retains its exact position in the assistant timeline.

## 5. RabbitMQ Topology

Use durable exchanges, durable quorum queues, persistent messages, publisher
confirms, manual consumer acknowledgements, and dead-letter routing.

Command routing keys:

```text
agent.run.start
agent.run.resume
approval.timeout.schedule
approval.timeout.ready
```

Timeout topology:

```text
approval.timeout.delay
  -- fixed 30-minute TTL and DLX -->
approval.timeout.ready
```

The delayed message contains only stable identifiers and timing metadata:

```json
{
  "batchId": "batch-1",
  "expiresAt": "2026-06-06T12:30:00Z"
}
```

The timeout consumer always re-reads PostgreSQL:

- resolved batch: ACK and do nothing
- pending and expired batch: atomically expire it and enqueue resume
- pending but not yet expired batch: reject or re-schedule according to the
  remaining delay

If an outbox timeout command is published after `expires_at`, the publisher
routes it directly to `approval.timeout.ready`.

## 6. Transaction Boundaries

### 6.1 Start Run

One PostgreSQL transaction creates:

- user message
- assistant placeholder message
- `agent_runs(status="queued")`
- `outbox_events(event_type="agent.run.start")`

The HTTP handler then subscribes to the persisted run event stream.

### 6.2 Create Approval Batch

When LangGraph emits an interrupt, one transaction creates or updates:

- `approval_batches(status="pending")`
- all `approval_requests(decision="pending")`
- related `tool_invocations(status="awaiting_approval")`
- approval `message_parts`
- `agent_runs(status="awaiting_approval")`
- `agent_run_events(event_type="approval_required")`
- `outbox_events(event_type="approval.timeout.schedule")`

The current SSE response ends after the persisted `approval_required` event.
It does not emit `done`.

### 6.3 Submit Manual Decisions

One transaction:

- locks the approval batch
- verifies it is still pending and not expired
- verifies every request appears exactly once
- saves `approved` or `rejected` for every request
- marks the batch `resolved` with `resolution_source="manual"`
- writes `resolved_at`
- writes an `approval_resolved` run event
- moves the run to `resume_queued`
- creates `outbox_events(event_type="agent.run.resume")`

The HTTP response subscribes to the same run event stream after the approval
event that preceded submission.

### 6.4 Expire Approval Batch

The timeout consumer transaction:

- locks the batch
- no-ops if it is no longer pending
- marks pending requests `expired`
- marks the batch `expired` with `resolution_source="timeout"`
- moves the run to `resume_queued`
- creates `outbox_events(event_type="agent.run.resume")`

For LangGraph, every expired request maps to a `reject` decision with an
approval-timeout explanation.

## 7. API Contract

Follow the repository's action-oriented POST style.

### 7.1 Start Chat Stream

```http
POST /api/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

The request keeps the current frontend contract.

The backend creates the run internally. The client does not call a separate
run-creation endpoint.

The first run-level event is:

```json
{
  "type": "run_created",
  "runId": "run-1",
  "conversationId": "conversation-1",
  "messageId": "assistant-1"
}
```

### 7.2 Resume Stream Transport

```http
POST /api/chat/stream/resume
Content-Type: application/json
Accept: text/event-stream
```

Request:

```json
{
  "runId": "run-1",
  "afterEventId": 42
}
```

This endpoint resumes client transport only. It does not resume LangGraph. It
replays persisted events after the cursor and then waits for new events until
the run reaches a stable boundary.

### 7.3 Submit Approval Decisions

```http
POST /api/chat/approval/decisions/{batchId}
Content-Type: application/json
Accept: text/event-stream
```

Request:

```json
{
  "decisions": [
    {
      "approvalRequestId": "request-1",
      "decision": "approve"
    },
    {
      "approvalRequestId": "request-2",
      "decision": "reject"
    }
  ],
  "afterEventId": 42
}
```

The endpoint persists the complete batch atomically, enqueues resume through
the outbox, and returns the resumed run's SSE stream.

Repeated identical submission returns the existing result and does not enqueue
a second resume command. A conflicting or stale submission returns `409`.

## 8. SSE Contract

Add:

```text
run_created
approval_required
approval_resolved
```

Keep:

```text
message_created
reasoning
tool_call
tool_result
delta
title
done
error
```

Every persisted event has:

- SSE `id` from `agent_run_events.id`
- `runId` in the JSON payload

`approval_required` payload:

```json
{
  "type": "approval_required",
  "runId": "run-1",
  "messageId": "assistant-1",
  "batch": {
    "id": "batch-1",
    "status": "pending",
    "expiresAt": "2026-06-06T12:30:00Z",
    "requests": [
      {
        "id": "request-1",
        "toolInvocationId": "call-1",
        "toolName": "get_weather",
        "args": {
          "city": "Beijing"
        },
        "decision": "pending"
      }
    ]
  }
}
```

The stream reaches one of these boundaries:

- `done`
- `error`
- `approval_required`

Only `done` and `error` are terminal Run states.

## 9. Agent Execution

Create the Agent with:

- PostgreSQL checkpointer
- `HumanInTheLoopMiddleware`
- `get_weather` configured with only `approve` and `reject`
- `agent_runs.id` as `configurable.thread_id`

The worker consumes:

### Start command

```python
agent.stream(
    {"messages": input_messages},
    config={"configurable": {"thread_id": run_id}},
    stream_mode=["messages", "updates"],
)
```

`updates` is required to observe `__interrupt__`; `messages` continues to carry
reasoning, tool, and text output.

### Resume command

```python
agent.stream(
    Command(resume={"decisions": decisions}),
    config={"configurable": {"thread_id": run_id}},
    stream_mode=["messages", "updates"],
)
```

The worker claims a command through conditional database transitions so a
duplicate MQ delivery does not normally execute the same start or resume twice.
The claim records `active_command_id`, `lease_owner`, and `lease_expires_at`.

Before applying a resume command, the worker reads the latest checkpoint and
verifies that the expected `interrupt_id` is still pending:

- matching interrupt: apply `Command(resume=...)`
- interrupt already consumed: reconcile business projections and ACK
- different interrupt: mark the command stale and fail the Run for inspection

This checkpoint reconciliation closes the crash window where LangGraph
advanced but the worker died before updating `agent_runs`.

## 10. Frontend State

Replace global single-stream state with per-conversation state:

```ts
type ConversationRunState = {
  runId: string;
  status: "streaming" | "awaiting_approval" | "resuming";
  lastEventId?: number;
  approvalBatch?: ApprovalBatch;
};

runsByConversationId: Record<string, ConversationRunState>;
```

Rules:

- one active stream controller per conversation
- different conversations may stream concurrently
- only the current conversation is input-locked
- `streaming`, `awaiting_approval`, and `resuming` lock input
- `completed` and `failed` release input
- events are reduced idempotently by event ID

## 11. Approval UI

Render approval inside the assistant message timeline at the persisted approval
part position.

The card displays:

- tool name
- read-only arguments
- expiration time
- one approve/reject choice per request
- submit button enabled only when every request has a decision

The card behavior:

- disables controls while submitting
- switches to read-only after resolution
- shows manual approval or rejection
- shows automatic timeout rejection
- reloads active run state after a `409` conflict

Argument editing is explicitly excluded.

## 12. Message History

Extend `ChatTimelinePart` with:

```ts
type ApprovalTimelinePart = {
  id: string;
  type: "approval";
  orderIndex: number;
  batch: {
    id: string;
    status: "pending" | "resolved" | "expired";
    expiresAt: string;
    resolutionSource?: "manual" | "timeout";
    resolvedAt?: string;
    requests: {
      id: string;
      toolInvocationId: string;
      toolName: string;
      args: Record<string, unknown>;
      decision: "pending" | "approved" | "rejected" | "expired";
      decidedAt?: string;
    }[];
  };
};
```

The history API rebuilds approval timeline parts from:

- `message_parts`
- `approval_batches`
- `approval_requests`
- `tool_invocations`

Live SSE and history responses use the same approval data shape.

History stores only formal submitted decisions. Temporary frontend selections
before submission are not audited.

The conversation history response also includes the active Run summary when
one exists. The frontend restores a pending approval card directly or resumes
the stream transport for `running` and `resuming` runs.

## 13. Error Handling

### PostgreSQL transaction failure

- Return an HTTP error before subscribing to SSE when run creation fails.
- Do not publish any MQ command without a committed outbox row.

### RabbitMQ unavailable

- Keep outbox events pending.
- Retry with bounded backoff.
- Do not lose the run or timeout command.
- Surface operational health separately from user-visible Agent errors.

### Duplicate MQ delivery

- Use stable command IDs.
- Guard state transitions with row locks and expected statuses.
- ACK commands whose effect already exists.

### Worker failure during Agent execution

- Persist stream events before exposing them.
- Retain LangGraph checkpoints.
- Redeliver the unacknowledged RabbitMQ command.
- Reclaim an expired worker lease.
- Reconcile the expected interrupt against the latest checkpoint before
  invoking or resuming again.
- Do not claim exactly-once model execution; RabbitMQ and model calls are
  at-least-once. Business state transitions, approval decisions, and tool
  execution records must remain idempotent.

### Approval race

- Manual approval and timeout consumer compete on the locked batch row.
- Exactly one transition from `pending` succeeds.
- The loser becomes a no-op or receives `409`.

### Stream disconnect

- Never cancel Agent execution because the HTTP client disconnected.
- Reconnect with `runId` and `afterEventId`.

## 14. Testing

### Backend unit tests

- whitelist requires approval only for `get_weather`
- allowed decisions contain only approve and reject
- interrupt produces one batch and ordered requests
- complete manual decisions produce one resume command
- incomplete or duplicate decisions are rejected
- stale and conflicting submissions return `409`
- timeout maps every pending request to LangGraph reject
- duplicate MQ messages are idempotent
- stale worker leases can be reclaimed
- resume redelivery reconciles an already-consumed checkpoint interrupt

### Transaction tests

- run and start outbox event commit together
- approval batch, requests, timeline part, timeout outbox, and run status commit
  together
- manual decision and resume outbox commit together
- rollback leaves neither business state nor outbox state partially written

### RabbitMQ integration tests

- publisher confirm marks outbox event published
- publish failure leaves event retryable
- 30-minute TTL message reaches the ready queue through DLX
- timeout consumer ACKs already resolved batches
- consumer failure causes redelivery without duplicate resume

### SSE integration tests

- initial POST emits `run_created`
- approval interrupt emits `approval_required` and no `done`
- approval POST returns continued SSE output
- resume POST replays only events after `afterEventId`
- duplicate replay events do not duplicate frontend content

### Persistence and history tests

- restart can resume a pending LangGraph interrupt
- historical messages include approval timeline parts
- approved, rejected, and timed-out decisions retain their original order
- active Run summary restores input locking after refresh

### Frontend tests

- different conversations can stream concurrently
- pending approval locks only its conversation
- submit requires every item to be selected
- approval cards become read-only after resolution
- timeout renders automatic rejection
- history and live events render the same card

## 15. Deployment

Add RabbitMQ to Docker Compose for local development.

Production deployment requires:

- RabbitMQ durable storage
- quorum queues
- publisher confirms
- manual acknowledgements
- dead-letter monitoring
- outbox backlog monitoring
- pending approval age monitoring
- worker health checks
- PostgreSQL checkpoint migrations

API, outbox publisher, and Agent consumers may initially run from the same
Python package, but must be separate process roles so they can scale and restart
independently.

## 16. Final Scope

The implementation delivers a production-grade approval foundation for tool
calls while keeping the first user-facing behavior narrow:

- only `get_weather`
- only approve or reject
- one active Run per conversation
- different conversations execute concurrently
- 30-minute automatic rejection
- durable resume, replay, decisions, and history

Workflow-node approval, argument editing, approver identity, and general
authorization remain future work.
