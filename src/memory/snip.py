"""Snip 剪裁管理器 - 保留工具调用结构，去除冗余结果"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


SNIP_PLACEHOLDER = "[SNIPPED]"
SNIP_RESULT_PLACEHOLDER = "[tool_result_snip]"
MAX_RESULT_LENGTH = 500  # 超过此长度才触发 snip


@dataclass
class ToolCallRecord:
    """工具调用记录"""

    tool_name: str
    arguments: Dict[str, Any]
    result: str
    call_id: str
    timestamp: str

    def to_snipped(self) -> Dict[str, Any]:
        """转换为剪裁后的格式"""
        return {
            "tool": self.tool_name,
            "args": self.arguments,
            "call_id": self.call_id,
            "timestamp": self.timestamp,
            "result": SNIP_RESULT_PLACEHOLDER,
            "result_size": len(self.result),
        }


class SnipManager:
    """Snip 剪裁管理器

    负责将工具调用结果替换为占位符，仅保留调用结构。
    这样可以大幅减少上下文占用，同时保留逻辑痕迹。
    """

    def __init__(self, workspace_path: str):
        """初始化 Snip 管理器

        Args:
            workspace_path: 工作空间根目录
        """
        self.workspace_path = os.path.expanduser(workspace_path)
        self.snip_log_path = os.path.join(self.workspace_path, "logs", "snip")
        os.makedirs(self.snip_log_path, exist_ok=True)

        # 统计信息
        self._stats = {
            "total_snipped": 0,
            "bytes_saved": 0,
        }

    def snip_tool_results(self, messages: List[Dict]) -> List[Dict]:
        """对消息列表中的工具结果进行 snip 剪裁

        Args:
            messages: 消息列表

        Returns:
            剪裁后的消息列表
        """
        snipped_messages = []
        total_saved = 0

        for msg in messages:
            msg_copy = msg.copy()

            # 处理 assistant 消息中的 tool_calls
            if msg.get("tool_calls"):
                snipped_calls = []
                for tc in msg["tool_calls"]:
                    tc_copy = tc.copy()
                    # 保留 tool_calls 结构，但结果在后续 tool 消息中处理
                    snipped_calls.append(tc_copy)
                msg_copy["tool_calls"] = snipped_calls

            # 处理 tool 消息
            if msg.get("role") == "tool":
                result = msg.get("content", "")
                if len(result) > MAX_RESULT_LENGTH:
                    # 超过阈值，剪裁结果
                    msg_copy["content"] = SNIP_PLACEHOLDER
                    msg_copy["_snipped"] = True
                    msg_copy["_original_size"] = len(result)
                    total_saved += len(result)
                    self._stats["total_snipped"] += 1
                else:
                    # 未超过阈值，保留完整结果但可以截断
                    if len(result) > 1000:
                        msg_copy["content"] = result[:1000] + "\n...[truncated]"
                        total_saved += len(result) - 1003

            snipped_messages.append(msg_copy)

        self._stats["bytes_saved"] += total_saved
        return snipped_messages

    def snip_single_message(self, msg: Dict) -> Dict:
        """对单条消息进行 snip 处理

        Args:
            msg: 消息字典

        Returns:
            剪裁后的消息
        """
        return self.snip_tool_results([msg])[0]

    def get_stats(self) -> Dict:
        """获取 snip 统计信息

        Returns:
            统计信息字典
        """
        return {
            **self._stats,
            "snip_threshold": MAX_RESULT_LENGTH,
        }

    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            "total_snipped": 0,
            "bytes_saved": 0,
        }

    def should_snip(self, content: str) -> bool:
        """判断是否应该进行 snip

        Args:
            content: 内容

        Returns:
            是否应该 snip
        """
        return len(content) > MAX_RESULT_LENGTH


class SmartSnipManager(SnipManager):
    """智能 Snip 管理器

    在 Snip 基础上增加：
    - 按工具类型区分阈值
    - 保留关键结果片段
    - 可恢复机制
    """

    # 不同工具类型的阈值配置
    TOOL_THRESHOLDS = {
        "Read": 500,  # 读取文件通常较小
        "Grep": 1000,  # 搜索结果可能较多
        "WebFetch": 5000,  # 网页抓取可能很大
        "default": 500,
    }

    # 需要保留结果的关键工具
    PRESERVE_RESULT_TOOLS = {
        "Calculator",  # 计算结果必须保留
        "Bash",  # 命令执行结果需要查看
    }

    def __init__(self, workspace_path: str):
        super().__init__(workspace_path)
        self._offload_records: Dict[str, str] = {}

    def get_tool_threshold(self, tool_name: str) -> int:
        """获取指定工具的阈值

        Args:
            tool_name: 工具名称

        Returns:
            阈值字节数
        """
        for prefix, threshold in self.TOOL_THRESHOLDS.items():
            if tool_name.startswith(prefix):
                return threshold
        return self.TOOL_THRESHOLDS["default"]

    def should_preserve_result(self, tool_name: str) -> bool:
        """判断是否应该保留某工具的结果

        Args:
            tool_name: 工具名称

        Returns:
            是否保留
        """
        return tool_name in self.PRESERVE_RESULT_TOOLS

    def smart_snip(
        self,
        messages: List[Dict],
        preserve_tools: List[str] = None,
    ) -> List[Dict]:
        """智能剪裁

        Args:
            messages: 消息列表
            preserve_tools: 需要保留结果的工具列表

        Returns:
            剪裁后的消息列表
        """
        preserve_tools = preserve_tools or []
        snipped_messages = []
        total_saved = 0

        for msg in messages:
            msg_copy = msg.copy()

            if msg.get("role") == "tool":
                tool_name = msg.get("name", "")
                result = msg.get("content", "")

                # 检查是否应该保留
                if tool_name in preserve_tools or self.should_preserve_result(
                    tool_name
                ):
                    # 保留完整结果
                    snipped_messages.append(msg_copy)
                    continue

                threshold = self.get_tool_threshold(tool_name)
                if len(result) > threshold:
                    # 提取关键片段（前 200 字符）
                    key_fragment = result[:200] if result else ""
                    msg_copy["content"] = (
                        f"{key_fragment}\n\n[{SNIP_PLACEHOLDER} {len(result)} bytes]"
                    )
                    msg_copy["_snipped"] = True
                    msg_copy["_original_size"] = len(result)
                    total_saved += len(result) - len(msg_copy["content"])
                    self._stats["total_snipped"] += 1

            snipped_messages.append(msg_copy)

        self._stats["bytes_saved"] += total_saved
        return snipped_messages


def get_snip_manager(workspace_path: str) -> SnipManager:
    """获取 Snip 管理器实例"""
    return SmartSnipManager(workspace_path)
