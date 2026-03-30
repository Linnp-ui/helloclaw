"""网页搜索工具 - 使用 DuckDuckGo 进行网络搜索"""

from typing import List, Dict, Any

from hello_agents.tools import Tool, ToolParameter, ToolResponse, tool_action


class WebSearchTool(Tool):
    """网页搜索工具

    使用 DuckDuckGo 进行网络搜索，无需 API Key。
    """

    def __init__(
        self,
        max_results: int = 5,
        timeout: int = 10,
    ):
        """初始化网页搜索工具

        Args:
            max_results: 最大返回结果数，默认 5
            timeout: 请求超时时间（秒），默认 10
        """
        super().__init__(
            name="web_search", description="使用搜索引擎搜索网络信息", expandable=True
        )

        self.max_results = max_results
        self.timeout = timeout

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        """执行搜索（默认行为）"""
        query = parameters.get("query", "")
        count = parameters.get("count", self.max_results)
        return self._search(query, count)

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query", type="string", description="搜索查询词", required=True
            ),
            ToolParameter(
                name="count",
                type="integer",
                description=f"返回结果数量，默认 {self.max_results}",
                required=False,
            ),
        ]

    def _search(self, query: str, count: int = None) -> ToolResponse:
        """执行搜索的核心实现

        Args:
            query: 搜索查询
            count: 返回结果数量

        Returns:
            ToolResponse: 搜索结果
        """
        if not query:
            return ToolResponse.error(code="INVALID_INPUT", message="搜索查询不能为空")

        try:
            from duckduckgo_search import DDGS

            ddgs = DDGS(timeout=self.timeout)
            results = list(ddgs.text(query, max_results=count or self.max_results))

            if not results:
                return ToolResponse.success(
                    text=f"未找到与 '{query}' 相关的结果",
                    data={"query": query, "results": []},
                )

            parsed = self._parse_search_results(results)
            formatted = self._format_results(parsed)

            return ToolResponse.success(
                text=formatted,
                data={
                    "query": query,
                    "results": parsed,
                    "count": len(parsed),
                },
            )

        except Exception as e:
            return ToolResponse.error(
                code="SEARCH_ERROR", message=f"搜索失败: {str(e)}"
            )

    def _parse_search_results(self, data: List[dict]) -> List[dict]:
        """解析 DuckDuckGo 搜索结果

        Args:
            data: 搜索结果数据

        Returns:
            搜索结果列表
        """
        results = []
        for item in data:
            result = {
                "title": item.get("title", ""),
                "url": item.get("href", ""),
                "description": item.get("body", ""),
            }
            results.append(result)
        return results

    def _format_results(self, results: List[dict]) -> str:
        """格式化搜索结果

        Args:
            results: 搜索结果列表

        Returns:
            格式化的文本
        """
        lines = [f"找到 {len(results)} 个结果:\n"]

        for i, result in enumerate(results, 1):
            lines.append(f"{i}. **{result['title']}**")
            lines.append(f"   URL: {result['url']}")
            if result["description"]:
                lines.append(f"   {result['description'][:200]}")
            lines.append("")

        return "\n".join(lines)

    @tool_action("search_web", "搜索网络信息")
    def _search_action(self, query: str, count: int = None) -> str:
        """搜索网络

        Args:
            query: 搜索查询词
            count: 返回结果数量（可选）
        """
        response = self._search(query, count)
        return response.text
