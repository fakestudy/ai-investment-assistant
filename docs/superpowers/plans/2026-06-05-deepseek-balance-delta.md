# DeepSeek Balance Delta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Query the current DeepSeek account balance and append it as a final assistant `delta` before the stream `done` event.

**Architecture:** Keep DeepSeek account APIs out of `service/chat.py` by adding a focused provider module. The chat stream remains the orchestration boundary and receives an injectable balance formatter so tests do not call the network.

**Tech Stack:** Python 3, `urllib.request`, Pydantic stream contract tests, existing unittest suite.

---

### Task 1: Add Balance Delta Stream Behavior

**Files:**
- Modify: `agent/tests/test_chat_stream.py`
- Modify: `agent/service/chat.py`

- [ ] **Step 1: Write the failing test**

Add two tests to `ChatEventStreamTest`:

```python
    def test_emits_deepseek_balance_delta_before_done(self) -> None:
        request = ChatStreamRequest.model_validate(
            {
                "conversationId": "conversation-1",
                "message": "查一下余额",
            }
        )

        events = list(
            iter_chat_events(
                request,
                agent=FakeAgent([]),
                message_id_factory=lambda: "assistant-1",
                now_factory=lambda: datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                balance_notice_provider=lambda: "当前 DeepSeek 账户余额：CNY 110.00",
            )
        )

        self.assertEqual(
            events[-2],
            {
                "type": "delta",
                "messageId": "assistant-1",
                "text": "\n\n当前 DeepSeek 账户余额：CNY 110.00",
            },
        )
        self.assertEqual(events[-1], {"type": "done", "messageId": "assistant-1"})

    def test_skips_balance_delta_when_provider_returns_none(self) -> None:
        request = ChatStreamRequest.model_validate(
            {
                "conversationId": "conversation-1",
                "message": "查一下余额",
            }
        )

        events = list(
            iter_chat_events(
                request,
                agent=FakeAgent([]),
                message_id_factory=lambda: "assistant-1",
                now_factory=lambda: datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                balance_notice_provider=lambda: None,
            )
        )

        self.assertEqual([event["type"] for event in events], ["message_created", "done"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m unittest tests.test_chat_stream.ChatEventStreamTest -v`

Expected: FAIL because `iter_chat_events()` does not accept `balance_notice_provider`.

- [ ] **Step 3: Add minimal stream integration**

Update `iter_chat_events()` signature:

```python
def iter_chat_events(
    request: ChatStreamRequest,
    *,
    agent: Any | None = None,
    title_generator: Callable[[str], str] = get_conversation_title,
    balance_notice_provider: Callable[[], str | None] = get_deepseek_balance_notice,
    message_id_factory: Callable[[], str] = lambda: str(uuid4()),
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Iterator[dict[str, Any]]:
```

Before `yield {"type": "done", "messageId": assistant_id}` add:

```python
        balance_notice = balance_notice_provider()
        if balance_notice:
            yield {
                "type": "delta",
                "messageId": assistant_id,
                "text": f"\n\n{balance_notice}",
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m unittest tests.test_chat_stream.ChatEventStreamTest -v`

Expected: PASS.

### Task 2: Add DeepSeek Balance Provider

**Files:**
- Create: `agent/provider/deepseek.py`
- Modify: `agent/service/chat.py`
- Test: `agent/tests/test_deepseek_provider.py`

- [ ] **Step 1: Write provider tests**

Create `agent/tests/test_deepseek_provider.py` with tests for formatting a CNY balance and returning `None` when no API key exists.

- [ ] **Step 2: Run provider tests to verify failure**

Run: `cd agent && uv run python -m unittest tests.test_deepseek_provider -v`

Expected: FAIL because `provider.deepseek` does not exist.

- [ ] **Step 3: Implement provider**

Create a focused `provider/deepseek.py` using `urllib.request.Request` against `https://api.deepseek.com/user/balance`, reading `DEEPSEEK_API_KEY` lazily inside the function, and returning `"当前 DeepSeek 账户余额：CNY 110.00"` for the first `balance_infos` entry.

- [ ] **Step 4: Wire provider into chat**

Import `get_deepseek_balance_notice` from `provider.deepseek` in `service/chat.py`.

- [ ] **Step 5: Run all agent tests**

Run: `cd agent && uv run python -m unittest discover -s tests -v`

Expected: PASS.
