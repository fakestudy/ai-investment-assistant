import unittest

from worker.main import startup_message


class WorkerEntrypointTest(unittest.TestCase):
    def test_startup_message_names_command_consumption(self) -> None:
        message = startup_message("agent worker")

        self.assertEqual(
            message,
            "agent worker started; consuming command queues.",
        )


if __name__ == "__main__":
    unittest.main()
