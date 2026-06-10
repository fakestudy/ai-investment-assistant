import json
import unittest
from io import BytesIO
from typing import Any
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return BytesIO(self._body).read()


class DeepSeekBalanceTest(unittest.TestCase):
    def test_format_balance_summary_renders_structured_markdown(self) -> None:
        from service.deepseek_balance import format_balance_summary

        summary = format_balance_summary(
            {
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "110.00",
                        "granted_balance": "10.00",
                        "topped_up_balance": "100.00",
                    }
                ],
            }
        )

        self.assertIn("DeepSeek 账户余额", summary)
        self.assertIn("| CNY | 110.00 | 10.00 | 100.00 |", summary)
        self.assertIn("状态：可用于 API 调用", summary)

    def test_fetch_deepseek_balance_calls_user_balance_endpoint(self) -> None:
        from service.deepseek_balance import fetch_deepseek_balance_sync

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers.get("Authorization")
            captured["timeout"] = timeout
            return _FakeResponse(
                {
                    "is_available": True,
                    "balance_infos": [{"currency": "CNY", "total_balance": "1.00"}],
                }
            )

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "deepseek-key"}, clear=True):
            result = fetch_deepseek_balance_sync(urlopen=fake_urlopen)

        self.assertEqual(captured["url"], "https://api.deepseek.com/user/balance")
        self.assertEqual(captured["authorization"], "Bearer deepseek-key")
        self.assertEqual(captured["timeout"], 10)
        self.assertEqual(result["balance_infos"][0]["currency"], "CNY")


if __name__ == "__main__":
    unittest.main()
