# Python Agent FE Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert LangChain agent output into the frontend chat SSE contract and generate a title for new conversations.

**Architecture:** Keep LangChain objects inside the Python service boundary. A dedicated event converter merges tool-call chunks, correlates tool results by call ID, and emits plain dictionaries matching `ChatStreamEvent`. The controller only formats those events as SSE.

**Tech Stack:** Python 3.12, FastAPI, LangChain, Pydantic, unittest, TypeScript.

---

### Task 1: Lock the stream contract with tests

**Files:**
- Modify: `agent/tests/test_chat_stream.py`
- Modify: `agent/schema/chat.py`

- [ ] Add a request-schema test for `conversationId`, `message`, and `generateTitle`.
- [ ] Add a fake LangChain stream containing reasoning, fragmented tool arguments, a `ToolMessage`, and final text.
- [ ] Assert the FE event order and stable tool-call ID.
- [ ] Run `PATH="$HOME/.local/bin:$PATH" uv run python -m unittest tests/test_chat_stream.py` and verify the new tests fail.

### Task 2: Implement event conversion and title generation

**Files:**
- Modify: `agent/service/chat.py`
- Modify: `agent/controller/chat.py`

- [ ] Add typed event generation with stable assistant IDs and timestamps.
- [ ] Merge `AIMessageChunk.tool_call_chunks` before emitting `tool_call`.
- [ ] Convert `ToolMessage` to `tool_result`, including latency and error status.
- [ ] Convert reasoning and content chunks to `reasoning` and `delta`.
- [ ] Complete `get_conversation_title()` with normalization and a 60-character fallback.
- [ ] Run the Python tests and verify they pass.

### Task 3: Request titles only for new conversations

**Files:**
- Modify: `web/features/chat/types.ts`
- Modify: `web/features/chat/store.ts`

- [ ] Add optional `generateTitle` to `StreamChatRequest`.
- [ ] Set it only when the selected conversation title is `New chat`.
- [ ] Run the frontend type/lint checks available in the repository.

### Task 4: Verify the complete change

**Files:**
- Test: `agent/tests/test_chat_stream.py`

- [ ] Run the complete Python unit test suite.
- [ ] Run the relevant frontend checks.
- [ ] Inspect the final diff for unrelated changes.

