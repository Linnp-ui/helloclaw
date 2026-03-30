"""天气查询工具 - 使用 Open-Meteo API"""

import json
from typing import List, Dict, Any

import requests
from hello_agents.tools import Tool, ToolParameter, ToolResponse, tool_action


class WeatherTool(Tool):
    """天气查询工具

    使用 Open-Meteo API 查询天气信息，无需 API Key。
    """

    def __init__(self, timeout: int = 10):
        """初始化天气工具

        Args:
            timeout: 请求超时时间（秒），默认 10
        """
        super().__init__(
            name="weather", description="查询指定城市的天气信息", expandable=True
        )
        self.timeout = timeout
        self._geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        self._weather_url = "https://api.open-meteo.com/v1/forecast"

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        """执行天气查询"""
        city = parameters.get("city", "")
        return self._get_weather(city)

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="city",
                type="string",
                description="城市名称（如：北京、上海、深圳）",
                required=True,
            ),
        ]

    def _get_weather(self, city: str) -> ToolResponse:
        """查询天气

        Args:
            city: 城市名称

        Returns:
            ToolResponse: 天气信息
        """
        if not city:
            return ToolResponse.error(code="INVALID_INPUT", message="城市名称不能为空")

        try:
            # 1. 获取城市坐标
            geo_resp = requests.get(
                self._geo_url,
                params={"name": city, "count": 1, "language": "zh"},
                timeout=self.timeout,
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                return ToolResponse.error(
                    code="CITY_NOT_FOUND",
                    message=f"未找到城市: {city}",
                )

            location = geo_data["results"][0]
            lat = location["latitude"]
            lon = location["longitude"]
            city_name = location.get("name", city)
            country = location.get("country", "")

            # 2. 获取天气数据
            weather_resp = requests.get(
                self._weather_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": "true",
                    "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                    "timezone": "Asia/Shanghai",
                },
                timeout=self.timeout,
            )
            weather_resp.raise_for_status()
            weather_data = weather_resp.json()

            current = weather_data.get("current_weather", {})
            temp = current.get("temperature", "N/A")
            windspeed = current.get("windspeed", "N/A")
            weathercode = current.get("weathercode", -1)
            daily = weather_data.get("daily", {})
            temp_max = daily.get("temperature_2m_max", [None])[0]
            temp_min = daily.get("temperature_2m_min", [None])[0]

            # 天气代码映射
            weather_desc = self._weathercode_to_desc(weathercode)

            # 格式化输出
            location_str = f"{city_name}" + (f", {country}" if country else "")
            lines = [
                f"🌤 **{location_str} 天气**",
                f"当前: {weather_desc}, {temp}°C",
                f"最高: {temp_max}°C / 最低: {temp_min}°C",
                f"风速: {windspeed} km/h",
            ]

            return ToolResponse.success(
                text="\n".join(lines),
                data={
                    "city": city_name,
                    "country": country,
                    "temperature": temp,
                    "temperature_max": temp_max,
                    "temperature_min": temp_min,
                    "weather_desc": weather_desc,
                    "windspeed": windspeed,
                    "latitude": lat,
                    "longitude": lon,
                },
            )

        except requests.RequestException as e:
            return ToolResponse.error(code="NETWORK_ERROR", message=f"网络错误: {e}")
        except Exception as e:
            return ToolResponse.error(
                code="WEATHER_ERROR", message=f"天气查询失败: {e}"
            )

    def _weathercode_to_desc(self, code: int) -> str:
        """将天气代码转换为描述"""
        weather_codes = {
            0: "晴",
            1: "大部晴",
            2: "多云",
            3: "阴",
            45: "雾",
            48: "雾凇",
            51: "毛毛雨",
            53: "小雨",
            55: "中雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            80: "阵雨",
            81: "阵雨",
            82: "暴雨",
            95: "雷阵雨",
            96: "冰雹雷阵雨",
            99: "冰雹雷阵雨",
        }
        return weather_codes.get(code, "未知")

    @tool_action("get_weather", "查询指定城市的天气")
    def _get_weather_action(self, city: str) -> str:
        """查询天气

        Args:
            city: 城市名称（如：北京、上海、深圳）
        """
        response = self._get_weather(city)
        return response.text
