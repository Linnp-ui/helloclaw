"""Microcompact 微压缩管理器 - 大体积数据的外部化"""

import hashlib
import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class OffloadRecord:
    """卸载记录"""

    cache_key: str
    tool_name: str
    original_size: int
    cached_at: str
    filename: str


class MicrocompactManager:
    """Microcompact 微压缩管理器

    将大体积工具执行结果卸载到外部缓存（磁盘），而非直接丢弃。
    这样可以：
    1. 大幅减少上下文 token 占用
    2. 保留恢复能力（按需加载）
    3. 不丢失有价值的执行结果
    """

    CACHE_DIR = "cache"
    MAX_CACHE_SIZE = 100 * 1024 * 1024  # 100MB 缓存上限
    DEFAULT_THRESHOLD = 10 * 1024  # 默认 10KB 触发卸载

    def __init__(
        self,
        workspace_path: str,
        threshold: int = None,
        max_cache_size: int = None,
    ):
        """初始化 Microcompact 管理器

        Args:
            workspace_path: 工作空间根目录
            threshold: 触发卸载的阈值（字节），默认 10KB
            max_cache_size: 缓存目录最大尺寸，默认 100MB
        """
        self.workspace_path = os.path.expanduser(workspace_path)
        self.cache_path = os.path.join(self.workspace_path, self.CACHE_DIR)
        self.threshold = threshold or self.DEFAULT_THRESHOLD
        self.max_cache_size = max_cache_size or self.MAX_CACHE_SIZE

        os.makedirs(self.cache_path, exist_ok=True)

        # 加载索引
        self._index: Dict[str, OffloadRecord] = {}
        self._load_index()

    def _get_cache_key(self, content: str) -> str:
        """生成缓存键

        Args:
            content: 内容

        Returns:
            缓存键（内容的 MD5 哈希前 12 位）
        """
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _get_cache_file_path(self, cache_key: str) -> str:
        """获取缓存文件路径

        Args:
            cache_key: 缓存键

        Returns:
            缓存文件完整路径
        """
        return os.path.join(self.cache_path, f"{cache_key}.json")

    def _load_index(self):
        """加载缓存索引"""
        index_file = os.path.join(self.cache_path, "index.json")
        if os.path.exists(index_file):
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, record in data.items():
                        self._index[key] = OffloadRecord(**record)
            except Exception:
                pass

    def _save_index(self):
        """保存缓存索引"""
        index_file = os.path.join(self.cache_path, "index.json")
        data = {k: vars(v) for k, v in self._index.items()}
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def offload_result(
        self,
        tool_name: str,
        arguments: Dict,
        result: str,
    ) -> Tuple[str, str]:
        """卸载大结果到外部缓存

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            result: 执行结果

        Returns:
            (缓存引用, 缓存键)
            缓存引用格式: [offload:{cache_key}]
        """
        # 检查是否需要卸载
        if len(result) < self.threshold:
            return result, ""

        # 生成缓存键
        cache_key = self._get_cache_key(result)

        # 如果已存在，直接返回引用
        if cache_key in self._index:
            return f"[offload:{cache_key}]", cache_key

        # 创建缓存记录
        record = OffloadRecord(
            cache_key=cache_key,
            tool_name=tool_name,
            original_size=len(result),
            cached_at=datetime.now().isoformat(),
            filename=f"{cache_key}.json",
        )

        # 保存到缓存文件
        cache_data = {
            "tool": tool_name,
            "args": arguments,
            "result": result,
            "cached_at": record.cached_at,
            "original_size": record.original_size,
        }

        cache_file = self._get_cache_file_path(cache_key)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False)

        self._index[cache_key] = record
        self._save_index()

        # 检查缓存大小，必要时清理
        self._cleanup_if_needed()

        return f"[offload:{cache_key}]", cache_key

    def load_result(self, cache_ref: str) -> Optional[str]:
        """按需加载缓存结果

        Args:
            cache_ref: 缓存引用，格式: [offload:{cache_key}]

        Returns:
            原始结果，如果加载失败返回 None
        """
        # 解析缓存引用
        if not cache_ref.startswith("[offload:") or not cache_ref.endswith("]"):
            return None

        cache_key = cache_ref[9:-1]
        return self.load_result_by_key(cache_key)

    def load_result_by_key(self, cache_key: str) -> Optional[str]:
        """通过缓存键加载结果

        Args:
            cache_key: 缓存键

        Returns:
            原始结果
        """
        cache_file = self._get_cache_file_path(cache_key)
        if not os.path.exists(cache_file):
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("result", "")
        except Exception:
            return None

    def _cleanup_if_needed(self):
        """必要时清理旧缓存"""
        # 计算当前缓存大小
        total_size = sum(
            os.path.getsize(os.path.join(self.cache_path, f))
            for f in os.listdir(self.cache_path)
            if f.endswith(".json") and f != "index.json"
        )

        if total_size <= self.max_cache_size:
            return

        # 按时间排序，删除最旧的
        records = sorted(
            self._index.items(),
            key=lambda x: x[1].cached_at,
        )

        # 删除 20% 的最旧缓存
        remove_count = len(records) // 5
        for key, record in records[:remove_count]:
            cache_file = self._get_cache_file_path(key)
            if os.path.exists(cache_file):
                os.remove(cache_file)
            del self._index[key]

        self._save_index()

    def get_stats(self) -> Dict:
        """获取缓存统计信息

        Returns:
            统计信息字典
        """
        total_size = sum(
            os.path.getsize(os.path.join(self.cache_path, f))
            for f in os.listdir(self.cache_path)
            if f.endswith(".json") and f != "index.json"
        )

        return {
            "cached_count": len(self._index),
            "total_size": total_size,
            "threshold": self.threshold,
            "max_size": self.max_cache_size,
        }

    def search_in_cache(self, keyword: str) -> List[Dict]:
        """在缓存中搜索关键词

        Args:
            keyword: 搜索关键词

        Returns:
            匹配的缓存记录列表
        """
        results = []
        keyword_lower = keyword.lower()

        for cache_key, record in self._index.items():
            result = self.load_result_by_key(cache_key)
            if result and keyword_lower in result.lower():
                results.append(
                    {
                        "cache_key": cache_key,
                        "tool": record.tool_name,
                        "cached_at": record.cached_at,
                        "original_size": record.original_size,
                        "match_preview": result[:200],
                    }
                )

        return results

    def clear_cache(self, days: int = 30) -> int:
        """清理旧缓存

        Args:
            days: 保留天数

        Returns:
            删除的缓存数量
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)
        to_remove = []

        for cache_key, record in self._index.items():
            cached_at = datetime.fromisoformat(record.cached_at)
            if cached_at < cutoff:
                to_remove.append(cache_key)

        for key in to_remove:
            cache_file = self._get_cache_file_path(key)
            if os.path.exists(cache_file):
                os.remove(cache_file)
            del self._index[key]

        if to_remove:
            self._save_index()

        return len(to_remove)


class MicrocompactMiddleware:
    """Microcompact 中间件

    作为一个中间件层，可以在 Agent 执行工具后自动处理结果卸载。
    """

    def __init__(self, workspace_path: str):
        self._manager = MicrocompactManager(workspace_path)

    def process_tool_result(
        self,
        tool_name: str,
        arguments: Dict,
        result: str,
    ) -> str:
        """处理工具执行结果

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            result: 执行结果

        Returns:
            处理后的结果（可能包含缓存引用）
        """
        return self._manager.offload_result(tool_name, arguments, result)[0]

    def restore_if_needed(self, content: str) -> str:
        """如果内容是缓存引用，则恢复原始结果

        Args:
            content: 内容

        Returns:
            恢复后的内容
        """
        if content.startswith("[offload:") and content.endswith("]"):
            restored = self._manager.load_result(content)
            if restored:
                return restored
        return content


def get_microcompact_manager(workspace_path: str) -> MicrocompactManager:
    """获取 Microcompact 管理器实例"""
    return MicrocompactManager(workspace_path)


def get_microcompact_middleware(workspace_path: str) -> MicrocompactMiddleware:
    """获取 Microcompact 中间件实例"""
    return MicrocompactMiddleware(workspace_path)
