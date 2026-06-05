import json
import os
from typing import Any
from urllib.request import Request, urlopen


DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"


def get_deepseek_balance_notice() -> str | None:
    """Return a short DeepSeek balance notice, or None when unavailable."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None

    try:
        request = Request(
            DEEPSEEK_BALANCE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="GET",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    balance_info = _primary_balance_info(payload)
    if balance_info is None:
        return None

    currency = balance_info.get("currency")
    total_balance = balance_info.get("total_balance")
    if not isinstance(currency, str) or not isinstance(total_balance, str):
        return None

    return f"当前 DeepSeek 账户余额：{currency} {total_balance}"


def _primary_balance_info(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    balance_infos = payload.get("balance_infos")
    if not isinstance(balance_infos, list):
        return None

    for item in balance_infos:
        if isinstance(item, dict) and item.get("currency") == "CNY":
            return item

    first_item = balance_infos[0] if balance_infos else None
    return first_item if isinstance(first_item, dict) else None
