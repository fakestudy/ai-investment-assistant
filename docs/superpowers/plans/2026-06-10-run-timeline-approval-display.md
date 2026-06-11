# Run Timeline Approval Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace approval-as-a-message-card with a unified run timeline where tool approvals are tool states and the only approval action surface is a multi-request approval dock.

**Architecture:** `agent_claude` owns the display contract: history and SSE project a stable `timelineItems` array for each assistant message. The frontend renders process details as a lightweight disclosure, renders only tools as structured items, and uses `activeRun.approvalBatch` only for the current approval dock.

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy in `agent_claude`; Next/React/Zustand/tsx tests in `web`.

---

### Task 1: Backend Timeline Contract

**Files:**
- Modify: `agent_claude/schema/chat.py`
- Modify: `agent_claude/service/history.py`
- Test: `agent_claude/tests/test_history_api.py`

- [ ] **Step 1: Write failing schema/projection tests**
  - Assert history messages serialize `timelineItems`.
  - Assert a pending approval batch is attached to the matching tool item by `toolInvocationId`.
  - Assert pending approval is not projected as a standalone approval timeline item.

- [ ] **Step 2: Run targeted tests and verify RED**
  - Run: `mise exec -- uv run python -m unittest tests.test_history_api.HistoryProjectionTest -v`
  - Expected: failures mentioning missing `timelineItems` or missing tool approval.

- [ ] **Step 3: Implement schema and projection**
  - Add `ToolApprovalState`, `ThoughtTimelineItem`, `ToolTimelineItem`, and `RunTimelineItem`.
  - Add `timeline_items` / alias `timelineItems` to `ChatMessage`.
  - Project existing `message_parts` into both legacy `timelineParts` and new `timelineItems` during migration.
  - When `activeRun.approvalBatch` exists, attach each request to the matching tool item; if a request has no matching tool invocation yet, create a tool item with `status="awaiting_approval"`.

- [ ] **Step 4: Verify GREEN**
  - Run the same unittest command.

### Task 2: Backend SSE Timeline Events

**Files:**
- Modify: `agent_claude/schema/chat.py`
- Modify: `agent_claude/service/approval_gate.py`
- Modify: `agent_claude/service/chat_stream.py`
- Modify: `agent_claude/service/run_manager.py`
- Test: `agent_claude/tests/test_approval_flow.py`
- Test: `agent_claude/tests/test_stream_persistence.py`

- [ ] **Step 1: Write failing event tests**
  - Approval required emits a `timeline_item_added` or `timeline_item_updated` tool item with approval state.
  - Approval resolved emits a tool item update for each request decision.
  - Tool result updates the same tool item id.

- [ ] **Step 2: Run targeted tests and verify RED**
  - Run: `mise exec -- uv run python -m unittest tests.test_approval_flow tests.test_stream_persistence -v`

- [ ] **Step 3: Implement compatibility events**
  - Keep legacy events during migration.
  - Add new `timeline_item_added` / `timeline_item_updated` events so the frontend can stop deriving display state from approval cards.

- [ ] **Step 4: Verify GREEN**
  - Run the same targeted tests.

### Task 3: Frontend State Contract

**Files:**
- Modify: `web/features/chat/types.ts`
- Modify: `web/features/chat/chat-event-reducer.ts`
- Modify: `web/features/chat/chat-ui-state.ts`
- Modify: `web/features/chat/store.ts`
- Test: `web/features/chat/chat-event-reducer.test.ts`
- Test: `web/features/chat/store.test.ts`

- [ ] **Step 1: Write failing reducer/store tests**
  - Reducer adds and updates `timelineItems`.
  - Approval events update `activeRun.approvalBatch` but do not inject approval parts into message timeline.
  - `selectConversation` keeps `activeRun.approvalBatch` for the dock and does not project it into message parts.

- [ ] **Step 2: Run frontend tests and verify RED**
  - Run: `pnpm dlx tsx --test features/chat/chat-event-reducer.test.ts features/chat/store.test.ts`

- [ ] **Step 3: Implement new frontend types and reducer**
  - Add `RunTimelineItem` and timeline event types.
  - Remove `projectActiveApprovalBatch`.
  - Keep legacy `timelineParts` fallback while components migrate.

- [ ] **Step 4: Verify GREEN**
  - Run the same frontend test command.

### Task 4: Frontend UI

**Files:**
- Create: `web/features/chat/components/process-disclosure.tsx`
- Create: `web/features/chat/components/tool-trace-item.tsx`
- Modify: `web/features/chat/components/chat-message-item.tsx`
- Modify: `web/features/chat/components/chat-message-timeline.tsx` or replace its usage
- Modify: `web/features/chat/components/approval-card.tsx`
- Modify: `web/features/chat/components/chat-input.tsx`
- Test: `web/features/chat/components/approval-card.test.tsx`
- Test: `web/features/chat/chat-ui-state.test.ts`

- [ ] **Step 1: Write failing render tests**
  - Process disclosure renders no numbered steps.
  - Tool rows render an icon and state.
  - Multi-request approval renders each request with query/url and two equal-width decisions below it.

- [ ] **Step 2: Run tests and verify RED**
  - Run: `pnpm dlx tsx --test features/chat/components/approval-card.test.tsx features/chat/chat-ui-state.test.ts`

- [ ] **Step 3: Implement UI components**
  - Lightweight process row: `已处理 18s` style, not a card.
  - Thought items render as plain text.
  - Tool items render icon + name + status + args.
  - Approval dock renders multiple requests, each with 2-column decisions.

- [ ] **Step 4: Verify GREEN**
  - Run the same frontend test command.

### Task 5: Final Verification

**Files:**
- Potentially modify docs or prototype if implementation diverges.

- [ ] **Step 1: Backend targeted verification**
  - Run: `mise exec -- uv run python -m unittest tests.test_history_api tests.test_approval_flow tests.test_stream_persistence -v`

- [ ] **Step 2: Frontend targeted verification**
  - Run: `pnpm dlx tsx --test features/chat/chat-event-reducer.test.ts features/chat/store.test.ts features/chat/components/approval-card.test.tsx features/chat/chat-ui-state.test.ts`

- [ ] **Step 3: Broader known verification bundle**
  - Run: `make test-dev-config`
  - Run in `agent_claude`: `mise exec -- uv run python -m unittest discover -s tests -p 'test_*.py' -v`
  - Run in `web`: `pnpm lint`

- [ ] **Step 4: Completion audit**
  - Confirm no approval card is injected into message timeline.
  - Confirm multiple approval requests share one dock.
  - Confirm refresh/history order is backend-projected.
  - Confirm old tests either pass or are intentionally updated for the new contract.
