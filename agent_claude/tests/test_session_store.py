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
        self.lock_statements = rows.setdefault("lock_statements", [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        if "pg_advisory_xact_lock" in sql:
            self.lock_statements.append(sql)
            return _Result([])
        if "INSERT INTO agent_session_entries" in sql:
            for values in statement._multi_values[0]:
                row_values = {column.key: value for column, value in values.items()}
                if row_values["entry_uuid"] is not None and any(
                    row.project_key == row_values["project_key"]
                    and row.sdk_session_id == row_values["sdk_session_id"]
                    and row.subpath == row_values["subpath"]
                    and row.entry_uuid == row_values["entry_uuid"]
                    for row in self._rows["entries"]
                ):
                    continue
                self._rows["entries"].append(AgentSessionEntry(**row_values))
            return _Result([])
        params = statement.compile().params
        if "FROM agent_session_entries" in sql:
            project_key = params["project_key_1"]
            sdk_session_id = params["sdk_session_id_1"]
            subpath = params["subpath_1"]
            is_entry_uuid_lookup = (
                "SELECT agent_session_entries.entry_uuid" in sql
                and "agent_session_entries.entry_payload" not in sql
            )
            entries = [
                row
                for row in self._rows["entries"]
                if row.project_key == project_key
                and row.sdk_session_id == sdk_session_id
                and row.subpath == subpath
            ]
            if is_entry_uuid_lookup:
                entry_uuid_values = set(params["entry_uuid_1"])
                entries = [
                    row for row in entries if row.entry_uuid in entry_uuid_values
                ]
            entries.sort(key=lambda row: row.sequence_no)
            if "agent_session_entries.sequence_no" in sql and "DESC" in sql:
                rows = [entries[-1].sequence_no] if entries else []
                return _Result(rows)
            if is_entry_uuid_lookup:
                return _Result([row.entry_uuid for row in entries])
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
        self.rows = {"entries": [], "sessions": [], "lock_statements": []}

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

    async def test_append_takes_per_session_advisory_transaction_lock(self) -> None:
        factory = _FakeSessionFactory()
        store = PostgresSessionStore(session_factory=factory)

        await store.append(
            {"project_key": "project-a", "session_id": "session-1"},
            [{"uuid": "entry-1", "type": "user", "text": "hello"}],
        )

        self.assertEqual(len(factory.rows["lock_statements"]), 1)
        self.assertIn("pg_advisory_xact_lock", factory.rows["lock_statements"][0])

    async def test_repeated_append_with_same_entry_uuid_is_idempotent(self) -> None:
        store = PostgresSessionStore(session_factory=_FakeSessionFactory())
        key = {"project_key": "project-a", "session_id": "session-1"}
        entries = [{"uuid": "entry-1", "type": "user", "text": "hello"}]

        await store.append(key, entries)
        await store.append(key, entries)

        loaded = await store.load(key)

        self.assertEqual(loaded, entries)

    async def test_append_with_different_entry_uuids_preserves_order(self) -> None:
        store = PostgresSessionStore(session_factory=_FakeSessionFactory())
        key = {
            "project_key": "project-a",
            "session_id": "session-1",
            "subpath": "workspace-a",
        }

        await store.append(
            key,
            [{"uuid": "entry-1", "type": "user", "text": "hello"}],
        )
        await store.append(
            key,
            [{"uuid": "entry-2", "type": "assistant", "text": "world"}],
        )

        loaded = await store.load(key)

        self.assertEqual(
            loaded,
            [
                {"uuid": "entry-1", "type": "user", "text": "hello"},
                {"uuid": "entry-2", "type": "assistant", "text": "world"},
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
