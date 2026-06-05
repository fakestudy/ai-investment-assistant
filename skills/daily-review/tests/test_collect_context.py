import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "collect_context.py"
)
SPEC = importlib.util.spec_from_file_location("daily_review_collect_context", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CollectContextTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "project"
        self.codex_home = self.root / "codex-home"
        self.project.mkdir()
        self.codex_home.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.name", "Daily Review Test")
        self._git("config", "user.email", "daily-review@example.com")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _git(self, *args, env=None):
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        return subprocess.run(
            ["git", *args],
            cwd=self.project,
            env=command_env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def _write_session(self, relative_path, cwd, timestamp, messages):
        path = self.codex_home / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "timestamp": timestamp,
                "type": "session_meta",
                "payload": {"id": path.stem, "cwd": str(cwd)},
            }
        ]
        for role, text, message_timestamp in messages:
            records.append(
                {
                    "timestamp": message_timestamp,
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": role,
                        "content": [{"type": "input_text", "text": text}],
                    },
                }
            )
        path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
            + "\n",
            encoding="utf-8",
        )

    def _collect(self):
        return MODULE.collect_context(
            project_path=self.project,
            codex_home=self.codex_home,
            timezone_name="Asia/Shanghai",
            raw_date="2026-06-05",
        )

    def test_collects_only_target_project_messages_for_review_day(self):
        target_session = Path("sessions/2026/06/05/target.jsonl")
        self._write_session(
            target_session,
            self.project / "agent",
            "2026-06-05T00:59:00Z",
            [
                (
                    "user",
                    "# AGENTS.md instructions for /tmp/project",
                    "2026-06-05T01:00:00Z",
                ),
                (
                    "user",
                    "<environment_context>ignored</environment_context>",
                    "2026-06-05T01:00:01Z",
                ),
                ("user", "为什么使用 SSE？", "2026-06-05T01:01:00Z"),
                (
                    "assistant",
                    "因为服务端需要持续推送。",
                    "2026-06-05T01:02:00Z",
                ),
            ],
        )
        self._write_session(
            Path("sessions/2026/06/05/other-project.jsonl"),
            self.root / "other-project",
            "2026-06-05T02:00:00Z",
            [("user", "不应出现", "2026-06-05T02:01:00Z")],
        )
        self._write_session(
            Path("sessions/2026/06/04/previous-day.jsonl"),
            self.project,
            "2026-06-04T01:00:00Z",
            [("user", "昨天的问题", "2026-06-04T01:01:00Z")],
        )

        result = self._collect()

        self.assertEqual(len(result["conversations"]), 1)
        self.assertEqual(
            result["conversations"][0]["messages"],
            [
                {
                    "role": "user",
                    "text": "为什么使用 SSE？",
                    "timestamp": "2026-06-05T01:01:00Z",
                },
                {
                    "role": "assistant",
                    "text": "因为服务端需要持续推送。",
                    "timestamp": "2026-06-05T01:02:00Z",
                },
            ],
        )
        self.assertTrue(result["has_reviewable_evidence"])

    def test_uses_shanghai_calendar_day_across_utc_boundaries(self):
        self._write_session(
            Path("sessions/2026/06/04/timezone-boundary.jsonl"),
            self.project,
            "2026-06-04T15:59:00Z",
            [
                ("user", "上海前一天", "2026-06-04T15:59:59Z"),
                ("user", "上海当天开始", "2026-06-04T16:00:00Z"),
                ("assistant", "上海当天结束前", "2026-06-05T15:59:59Z"),
                ("assistant", "上海后一天", "2026-06-05T16:00:00Z"),
            ],
        )

        result = self._collect()

        self.assertEqual(
            result["conversations"][0]["messages"],
            [
                {
                    "role": "user",
                    "text": "上海当天开始",
                    "timestamp": "2026-06-04T16:00:00Z",
                },
                {
                    "role": "assistant",
                    "text": "上海当天结束前",
                    "timestamp": "2026-06-05T15:59:59Z",
                },
            ],
        )

    def test_collects_current_branch_commits_and_working_tree_changes(self):
        source = self.project / "stream.txt"
        source.write_text("committed content\n", encoding="utf-8")
        self._git("add", "stream.txt")
        commit_env = {
            "GIT_AUTHOR_DATE": "2026-06-05T10:00:00+08:00",
            "GIT_COMMITTER_DATE": "2026-06-05T10:00:00+08:00",
        }
        self._git("commit", "-m", "feat: add stream", env=commit_env)
        source.write_text(
            "committed content\nworking tree change\n",
            encoding="utf-8",
        )

        result = self._collect()

        self.assertEqual(len(result["git"]["commits"]), 1)
        self.assertEqual(result["git"]["commits"][0]["subject"], "feat: add stream")
        self.assertEqual(
            result["git"]["commits"][0]["commit_date"],
            "2026-06-05T10:00:00+08:00",
        )
        self.assertIn("committed content", result["git"]["commits"][0]["diff"])
        self.assertIn("working tree change", result["git"]["working_tree_diff"])
        self.assertTrue(result["evidence_counts"]["working_tree_changed"])

    def test_collects_untracked_text_file_content(self):
        untracked = self.project / "new-agent.py"
        untracked.write_text(
            "def stream_messages():\n    return 'untracked evidence'\n",
            encoding="utf-8",
        )

        result = self._collect()

        self.assertEqual(
            result["git"]["untracked_files"],
            [
                {
                    "path": "new-agent.py",
                    "content": (
                        "def stream_messages():\n"
                        "    return 'untracked evidence'\n"
                    ),
                    "truncated": False,
                }
            ],
        )
        self.assertIn("untracked evidence", result["git"]["working_tree_diff"])

    def test_skips_sensitive_untracked_files_and_symlinks(self):
        (self.project / ".env").write_text(
            "API_KEY=must-not-enter-review-context\n",
            encoding="utf-8",
        )
        outside_secret = self.root / "outside-secret.txt"
        outside_secret.write_text("outside secret\n", encoding="utf-8")
        (self.project / "secret-link.txt").symlink_to(outside_secret)

        result = self._collect()

        self.assertEqual(result["git"]["untracked_files"], [])
        self.assertNotIn("must-not-enter-review-context", result["git"]["working_tree_diff"])
        self.assertNotIn("outside secret", result["git"]["working_tree_diff"])

    def test_reuses_existing_report_or_increments_global_sequence(self):
        reviews = self.project / "daily-reviews"
        reviews.mkdir()
        (reviews / "01-2026-06-03.md").write_text(
            "# Review 1\n\n## 下一步学习 TODO\n\n- 解释 TCP 重传。\n",
            encoding="utf-8",
        )
        (reviews / "02-2026-06-04.md").write_text(
            "# Review 2\n\n## 下一步学习 TODO\n\n- 解释 SSE 断线续传。\n",
            encoding="utf-8",
        )

        first_result = self._collect()

        self.assertEqual(
            first_result["report"]["current_path"],
            str(reviews.resolve() / "03-2026-06-05.md"),
        )
        self.assertFalse(first_result["report"]["current_exists"])
        self.assertEqual(
            first_result["report"]["previous_path"],
            str(reviews.resolve() / "02-2026-06-04.md"),
        )
        self.assertIn(
            "解释 SSE 断线续传",
            first_result["report"]["previous_content"],
        )

        (reviews / "03-2026-06-05.md").write_text(
            "# Existing review\n",
            encoding="utf-8",
        )
        second_result = self._collect()

        self.assertEqual(
            second_result["report"]["current_path"],
            str(reviews.resolve() / "03-2026-06-05.md"),
        )
        self.assertTrue(second_result["report"]["current_exists"])

    def test_reports_no_reviewable_evidence(self):
        result = self._collect()

        self.assertFalse(result["has_reviewable_evidence"])
        self.assertEqual(
            result["evidence_counts"],
            {
                "conversations": 0,
                "commits": 0,
                "working_tree_changed": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
