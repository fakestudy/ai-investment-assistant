from langchain.tools import tool

from provider.deepseek import get_deepseek_balance_notice


@tool
def get_deepseek_balance() -> str:
    """查询 DeepSeek 账户余额。仅当用户明确询问余额、账户余额、剩余额度或费用情况时调用。"""
    notice = get_deepseek_balance_notice()
    if notice is None:
        return "暂时无法查询 DeepSeek 账户余额。"
    return notice
