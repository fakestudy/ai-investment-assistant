import unittest

from worker.main import startup_message


class WorkerEntrypointTest(unittest.TestCase):
    def test_startup_message_names_deferred_implementation(self) -> None:
        message = startup_message("agent worker")

        self.assertEqual(
            message,
            "agent worker started; command handling will be implemented in a later task.",
        )


if __name__ == "__main__":
    unittest.main()
