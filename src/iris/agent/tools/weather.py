import json
from typing import Any

from iris.agent.ports import Tool, WeatherService


class WeatherTool(Tool):
    name = "get_weather"
    description = (
        "Gets the current weather (temperature, feels like, humidity, wind, conditions) for a city. "
        "If the user did not say the city, use the one in <knowledge>; if unknown, ask and remember it."
    )
    input_schema = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name, e.g. 'Osasco'"}},
        "required": ["city"],
    }

    def __init__(self, service: WeatherService):
        self.service = service

    def run(self, tool_input: dict[str, Any]) -> str:
        return json.dumps(self.service.current(tool_input["city"]), ensure_ascii=False)
