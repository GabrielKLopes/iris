import json
import urllib.parse
import urllib.request
from typing import Any

WEATHER_CODES = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado", 3: "nublado",
    45: "neblina", 48: "neblina com geada", 51: "garoa fraca", 53: "garoa", 55: "garoa forte",
    61: "chuva fraca", 63: "chuva", 65: "chuva forte", 80: "pancadas de chuva fracas",
    81: "pancadas de chuva", 82: "pancadas de chuva fortes", 95: "trovoada", 96: "trovoada com granizo",
    99: "trovoada forte com granizo",
}


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OpenMeteoWeather:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def current(self, city: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"name": city, "count": 1, "language": "pt", "format": "json"})
        places = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?{query}", self.timeout).get("results")
        if not places:
            raise ValueError(f"City not found: {city}")
        place = places[0]
        params = urllib.parse.urlencode(
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 1,
                "timezone": "auto",
            }
        )
        data = _get_json(f"https://api.open-meteo.com/v1/forecast?{params}", self.timeout)
        current, daily = data["current"], data["daily"]
        return {
            "city": f"{place['name']}, {place.get('admin1', '')}".strip(", "),
            "temperature_c": current["temperature_2m"],
            "feels_like_c": current["apparent_temperature"],
            "humidity_percent": current["relative_humidity_2m"],
            "wind_kmh": current["wind_speed_10m"],
            "conditions": WEATHER_CODES.get(current["weather_code"], "desconhecido"),
            "today_min_c": daily["temperature_2m_min"][0],
            "today_max_c": daily["temperature_2m_max"][0],
            "rain_chance_percent": daily["precipitation_probability_max"][0],
        }
