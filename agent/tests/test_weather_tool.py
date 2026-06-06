import unittest

from agent_tools.get_weather import get_weather


class WeatherToolTest(unittest.TestCase):
    def test_weather_tool_is_registered_as_langchain_tool(self) -> None:
        self.assertEqual(get_weather.name, "get_weather")
        self.assertTrue(callable(get_weather.invoke))

    def test_weather_tool_returns_city_weather(self) -> None:
        result = get_weather.invoke({"city": "Shanghai"})

        self.assertEqual(result, "its will be sunny in Shanghai")


if __name__ == "__main__":
    unittest.main()
