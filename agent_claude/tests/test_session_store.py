import unittest

import model.conversation  # noqa: F401
from model.agent_session import AgentSession
from model.agent_session_entry import AgentSessionEntry
from repository.agent_session import (
    get_agent_session_by_conversation_id,
    upsert_agent_session,
)
from service.session_store import PostgresSessionStore


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError("expected at most one row")
        return self._rows[0]

    def scalars(self):
        return _ScalarResult(self._rows)


class _FakeAsyncSession:
    def __init__(self, rows):
        self._rows = rows
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement):
        sql = str(statement)
        params = statement.compile().params
        if "FROM agent_session_entries" in sql:
            sdk_session_id = params["sdk_session_id_1"]
            entries = [
                row
                for row in self._rows["entries"]
                if row.sdk_session_id == sdk_session_id
            ]
            entries.sort(key=lambda row: row.sequence_no)
            if "agent_session_entries.sequence_no" in sql and "DESC" in sql:
                rows = [entries[-1].sequence_no] if entries else []
                return _Result(rows)
            return _Result(entries)
        if "FROM agent_sessions" in sql:
            conversation_id = params["conversation_id_1"]
            rows = [
                row
                for row in self._rows["sessions"]
                if row.conversation_id == conversation_id
            ]
            return _Result(rows)
        raise AssertionError(f"unexpected statement: {sql}")

    def add(self, row):
        if isinstance(row, AgentSessionEntry):
            self._rows["entries"].append(row)
            return
        if isinstance(row, AgentSession):
            self._rows["sessions"].append(row)
            return
        raise AssertionError(f"unexpected row type: {type(row)!r}")

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True


class _FakeSessionFactory:
    def __init__(self):
        self.rows = {"entries": [], "sessions": []}

    def __call__(self):
        return _FakeAsyncSession(self.rows)


class SessionStoreContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_append_and_load_round_trip_preserves_sequence_order(self) -> None:
        store = PostgresSessionStore(session_factory=_FakeSessionFactory())

        await store.append(
            {"project_key": "project-a", "session_id": "session-1"},
            [{"type": "user", "text": "hello"}],
        )
        await store.append(
            {"project_key": "project-a", "session_id": "session-1"},
            [{"type": "assistant", "text": "world"}],
        )

        entries = await store.load(
            {"project_key": "project-a", "session_id": "session-1"}
        )

        self.assertEqual(
            entries,
            [
                {"type": "user", "text": "hello"},
                {"type": "assistant", "text": "world"},
            ],
        )

    async def test_upsert_agent_session_maps_conversation_to_sdk_session(self) -> None:
        session = _FakeAsyncSession({"entries": [], "sessions": []})

        created = await upsert_agent_session(
            session,
            conversation_id="conversation-1",
            sdk_session_id="sdk-session-1",
        )
        updated = await upsert_agent_session(
            session,
            conversation_id="conversation-1",
            sdk_session_id="sdk-session-2",
        )
        loaded = await get_agent_session_by_conversation_id(
            session,
            "conversation-1",
        )

        self.assertEqual(created.id, updated.id)
        self.assertEqual(loaded.sdk_session_id, "sdk-session-2")


if __name__ == "__main__":
    unittest.main()
