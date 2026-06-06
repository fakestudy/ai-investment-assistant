from langchain.tools import tool


@tool(name_or_callable="get_weather")
def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"its will be sunny in {city}"
