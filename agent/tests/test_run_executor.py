import asyncio
import time
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.types import Command
from sqlalchemy import delete, select

from core.database import AsyncSessionLocal, engine
from model.agent_run import AgentRun
from model.agent_run_event import AgentRunEvent
from model.approval import ApprovalBatch
from model.conversation import Conversation
from model.message import Message
from model.tool_invocation import ToolInvocation
from worker.run_executor import (
    AgentRunCommand,
    AgentRunCommandRetry,
    RunExecutor,
    claim_start_command,
    claim_resume_command,
)


class FakeAgent:
    def __init__(
        self,
        chunks: list[object],
        *,
        checkpoint_interrupts: list[str] | None = None,
    ) -> None:
        self.chunks = chunks
        self.calls: list[dict[str, object]] = []
        self.state_calls: list[dict[str, object]] = []
        self.checkpoint_interrupts = checkpoint_interrupts

    async def astream(self, input: object, **kwargs: object):
        self.calls.append({"input": input, **kwargs})
        for chunk in self.chunks:
            yield chunk

    async def aget_state(self, config: dict[str, object]) -> object:
        self.state_calls.append(config)
        interrupts = [
            SimpleNamespace(id=interrupt_id)
            for interrupt_id in (self.checkpoint_interrupts or [])
        ]
        return SimpleNamespace(interrupts=tuple(interrupts))


class ObservingAgent(FakeAgent):
    def __init__(self, chunks: list[object], events: list[str]) -> None:
        super().__init__(chunks)
        self.events = events

    async def astream(self, input: object, **kwargs: object):
        self.events.append("stream:start")
        async for chunk in super().astream(input, **kwargs):
            yield chunk


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def commit_event(self, event_type: str) -> None:
        self.calls.append(f"commit:event:{event_type}")

    async def notify(self, run_id: str) -> None:
        self.calls.append(f"notify:{run_id}")


class RunExecutorTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def test_start_uses_run_id_as_thread_id_and_both_stream_modes(self) -> None:
        asyncio.run(self._test_start_uses_run_id_as_thread_id_and_both_stream_modes())

    def test_event_is_committed_before_it_is_visible(self) -> None:
        asyncio.run(self._test_event_is_committed_before_it_is_visible())

    def test_multimode_messages_are_projected_from_mode_tuples(self) -> None:
        asyncio.run(self._test_multimode_messages_are_projected_from_mode_tuples())

    def test_title_is_projected_after_stream_when_requested(self) -> None:
        asyncio.run(self._test_title_is_projected_after_stream_when_requested())

    def test_claim_distinguishes_duplicate_ack_from_lease_retry(self) -> None:
        asyncio.run(self._test_claim_distinguishes_duplicate_ack_from_lease_retry())

    def test_start_command_carries_generate_title_from_outbox_payload(self) -> None:
        command = AgentRunCommand.from_payload(
            "command-1",
            {"runId": "run-1", "generateTitle": True},
        )

        self.assertEqual(command.id, "command-1")
        self.assertEqual(command.run_id, "run-1")
        self.assertTrue(command.generate_title)

    def test_real_multimode_stream_persists_message_mode_events_only(self) -> None:
        asyncio.run(self._test_real_multimode_stream_persists_message_mode_events_only())

    def test_real_title_projection_updates_conversation_and_event_log(self) -> None:
        asyncio.run(self._test_real_title_projection_updates_conversation_and_event_log())

    def test_completed_run_keeps_command_id_for_duplicate_ack(self) -> None:
        asyncio.run(self._test_completed_run_keeps_command_id_for_duplicate_ack())

    def test_execute_start_raises_retry_when_active_lease_blocks_claim(self) -> None:
        asyncio.run(
            self._test_execute_start_raises_retry_when_active_lease_blocks_claim()
        )

    def test_resume_uses_command_decisions_and_run_id_thread_id(self) -> None:
        asyncio.run(self._test_resume_uses_command_decisions_and_run_id_thread_id())

    def test_claim_resume_allows_resume_queued_to_resuming(self) -> None:
        asyncio.run(self._test_claim_resume_allows_resume_queued_to_resuming())

    def test_resume_consumed_checkpoint_acks_without_command(self) -> None:
        asyncio.run(self._test_resume_consumed_checkpoint_acks_without_command())

    def test_resume_duplicate_completed_ack_skips_checkpoint_lookup(self) -> None:
        asyncio.run(
            self._test_resume_duplicate_completed_ack_skips_checkpoint_lookup()
        )

    def test_resume_consumed_checkpoint_completes_run_with_stable_done_event(self) -> None:
        asyncio.run(
            self._test_resume_consumed_checkpoint_completes_run_with_stable_done_event()
        )

    def test_resume_mismatched_checkpoint_fails_run_and_emits_error(self) -> None:
        asyncio.run(
            self._test_resume_mismatched_checkpoint_fails_run_and_emits_error()
        )

    def test_title_generation_does_not_block_stream_start(self) -> None:
        asyncio.run(self._test_title_generation_does_not_block_stream_start())

    def test_title_generation_failure_does_not_fail_completed_run(self) -> None:
        asyncio.run(
            self._test_title_generation_failure_does_not_fail_completed_run()
        )

    async def _test_start_uses_run_id_as_thread_id_and_both_stream_modes(self) -> None:
        fake_agent = FakeAgent([AIMessageChunk(content="hello")])
        recorder = Recorder()
        executor = RunExecutor(
            agent=fake_agent,
            load_messages=lambda _: [{"role": "user", "content": "hello"}],
            commit_event=recorder.commit_event,
            notify_run_events=recorder.notify,
            now_factory=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        )

        await executor.execute_start(AgentRunCommand(id="cmd-1", run_id="run-1"))

        self.assertEqual(
            fake_agent.calls,
            [
                {
                    "input": {"messages": [{"role": "user", "content": "hello"}]},
                    "config": {"configurable": {"thread_id": "run-1"}},
                    "stream_mode": ["messages", "updates"],
                }
            ],
        )

    async def _test_event_is_committed_before_it_is_visible(self) -> None:
        fake_agent = FakeAgent([AIMessageChunk(content="hello")])
        recorder = Recorder()
        executor = RunExecutor(
            agent=fake_agent,
            load_messages=lambda _: [{"role": "user", "content": "hello"}],
            commit_event=recorder.commit_event,
            notify_run_events=recorder.notify,
            now_factory=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        )

        await executor.execute_start(AgentRunCommand(id="cmd-1", run_id="run-1"))

        self.assertLess(
            recorder.calls.index("commit:event:delta"),
            recorder.calls.index("notify:run-1"),
        )

    async def _test_multimode_messages_are_projected_from_mode_tuples(self) -> None:
        fake_agent = FakeAgent(
            [
                (
                    "messages",
                    (
                        AIMessageChunk(
                            content="",
                            additional_kwargs={"reasoning_content": "think"},
                        ),
                        {"langgraph_node": "model"},
                    ),
                ),
                ("messages", (AIMessageChunk(content="hello"), {"langgraph_node": "model"})),
                (
                    "messages",
                    (
                        ToolMessage(
                            content="sunny",
                            name="get_weather",
                            tool_call_id="call-weather",
                        ),
                        {"langgraph_node": "tools"},
                    ),
                ),
                ("updates", {"model": {"messages": []}}),
            ]
        )
        recorder = Recorder()
        executor = RunExecutor(
            agent=fake_agent,
            load_messages=lambda _: [{"role": "user", "content": "weather"}],
            commit_event=recorder.commit_event,
            notify_run_events=recorder.notify,
            now_factory=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        )

        await executor.execute_start(AgentRunCommand(id="cmd-1", run_id="run-1"))

        self.assertIn("commit:event:reasoning", recorder.calls)
        self.assertIn("commit:event:delta", recorder.calls)
        self.assertIn("commit:event:tool_result", recorder.calls)
        self.assertNotIn("commit:event:updates", recorder.calls)

    async def _test_title_is_projected_after_stream_when_requested(self) -> None:
        fake_agent = FakeAgent([("messages", (AIMessageChunk(content="hello"), {}))])
        recorder = Recorder()
        executor = RunExecutor(
            agent=fake_agent,
            load_messages=lambda _: [{"role": "user", "content": "hello"}],
            commit_event=recorder.commit_event,
            notify_run_events=recorder.notify,
            title_generator=lambda messages: f"title:{messages[-1]['content']}",
            now_factory=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        )

        await executor.execute_start(
            AgentRunCommand(id="cmd-1", run_id="run-1", generate_title=True)
        )

        self.assertIn("commit:event:title", recorder.calls)
        self.assertLess(
            recorder.calls.index("commit:event:delta"),
            recorder.calls.index("commit:event:title"),
        )

    async def _test_title_generation_does_not_block_stream_start(self) -> None:
        events: list[str] = []

        def slow_title_generator(_: list[dict[str, str]]) -> str:
            events.append("title:start")
            time.sleep(0.05)
            events.append("title:end")
            return "slow title"

        executor = RunExecutor(
            agent=ObservingAgent([AIMessageChunk(content="hello")], events),
            load_messages=lambda _: [{"role": "user", "content": "hello"}],
            commit_event=Recorder().commit_event,
            title_generator=slow_title_generator,
        )

        await executor.execute_start(
            AgentRunCommand(id="cmd-1", run_id="run-1", generate_title=True)
        )

        self.assertLess(events.index("stream:start"), events.index("title:end"))

    async def _test_claim_distinguishes_duplicate_ack_from_lease_retry(self) -> None:
        run_id = "run-claim-semantics"
        await self._reset_run(run_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        await self._create_run(run_id, now=now)

        async with AsyncSessionLocal() as session:
            first = await claim_start_command(
                session,
                command=AgentRunCommand(id="cmd-1", run_id=run_id),
                worker_id="worker-1",
                lease_seconds=60,
                now=now,
            )
            self.assertEqual(first.action, "execute")
            await session.commit()

        async with AsyncSessionLocal() as session:
            duplicate = await claim_start_command(
                session,
                command=AgentRunCommand(id="cmd-1", run_id=run_id),
                worker_id="worker-2",
                lease_seconds=60,
                now=now + timedelta(seconds=10),
            )
            self.assertEqual(duplicate.action, "ack")
            await session.rollback()

        async with AsyncSessionLocal() as session:
            competing = await claim_start_command(
                session,
                command=AgentRunCommand(id="cmd-2", run_id=run_id),
                worker_id="worker-2",
                lease_seconds=60,
                now=now + timedelta(seconds=10),
            )
            self.assertEqual(competing.action, "retry")
            await session.rollback()

        async with AsyncSessionLocal() as session:
            expired = await claim_start_command(
                session,
                command=AgentRunCommand(id="cmd-2", run_id=run_id),
                worker_id="worker-2",
                lease_seconds=60,
                now=now + timedelta(seconds=61),
            )
            self.assertEqual(expired.action, "execute")
            self.assertEqual(expired.run.active_command_id, "cmd-2")
            await session.rollback()

        await self._reset_run(run_id)

    async def _test_real_multimode_stream_persists_message_mode_events_only(self) -> None:
        run_id = "run-real-multimode"
        await self._reset_run(run_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        await self._create_run(run_id, now=now)
        fake_agent = FakeAgent(
            [
                (
                    "messages",
                    (
                        AIMessageChunk(
                            content="",
                            additional_kwargs={"reasoning_content": "think"},
                        ),
                        {"langgraph_node": "model"},
                    ),
                ),
                (
                    "messages",
                    (
                        AIMessageChunk(
                            content="",
                            tool_call_chunks=[
                                {
                                    "name": "get_weather",
                                    "args": '{"city":"北京"}',
                                    "id": "call-real-multimode",
                                    "index": 0,
                                    "type": "tool_call_chunk",
                                }
                            ],
                            response_metadata={"finish_reason": "tool_calls"},
                        ),
                        {"langgraph_node": "model"},
                    ),
                ),
                (
                    "messages",
                    (
                        ToolMessage(
                            content="sunny",
                            name="get_weather",
                            tool_call_id="call-real-multimode",
                        ),
                        {"langgraph_node": "tools"},
                    ),
                ),
                ("updates", {"model": {"messages": ["ignored update payload"]}}),
                ("messages", (AIMessageChunk(content="done"), {"langgraph_node": "model"})),
            ]
        )
        executor = RunExecutor(
            agent=fake_agent,
            session_factory=AsyncSessionLocal,
            worker_id="worker-real",
            now_factory=lambda: now,
        )

        await executor.execute_start(AgentRunCommand(id="cmd-real", run_id=run_id))

        async with AsyncSessionLocal() as session:
            event_rows = await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == run_id)
                .order_by(AgentRunEvent.id.asc())
            )
            events = event_rows.scalars().all()
            invocation = await session.get(ToolInvocation, "call-real-multimode")

        self.assertEqual(
            [event.event_type for event in events],
            ["reasoning", "tool_call", "tool_result", "delta", "done"],
        )
        self.assertIsNotNone(invocation)
        assert invocation is not None
        self.assertEqual(invocation.tool_name, "get_weather")
        self.assertEqual(invocation.args, {"city": "北京"})
        self.assertEqual(invocation.result, "sunny")
        await self._reset_run(run_id)

    async def _test_real_title_projection_updates_conversation_and_event_log(self) -> None:
        run_id = "run-real-title"
        await self._reset_run(run_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        await self._create_run(run_id, now=now)
        fake_agent = FakeAgent(
            [("messages", (AIMessageChunk(content="hello"), {"langgraph_node": "model"}))]
        )
        executor = RunExecutor(
            agent=fake_agent,
            session_factory=AsyncSessionLocal,
            worker_id="worker-title",
            title_generator=lambda messages: f"title:{messages[-1]['content']}",
            now_factory=lambda: now,
        )

        await executor.execute_start(
            AgentRunCommand(id="cmd-title", run_id=run_id, generate_title=True)
        )

        async with AsyncSessionLocal() as session:
            conversation = await session.get(Conversation, f"conversation-{run_id}")
            event_rows = await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == run_id)
                .order_by(AgentRunEvent.id.asc())
            )
            events = event_rows.scalars().all()

        self.assertIsNotNone(conversation)
        assert conversation is not None
        self.assertEqual(conversation.title, "title:hello")
        self.assertEqual(
            [event.event_type for event in events],
            ["delta", "title", "done"],
        )
        self.assertEqual(events[1].payload["title"], "title:hello")
        await self._reset_run(run_id)

    async def _test_title_generation_failure_does_not_fail_completed_run(self) -> None:
        run_id = "run-title-failure"
        await self._reset_run(run_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        await self._create_run(run_id, now=now)

        def failing_title_generator(_: list[dict[str, str]]) -> str:
            raise RuntimeError("title unavailable")

        executor = RunExecutor(
            agent=FakeAgent(
                [("messages", (AIMessageChunk(content="hello"), {"langgraph_node": "model"}))]
            ),
            session_factory=AsyncSessionLocal,
            worker_id="worker-title-failure",
            title_generator=failing_title_generator,
            now_factory=lambda: now,
        )

        await executor.execute_start(
            AgentRunCommand(id="cmd-title-failure", run_id=run_id, generate_title=True)
        )

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            conversation = await session.get(Conversation, f"conversation-{run_id}")
            event_rows = await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == run_id)
                .order_by(AgentRunEvent.id.asc())
            )
            events = event_rows.scalars().all()

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "completed")
        self.assertIsNone(run.error)
        self.assertIsNotNone(conversation)
        assert conversation is not None
        self.assertEqual(conversation.title, "Run executor")
        self.assertEqual([event.event_type for event in events], ["delta", "done"])
        await self._reset_run(run_id)

    async def _test_completed_run_keeps_command_id_for_duplicate_ack(self) -> None:
        run_id = "run-completed-duplicate-ack"
        await self._reset_run(run_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        await self._create_run(run_id, now=now)
        executor = RunExecutor(
            agent=FakeAgent([("messages", (AIMessageChunk(content="hello"), {}))]),
            session_factory=AsyncSessionLocal,
            worker_id="worker-duplicate",
            now_factory=lambda: now,
        )

        await executor.execute_start(AgentRunCommand(id="cmd-duplicate", run_id=run_id))

        async with AsyncSessionLocal() as session:
            duplicate = await claim_start_command(
                session,
                command=AgentRunCommand(id="cmd-duplicate", run_id=run_id),
                worker_id="worker-other",
                lease_seconds=60,
                now=now + timedelta(seconds=5),
            )
            self.assertEqual(duplicate.action, "ack")
            self.assertIsNotNone(duplicate.run)
            assert duplicate.run is not None
            self.assertEqual(duplicate.run.active_command_id, "cmd-duplicate")
            await session.rollback()

        await self._reset_run(run_id)

    async def _test_execute_start_raises_retry_when_active_lease_blocks_claim(
        self,
    ) -> None:
        run_id = "run-execute-start-retry"
        await self._reset_run(run_id)
        now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        await self._create_run(run_id, now=now)
        async with AsyncSessionLocal() as session:
            result = await claim_start_command(
                session,
                command=AgentRunCommand(id="cmd-active", run_id=run_id),
                worker_id="worker-active",
                lease_seconds=60,
                now=now,
            )
            self.assertEqual(result.action, "execute")
            await session.commit()

        agent = FakeAgent([AIMessageChunk(content="should-not-run")])
        executor = RunExecutor(
            agent=agent,
            session_factory=AsyncSessionLocal,
            worker_id="worker-retry",
            now_factory=lambda: now + timedelta(seconds=10),
        )

        with self.assertRaises(AgentRunCommandRetry):
            await executor.execute_start(AgentRunCommand(id="cmd-retry", run_id=run_id))
        self.assertEqual(agent.calls, [])

        await self._reset_run(run_id)

    async def _test_resume_uses_command_decisions_and_run_id_thread_id(self) -> None:
        fake_agent = FakeAgent(
            [AIMessageChunk(content="resumed")],
            checkpoint_interrupts=["interrupt-resume"],
        )
        recorder = Recorder()
        executor = RunExecutor(
            agent=fake_agent,
            commit_event=recorder.commit_event,
            notify_run_events=recorder.notify,
            now_factory=lambda: datetime(2026, 6, 7, 14, 0, tzinfo=UTC),
        )
        decisions = [{"type": "approve"}, {"type": "reject", "message": "no"}]

        await executor.execute_resume(
            AgentRunCommand(
                id="cmd-resume",
                run_id="run-resume",
                batch_id="batch-resume",
                interrupt_id="interrupt-resume",
                decisions=decisions,
            )
        )

        self.assertEqual(
            fake_agent.state_calls,
            [{"configurable": {"thread_id": "run-resume"}}],
        )
        self.assertEqual(len(fake_agent.calls), 1)
        call = fake_agent.calls[0]
        self.assertIsInstance(call["input"], Command)
        self.assertEqual(call["input"].resume, {"decisions": decisions})
        self.assertEqual(
            call["config"],
            {"configurable": {"thread_id": "run-resume"}},
        )
        self.assertEqual(call["stream_mode"], ["messages", "updates"])
        self.assertIn("commit:event:delta", recorder.calls)

    async def _test_resume_consumed_checkpoint_acks_without_command(self) -> None:
        fake_agent = FakeAgent([], checkpoint_interrupts=[])
        executor = RunExecutor(
            agent=fake_agent,
            commit_event=Recorder().commit_event,
            now_factory=lambda: datetime(2026, 6, 7, 14, 10, tzinfo=UTC),
        )

        await executor.execute_resume(
            AgentRunCommand(
                id="cmd-consumed",
                run_id="run-consumed",
                batch_id="batch-consumed",
                interrupt_id="interrupt-consumed",
                decisions=[{"type": "approve"}],
            )
        )

        self.assertEqual(fake_agent.state_calls, [{"configurable": {"thread_id": "run-consumed"}}])
        self.assertEqual(fake_agent.calls, [])

    async def _test_resume_duplicate_completed_ack_skips_checkpoint_lookup(
        self,
    ) -> None:
        run_id = "run-resume-duplicate-completed"
        now = datetime(2026, 6, 7, 14, 20, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=now)
        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            run.status = "completed"
            run.completed_at = now
            run.active_command_id = "cmd-resume-duplicate"
            session.add(
                ApprovalBatch(
                    id="batch-resume-duplicate-completed",
                    agent_run_id=run_id,
                    assistant_message_id=f"assistant-{run_id}",
                    interrupt_id="interrupt-duplicate-completed",
                    sequence=1,
                    status="resolved",
                    expires_at=now + timedelta(minutes=30),
                    resolution_source="manual",
                    created_at=now,
                    resolved_at=now,
                )
            )
            await session.commit()

        fake_agent = FakeAgent([], checkpoint_interrupts=["unexpected-checkpoint-read"])
        executor = RunExecutor(
            agent=fake_agent,
            session_factory=AsyncSessionLocal,
            worker_id="worker-duplicate-completed",
            now_factory=lambda: now + timedelta(seconds=5),
        )

        await executor.execute_resume(
            AgentRunCommand(
                id="cmd-resume-duplicate",
                run_id=run_id,
                batch_id="batch-resume-duplicate-completed",
                interrupt_id="interrupt-duplicate-completed",
                decisions=[{"type": "approve"}],
            )
        )

        self.assertEqual(fake_agent.state_calls, [])
        self.assertEqual(fake_agent.calls, [])
        await self._reset_run(run_id)

    async def _test_resume_consumed_checkpoint_completes_run_with_stable_done_event(
        self,
    ) -> None:
        run_id = "run-resume-consumed-db"
        now = datetime(2026, 6, 7, 14, 40, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=now)
        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            run.status = "resume_queued"
            session.add(
                ApprovalBatch(
                    id="batch-resume-consumed-db",
                    agent_run_id=run_id,
                    assistant_message_id=f"assistant-{run_id}",
                    interrupt_id="interrupt-consumed-db",
                    sequence=1,
                    status="resolved",
                    expires_at=now + timedelta(minutes=30),
                    resolution_source="manual",
                    created_at=now,
                    resolved_at=now,
                )
            )
            await session.commit()

        fake_agent = FakeAgent([], checkpoint_interrupts=[])
        executor = RunExecutor(
            agent=fake_agent,
            session_factory=AsyncSessionLocal,
            worker_id="worker-consumed-db",
            now_factory=lambda: now,
        )

        await executor.execute_resume(
            AgentRunCommand(
                id="cmd-resume-consumed-db",
                run_id=run_id,
                batch_id="batch-resume-consumed-db",
                interrupt_id="interrupt-consumed-db",
                decisions=[{"type": "approve"}],
            )
        )
        await executor.execute_resume(
            AgentRunCommand(
                id="cmd-resume-consumed-db",
                run_id=run_id,
                batch_id="batch-resume-consumed-db",
                interrupt_id="interrupt-consumed-db",
                decisions=[{"type": "approve"}],
            )
        )

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assistant = await session.get(Message, f"assistant-{run_id}")
            event_rows = await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == run_id)
                .order_by(AgentRunEvent.id.asc())
            )
            events = event_rows.scalars().all()

        self.assertEqual(fake_agent.calls, [])
        self.assertEqual(
            fake_agent.state_calls,
            [{"configurable": {"thread_id": run_id}}],
        )
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "completed")
        self.assertIsNone(run.error)
        self.assertIsNone(run.lease_owner)
        self.assertIsNone(run.lease_expires_at)
        self.assertEqual(run.active_command_id, "cmd-resume-consumed-db")
        self.assertIsNotNone(assistant)
        assert assistant is not None
        self.assertEqual(assistant.status, "done")
        self.assertEqual([event.event_type for event in events], ["done"])
        self.assertEqual(
            events[0].payload,
            {
                "type": "done",
                "runId": run_id,
                "messageId": f"assistant-{run_id}",
            },
        )

        await self._reset_run(run_id)

    async def _test_resume_mismatched_checkpoint_fails_run_and_emits_error(
        self,
    ) -> None:
        run_id = "run-resume-mismatch"
        now = datetime(2026, 6, 7, 15, 0, tzinfo=UTC)
        await self._reset_run(run_id)
        await self._create_run(run_id, now=now)

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            run.status = "resume_queued"
            session.add(
                ApprovalBatch(
                    id="batch-resume-mismatch",
                    agent_run_id=run_id,
                    assistant_message_id=f"assistant-{run_id}",
                    interrupt_id="interrupt-expected",
                    sequence=1,
                    status="resolved",
                    expires_at=now + timedelta(minutes=30),
                    resolution_source="manual",
                    created_at=now,
                    resolved_at=now,
                )
            )
            await session.commit()

        fake_agent = FakeAgent([], checkpoint_interrupts=["interrupt-actual"])
        executor = RunExecutor(
            agent=fake_agent,
            session_factory=AsyncSessionLocal,
            worker_id="worker-resume-mismatch",
            now_factory=lambda: now,
        )

        await executor.execute_resume(
            AgentRunCommand(
                id="cmd-resume-mismatch",
                run_id=run_id,
                batch_id="batch-resume-mismatch",
                interrupt_id="interrupt-expected",
                decisions=[{"type": "approve"}],
            )
        )

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            event_rows = await session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.agent_run_id == run_id)
                .order_by(AgentRunEvent.id.asc())
            )
            events = event_rows.scalars().all()

        self.assertEqual(fake_agent.calls, [])
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error, "Checkpoint interrupt mismatch")
        self.assertEqual([event.event_type for event in events], ["error"])
        self.assertEqual(events[0].payload["message"], "Checkpoint interrupt mismatch")

        await self._reset_run(run_id)

    async def _test_claim_resume_allows_resume_queued_to_resuming(self) -> None:
        run_id = "run-claim-resume"
        await self._reset_run(run_id)
        now = datetime(2026, 6, 7, 14, 30, tzinfo=UTC)
        await self._create_run(run_id, now=now)

        async with AsyncSessionLocal() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            run.status = "resume_queued"
            session.add(
                ApprovalBatch(
                    id="batch-claim-resume",
                    agent_run_id=run_id,
                    assistant_message_id=f"assistant-{run_id}",
                    interrupt_id="interrupt-claim-resume",
                    sequence=1,
                    status="resolved",
                    expires_at=now + timedelta(minutes=30),
                    resolution_source="manual",
                    created_at=now,
                    resolved_at=now,
                )
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            claim = await claim_resume_command(
                session,
                command=AgentRunCommand(
                    id="cmd-resume-claim",
                    run_id=run_id,
                    batch_id="batch-claim-resume",
                    interrupt_id="interrupt-claim-resume",
                    decisions=[{"type": "approve"}],
                ),
                worker_id="worker-resume",
                lease_seconds=60,
                now=now,
            )
            self.assertEqual(claim.action, "execute")
            self.assertIsNotNone(claim.run)
            assert claim.run is not None
            self.assertEqual(claim.run.status, "resuming")
            self.assertEqual(claim.run.active_command_id, "cmd-resume-claim")
            await session.rollback()

        await self._reset_run(run_id)

    async def _create_run(self, run_id: str, *, now: datetime) -> None:
        conversation_id = f"conversation-{run_id}"
        async with AsyncSessionLocal() as session:
            session.add(
                Conversation(
                    id=conversation_id,
                    title="Run executor",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                Message(
                    id=f"user-{run_id}",
                    conversation_id=conversation_id,
                    role="user",
                    content="hello",
                    reasoning="",
                    status="done",
                    created_at=now,
                )
            )
            session.add(
                Message(
                    id=f"assistant-{run_id}",
                    conversation_id=conversation_id,
                    role="assistant",
                    content="",
                    reasoning="",
                    status="streaming",
                    created_at=now,
                )
            )
            await session.flush()
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=conversation_id,
                    user_message_id=f"user-{run_id}",
                    assistant_message_id=f"assistant-{run_id}",
                    status="queued",
                    version=0,
                    lease_owner=None,
                    lease_expires_at=None,
                    active_command_id=None,
                    error=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )
            await session.commit()

    async def _reset_run(self, run_id: str) -> None:
        conversation_id = f"conversation-{run_id}"
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(AgentRunEvent).where(AgentRunEvent.agent_run_id == run_id)
            )
            await session.execute(delete(AgentRun).where(AgentRun.id == run_id))
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()


if __name__ == "__main__":
    unittest.main()
