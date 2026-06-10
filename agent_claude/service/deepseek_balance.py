from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen as default_urlopen


DEFAULT_DEEPSEEK_API_BASE_URL = "https://api.deepseek.com"


class DeepSeekBalanceError(RuntimeError):
    pass


def fetch_deepseek_balance_sync(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 10,
    urlopen: Callable[..., Any] = default_urlopen,
) -> dict[str, Any]:
    token = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY")
    if not token:
        raise DeepSeekBalanceError("DEEPSEEK_API_KEY is not configured")

    endpoint = f"{(base_url or DEFAULT_DEEPSEEK_API_BASE_URL).rstrip('/')}/user/balance"
    request = Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise DeepSeekBalanceError(
            f"DeepSeek balance API returned HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise DeepSeekBalanceError("DeepSeek balance API request failed") from exc
    except json.JSONDecodeError as exc:
        raise DeepSeekBalanceError("DeepSeek balance API returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise DeepSeekBalanceError("DeepSeek balance API returned unexpected payload")
    return payload


async def fetch_deepseek_balance() -> dict[str, Any]:
    return await asyncio.to_thread(fetch_deepseek_balance_sync)


def format_balance_summary(payload: dict[str, Any]) -> str:
    rows = []
    balance_infos = payload.get("balance_infos")
    if isinstance(balance_infos, list):
        for item in balance_infos:
            if not isinstance(item, dict):
                continue
            rows.append(
                "| {currency} | {total} | {granted} | {topped_up} |".format(
                    currency=_string_field(item, "currency"),
                    total=_string_field(item, "total_balance"),
                    granted=_string_field(item, "granted_balance"),
                    topped_up=_string_field(item, "topped_up_balance"),
                )
            )

    status = (
        "可用于 API 调用"
        if payload.get("is_available") is True
        else "不可用于 API 调用"
    )
    table = (
        "\n".join(
            [
                "| 币种 | 总余额 | 赠金余额 | 充值余额 |",
                "|---|---:|---:|---:|",
                *rows,
            ]
        )
        if rows
        else "暂无余额明细"
    )

    return f"DeepSeek 账户余额\n\n{table}\n\n状态：{status}"


def safe_balance_error_message(error: Exception) -> str:
    if isinstance(error, DeepSeekBalanceError):
        return str(error)
    return "DeepSeek balance command failed"


def _string_field(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if value is None:
        return "-"
    return str(value)
