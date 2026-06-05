import os
import unittest
from io import BytesIO
from unittest.mock import patch

from provider.deepseek import get_deepseek_balance_notice


class FakeHTTPResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return BytesIO(self.payload).read()


class DeepSeekProviderTest(unittest.TestCase):
    def test_formats_total_balance_notice(self) -> None:
        payload = (
            b'{"is_available": true, "balance_infos": ['
            b'{"currency": "CNY", "total_balance": "110.00", '
            b'"granted_balance": "10.00", "topped_up_balance": "100.00"}]}'
        )

        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True),
            patch(
                "provider.deepseek.urlopen",
                return_value=FakeHTTPResponse(payload),
            ) as urlopen_mock,
        ):
            notice = get_deepseek_balance_notice()

        self.assertEqual(notice, "当前 DeepSeek 账户余额：CNY 110.00")
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/user/balance")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")

    def test_returns_none_when_api_key_is_missing(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("provider.deepseek.urlopen") as urlopen_mock,
        ):
            notice = get_deepseek_balance_notice()

        self.assertIsNone(notice)
        urlopen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
