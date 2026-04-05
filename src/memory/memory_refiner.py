"""记忆精炼器 - 用小模型处理原始记忆后再返回给主模型"""

import os
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# 默认使用最便宜的模型
DEFAULT_REFINE_MODEL = "glm-4.7-flash"
DEFAULT_REFINE_PROMPT = """你是一个记忆整理助手。请从以下原始记忆碎片中提取关键信息，用自然语言总结。

要求：
1. 只保留与用户问题相关的核心信息
2. 用口语化的方式表达（如"用户喜欢..."、"用户曾经..."）
3. 不要包含文件名、行号、标签等内部格式
4. 如果没有有用信息，返回"无相关信息"

原始记忆：
{memory_content}

精简后的记忆（仅供内部参考，禁止输出给用户）："""


class MemoryRefiner:
    """记忆精炼器

    在检索和回答之间增加一个处理层：
    1. 接收原始记忆搜索结果
    2. 用小模型提取关键信息
    3. 返回处理后的精简内容给主模型
    """

    def __init__(
        self,
        model_id: str = None,
        api_key: str = None,
        base_url: str = None,
        prompt: str = None,
    ):
        """初始化记忆精炼器

        Args:
            model_id: 精炼用的模型 ID，默认 gpt-4o-mini
            api_key: API Key，默认从环境变量读取
            base_url: API Base URL，默认从环境变量读取
            prompt: 自定义提示词模板
        """
        self.model_id = model_id or os.getenv(
            "MEMORY_REFINE_MODEL", DEFAULT_REFINE_MODEL
        )
        self.api_key = (
            api_key or os.getenv("LLM_API_KEY") or os.getenv("MEMORY_REFINE_API_KEY")
        )
        self.base_url = (
            base_url or os.getenv("LLM_BASE_URL") or os.getenv("MEMORY_REFINE_BASE_URL")
        )
        self.prompt = prompt or DEFAULT_REFINE_PROMPT

    def refine(self, raw_memory: str) -> str:
        """同步精炼记忆

        Args:
            raw_memory: 原始记忆内容

        Returns:
            精炼后的记忆内容
        """
        if not raw_memory or len(raw_memory.strip()) < 10:
            return "无相关信息"

        try:
            import json
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url)

            prompt = self.prompt.replace("{memory_content}", raw_memory)

            response = client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
            )

            result = response.choices[0].message.content.strip()
            logger.info(
                f"[MemoryRefiner] 精炼完成，输入 {len(raw_memory)} 字符 -> 输出 {len(result)} 字符"
            )
            return result

        except Exception as e:
            logger.error(f"[MemoryRefiner] 精炼失败: {e}")
            return raw_memory  # 失败时返回原始内容

    async def arefine(self, raw_memory: str) -> str:
        """异步精炼记忆

        Args:
            raw_memory: 原始记忆内容

        Returns:
            精炼后的记忆内容
        """
        if not raw_memory or len(raw_memory.strip()) < 10:
            return "无相关信息"

        try:
            import json
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

            prompt = self.prompt.replace("{memory_content}", raw_memory)

            response = await client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
            )

            result = response.choices[0].message.content.strip()
            logger.info(
                f"[MemoryRefiner] 精炼完成，输入 {len(raw_memory)} 字符 -> 输出 {len(result)} 字符"
            )
            return result

        except Exception as e:
            logger.error(f"[MemoryRefiner] 精炼失败: {e}")
            return raw_memory  # 失败时返回原始内容


# 全局实例（延迟初始化）
_refiner: Optional[MemoryRefiner] = None


def get_memory_refiner() -> MemoryRefiner:
    """获取记忆精炼器实例"""
    global _refiner
    if _refiner is None:
        _refiner = MemoryRefiner()
    return _refiner
