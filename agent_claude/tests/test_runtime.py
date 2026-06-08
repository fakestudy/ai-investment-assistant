import os
import unittest
from unittest.mock import patch

from service.runtime import _anthropic_env


class RuntimeEnvTest(unittest.TestCase):
    def test_anthropic_env_forwards_all_anthropic_vars_and_maps_auth_token(self) -> None:
        patched_env = {
            "ANTHROPIC_AUTH_TOKEN": "settings-token",
            "ANTHROPIC_BASE_URL": "https://settings.example",
            "ANTHROPIC_MODEL": "claude-settings",
            "ANTHROPIC_CUSTOM_HEADER": "custom-value",
            "ANTHROPIC_API_KEY": "ambient-token",
            "UNRELATED": "ignored",
        }

        with patch.dict(os.environ, patched_env, clear=True):
            env = _anthropic_env()

        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "settings-token")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "settings-token")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://settings.example")
        self.assertEqual(env["ANTHROPIC_MODEL"], "claude-settings")
        self.assertEqual(env["ANTHROPIC_CUSTOM_HEADER"], "custom-value")
        self.assertNotIn("UNRELATED", env)


if __name__ == "__main__":
    unittest.main()
