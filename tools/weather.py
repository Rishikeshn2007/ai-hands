import httpx

WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class Weather:
    @staticmethod
    async def fetch_weather(city: str) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=20) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1},
            )
            geo.raise_for_status()
            geo_data = geo.json()
            if not geo_data.get("results"):
                return {"error": "City not found"}

            place = geo_data["results"][0]
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": (
                        "temperature_2m,relative_humidity_2m,"
                        "apparent_temperature,is_day,precipitation,"
                        "weather_code,wind_speed_10m"
                    ),
                },
            )
            response.raise_for_status()
            current = response.json()["current"]
            current["condition"] = WMO.get(current.get("weather_code"), "Unknown")
            return {
                "city": place["name"],
                "country": place.get("country"),
                "weather": current,
            }
