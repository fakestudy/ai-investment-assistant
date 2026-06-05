import unittest
from unittest.mock import patch

from agent_tools.deepseek import get_deepseek_balance


class DeepSeekToolsTest(unittest.TestCase):
    def test_balance_tool_returns_provider_notice(self) -> None:
        with patch(
            "agent_tools.deepseek.get_deepseek_balance_notice",
            return_value="当前 DeepSeek 账户余额：CNY 110.00",
        ):
            result = get_deepseek_balance()

        self.assertEqual(result, "当前 DeepSeek 账户余额：CNY 110.00")

    def test_balance_tool_returns_safe_fallback_when_unavailable(self) -> None:
        with patch(
            "agent_tools.deepseek.get_deepseek_balance_notice",
            return_value=None,
        ):
            result = get_deepseek_balance()

        self.assertEqual(result, "暂时无法查询 DeepSeek 账户余额。")


if __name__ == "__main__":
    unittest.main()
