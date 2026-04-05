"""Memory Flush 管理器 - 五级上下文压缩系统

Level 1: Snip - 剪裁工具调用结果
Level 2: Microcompact - 大结果外部化
Level 3: Context Collapse - 中间状态折叠
Level 4: Autocompact - 阈值触发压缩
Level 5: Reactive Compact - 错误兜底
"""

import json
import os
import re
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable

from .snip import SmartSnipManager, SNIP_PLACEHOLDER
from .microcompact import MicrocompactManager


class ContextCollapseManager:
    """Context Collapse 折叠管理器

    将对话过程中的中间片段进行折叠处理，生成摘要，只保留关键信息。
    """

    # 需要保留完整性的关键消息类型
    KEEP_FULL_ROUNDS = 3  # 最近 3 轮完整对话

    # 折叠标记
    COLLAPSED_MARKER = "[COLLAPSED]"

    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.expanduser(workspace_path)
        self.collapse_log_path = os.path.join(workspace_path, "logs", "collapse")
        os.makedirs(self.collapse_log_path, exist_ok=True)

    def collapse_history(
        self,
        messages: List[Dict],
        keep_recent: int = None,
    ) -> List[Dict]:
        """折叠历史消息

        Args:
            messages: 消息列表
            keep_recent: 保留最近 N 轮完整对话

        Returns:
            折叠后的消息列表
        """
        keep_recent = keep_recent or self.KEEP_FULL_ROUNDS * 2

        if len(messages) <= keep_recent:
            return messages

        # 保留最近的消息
        recent = messages[-keep_recent:]
        collapsed = messages[:-keep_recent]

        # 生成折叠摘要
        summary = self._generate_summary(collapsed)
        collapsed_info = {
            "role": "system",
            "content": f"{self.COLLAPSED_MARKER} {len(collapsed)} 条消息已折叠\n\n{summary}",
            "_collapsed": True,
            "_original_count": len(collapsed),
        }

        return [collapsed_info] + recent

    def _generate_summary(self, messages: List[Dict]) -> str:
        """生成折叠摘要

        Args:
            messages: 被折叠的消息

        Returns:
            摘要文本
        """
        # 统计工具调用
        tool_calls = {}
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    name = tc.get("function", {}).get("name", "unknown")
                    tool_calls[name] = tool_calls.get(name, 0) + 1

        # 统计用户消息
        user_messages = [
            m["content"][:100]
            for m in messages
            if m.get("role") == "user" and m.get("content")
        ]

        summary_parts = [f"共 {len(messages)} 条消息"]

        if tool_calls:
            tools_str = ", ".join([f"{k}({v})" for k, v in tool_calls.items()])
            summary_parts.append(f"工具调用: {tools_str}")

        if user_messages:
            summary_parts.append(f"用户话题: {'; '.join(user_messages[:3])}")

        return "\n".join(summary_parts)

    def expand_collapsed(self, messages: List[Dict]) -> List[Dict]:
        """展开折叠的消息（用于需要完整历史时）

        Args:
            messages: 消息列表

        Returns:
            展开后的消息列表（如果需要可以恢复原始消息）
        """
        # 暂时保留折叠标记，不实际恢复
        return messages


class AutocompactManager:
    """Autocompact 自动压缩管理器

    当上下文占用达到预设阈值时，触发全量摘要压缩机制。
    """

    # 五级阈值配置
    THRESHOLDS = {
        "snip": 0.50,  # 50% 触发 Snip
        "microcompact": 0.60,  # 60% 触发 Microcompact
        "collapse": 0.70,  # 70% 触发 Collapse
        "full": 0.80,  # 80% 触发全量压缩
        "emergency": 0.90,  # 90% 触发紧急压缩
    }

    def __init__(
        self,
        context_window: int = 128000,
        compression_threshold: float = 0.8,
        soft_threshold_tokens: int = 4000,
    ):
        self.context_window = context_window
        self.compression_threshold = compression_threshold
        self.soft_threshold_tokens = soft_threshold_tokens

        # 当前触发的压缩级别
        self._current_level = 0
        self._levels_triggered = set()

    def get_trigger_point(self, level: str = "full") -> int:
        """获取指定级别的触发点

        Args:
            level: 级别名称

        Returns:
            触发点的 token 数
        """
        threshold = self.THRESHOLDS.get(level, self.compression_threshold)
        return int(self.context_window * threshold - self.soft_threshold_tokens)

    def get_current_level(self, current_tokens: int) -> str:
        """获取当前应该触发的压缩级别

        Args:
            current_tokens: 当前 token 数

        Returns:
            级别名称
        """
        for level, threshold in sorted(
            self.THRESHOLDS.items(), key=lambda x: x[1], reverse=True
        ):
            if current_tokens >= self.get_trigger_point(level):
                return level
        return "normal"

    def should_trigger(self, current_tokens: int, level: str) -> bool:
        """判断是否应该触发指定级别

        Args:
            current_tokens: 当前 token 数
            level: 级别名称

        Returns:
            是否应该触发
        """
        trigger_point = self.get_trigger_point(level)
        return current_tokens >= trigger_point and level not in self._levels_triggered

    def get_levels_above(self, current_tokens: int) -> List[str]:
        """获取需要触发的所有级别

        Args:
            current_tokens: 当前 token 数

        Returns:
            级别列表（按优先级排序）
        """
        levels = []
        for level in ["snip", "microcompact", "collapse", "full", "emergency"]:
            if self.should_trigger(current_tokens, level):
                levels.append(level)
                self._levels_triggered.add(level)
        return levels

    def reset(self):
        """重置压缩状态"""
        self._current_level = 0
        self._levels_triggered.clear()

    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "current_level": self._current_level,
            "levels_triggered": list(self._levels_triggered),
            "thresholds": self.THRESHOLDS,
            "trigger_points": {k: self.get_trigger_point(k) for k in self.THRESHOLDS},
        }


class ReactiveCompactManager:
    """Reactive Compact 应急压缩管理器

    当 API 返回 413 等错误时，紧急触发最高级别压缩。
    """

    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self._emergency_mode = False

    def should_reactive(self, error: Exception) -> bool:
        """判断是否应该触发应急压缩

        Args:
            error: 异常对象

        Returns:
            是否应该触发
        """
        error_str = str(error).lower()

        # 413 表示 payload too large
        if "413" in error_str:
            return True

        # 其他可能的上下文溢出错误
        if any(kw in error_str for kw in ["too large", "context length", "max tokens"]):
            return True

        return False

    def get_emergency_prompt(self) -> str:
        """获取紧急压缩提示词

        Returns:
            提示词
        """
        return """[EMERGENCY] Context overflow detected.

The API rejected the request due to context size. You must compress the context now.

Requirements:
1. Keep only the most recent 2 conversation rounds
2. Summarize all previous context into a brief summary (max 200 words)
3. Do NOT call any tools - just respond with the compressed context
4. Start your response with [COMPRESSED]

If nothing important to preserve, respond with [COMPRESSED] [SKIP]"""

    def mark_emergency(self):
        """标记为紧急模式"""
        self._emergency_mode = True

    def is_emergency(self) -> bool:
        """检查是否在紧急模式"""
        return self._emergency_mode

    def clear_emergency(self):
        """清除紧急模式"""
        self._emergency_mode = False


class MemoryFlushManager:
    """Memory Flush 管理器 - 五级上下文压缩系统

    整合 Snip、Microcompact、Context Collapse、Autocompact 和 Reactive Compact。
    在上下文压缩前触发记忆保存提醒。
    """

    def __init__(
        self,
        context_window: int = 128000,
        compression_threshold: float = 0.8,
        soft_threshold_tokens: int = 4000,
        enabled: bool = True,
        workspace_path: str = None,
    ):
        """初始化 Memory Flush 管理器

        Args:
            context_window: 上下文窗口大小
            compression_threshold: 压缩阈值（比例）
            soft_threshold_tokens: 软阈值 token 数
            enabled: 是否启用
            workspace_path: 工作空间路径
        """
        self.context_window = context_window
        self.compression_threshold = compression_threshold
        self.soft_threshold_tokens = soft_threshold_tokens
        self.enabled = enabled

        # 初始化各层级管理器
        self._snip_manager = SmartSnipManager(
            workspace_path or "~/.helloclaw/workspace"
        )
        self._microcompact = MicrocompactManager(
            workspace_path or "~/.helloclaw/workspace"
        )
        self._collapse_manager = ContextCollapseManager(
            workspace_path or "~/.helloclaw/workspace"
        )
        self._autocompact = AutocompactManager(
            context_window, compression_threshold, soft_threshold_tokens
        )
        self._reactive = ReactiveCompactManager(
            workspace_path or "~/.helloclaw/workspace"
        )

        # 记录是否已经触发过 flush
        self._flush_triggered = False

    # ==================== Snip 集成 ====================

    def apply_snip(self, messages: List[Dict]) -> List[Dict]:
        """应用 Snip 剪裁

        Args:
            messages: 消息列表

        Returns:
            剪裁后的消息
        """
        return self._snip_manager.snip_tool_results(messages)

    # ==================== Microcompact 集成 ====================

    def apply_microcompact(self, messages: List[Dict]) -> List[Dict]:
        """应用 Microcompact

        Args:
            messages: 消息列表

        Returns:
            处理后的消息
        """
        processed = []
        for msg in messages:
            msg_copy = msg.copy()

            if msg.get("role") == "tool":
                result = msg.get("content", "")
                if result and not result.startswith("[offload:"):
                    offloaded, _ = self._microcompact.offload_result(
                        tool_name=msg.get("name", "unknown"),
                        arguments={},
                        result=result,
                    )
                    msg_copy["content"] = offloaded

            processed.append(msg_copy)

        return processed

    # ==================== Context Collapse 集成 ====================

    def apply_collapse(
        self, messages: List[Dict], keep_recent: int = None
    ) -> List[Dict]:
        """应用 Context Collapse

        Args:
            messages: 消息列表
            keep_recent: 保留最近 N 轮

        Returns:
            折叠后的消息
        """
        return self._collapse_manager.collapse_history(messages, keep_recent)

    # ==================== Autocompact 集成 ====================

    def should_trigger_flush(self, current_tokens: int) -> bool:
        """判断是否应该触发 flush

        Args:
            current_tokens: 当前 token 数

        Returns:
            是否应该触发
        """
        if not self.enabled or self._flush_triggered:
            return False

        trigger_point = (
            self.context_window * self.compression_threshold
            - self.soft_threshold_tokens
        )
        return current_tokens >= trigger_point

    def get_autocompact_levels(self, current_tokens: int) -> List[str]:
        """获取需要触发的压缩级别

        Args:
            current_tokens: 当前 token 数

        Returns:
            级别列表
        """
        return self._autocompact.get_levels_above(current_tokens)

    def apply_autocompact(
        self,
        messages: List[Dict],
        current_tokens: int,
    ) -> List[Dict]:
        """应用自动压缩

        Args:
            messages: 消息列表
            current_tokens: 当前 token 数

        Returns:
            压缩后的消息
        """
        levels = self.get_autocompact_levels(current_tokens)

        # 按顺序应用压缩
        if "snip" in levels:
            messages = self.apply_snip(messages)

        if "microcompact" in levels:
            messages = self.apply_microcompact(messages)

        if "collapse" in levels:
            messages = self.apply_collapse(messages)

        if "full" in levels or "emergency" in levels:
            messages = self._generate_full_summary(messages)

        return messages

    def _generate_full_summary(self, messages: List[Dict]) -> List[Dict]:
        """生成全量摘要

        Args:
            messages: 消息列表

        Returns:
            仅包含摘要的消息
        """
        # 提取关键信息
        user_msgs = [
            m["content"]
            for m in messages
            if m.get("role") == "user" and m.get("content")
        ]
        assistant_msgs = [
            m["content"]
            for m in messages
            if m.get("role") == "assistant" and m.get("content")
        ]

        summary = f"""[COMPRESSED] Conversation summary:
- {len(user_msgs)} user messages
- {len(assistant_msgs)} assistant messages
- Last user message: {user_msgs[-1][:100] if user_msgs else "N/A"}
"""

        return [{"role": "system", "content": summary, "_compressed": True}]

    # ==================== Reactive Compact 集成 ====================

    def handle_error(self, error: Exception) -> bool:
        """处理 API 错误

        Args:
            error: 异常对象

        Returns:
            是否成功处理
        """
        if self._reactive.should_reactive(error):
            self._reactive.mark_emergency()
            return True
        return False

    def is_emergency(self) -> bool:
        """检查是否在紧急模式"""
        return self._reactive.is_emergency()

    def get_emergency_prompt(self) -> str:
        """获取紧急提示词"""
        return self._reactive.get_emergency_prompt()

    def clear_emergency(self):
        """清除紧急模式"""
        self._reactive.clear_emergency()

    # ==================== Flush 提示词 ====================

    def get_flush_prompt(self) -> str:
        """获取 flush 提示词"""
        today = datetime.now().strftime("%Y-%m-%d")
        return f"""Pre-compaction memory flush.

The conversation context is about to be compressed. Please save any important memories now.

Guidelines:
- Use memory_add to save notable facts, decisions, or user preferences to memory/{today}.md
- Use memory_update_longterm for information that should persist across all sessions
- Focus on information that would be valuable for future conversations

If nothing important needs to be stored, reply with exactly: [SILENT]"""

    def is_silent_response(self, response: str) -> bool:
        """判断是否是静默响应"""
        return response.strip() == "[SILENT]"

    # ==================== 状态管理 ====================

    def reset(self):
        """重置 flush 状态"""
        self._flush_triggered = False
        self._autocompact.reset()
        self._reactive.clear_emergency()

    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "enabled": self.enabled,
            "context_window": self.context_window,
            "compression_threshold": self.compression_threshold,
            "soft_threshold_tokens": self.soft_threshold_tokens,
            "flush_triggered": self._flush_triggered,
            "autocompact_status": self._autocompact.get_status(),
            "emergency_mode": self.is_emergency(),
        }
