"""Hot 层记忆索引管理器 - 指针化存储"""

import os
import json
from datetime import datetime
from typing import List, Optional, Dict
from pathlib import Path

import logging

logger = logging.getLogger(__name__)


class HotIndexManager:
    """Hot 层记忆索引管理器

    负责管理 MEMORY.md 指针索引，实现：
    - 指针存储（引用而非内容）
    - 25KB 大小限制
    - 快速加载（常驻上下文）
    """

    MAX_SIZE_BYTES = 25 * 1024  # 25KB
    INDEX_FILE = "memory_index.json"

    def __init__(self, workspace_path: str):
        """初始化 Hot 索引管理器

        Args:
            workspace_path: 工作空间根目录
        """
        self.workspace_path = os.path.expanduser(workspace_path)
        self.memory_path = os.path.join(self.workspace_path, "memory")
        self.topics_path = os.path.join(self.workspace_path, "topics")
        self._index_cache: Optional[Dict] = None

    def get_index_path(self) -> str:
        """获取索引文件路径"""
        return os.path.join(self.workspace_path, self.INDEX_FILE)

    def load_index(self) -> Dict:
        """加载索引缓存"""
        logger.info("[HotIndex] load_index() 开始加载索引")
        if self._index_cache is not None:
            logger.info(
                f"[HotIndex] 使用缓存，条目数: {len(self._index_cache.get('entries', []))}"
            )
            return self._index_cache

        index_path = self.get_index_path()
        logger.info(f"[HotIndex] 索引文件路径: {index_path}")

        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    self._index_cache = json.load(f)
                logger.info(
                    f"[HotIndex] 从文件加载成功，条目数: {len(self._index_cache.get('entries', []))}"
                )
                return self._index_cache
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[HotIndex] 加载索引失败，将重建: {e}")

        logger.info("[HotIndex] 开始构建索引")
        self._index_cache = self._build_index()
        logger.info(
            f"[HotIndex] 索引构建完成，条目数: {len(self._index_cache.get('entries', []))}"
        )
        return self._index_cache

    def save_index(self, index: Dict):
        """保存索引到文件"""
        logger.info(
            f"[HotIndex] save_index() 保存索引，条目数: {len(index.get('entries', []))}"
        )
        index_path = self.get_index_path()
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        self._index_cache = index
        logger.info(f"[HotIndex] 索引已保存到: {index_path}")

    def _build_index(self) -> Dict:
        """构建索引（从每日记忆和话题中提取）"""
        logger.info("[HotIndex] _build_index() 开始构建索引")

        index = {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "entries": [],
            "stats": {
                "total": 0,
                "preference": 0,
                "decision": 0,
                "entity": 0,
                "fact": 0,
            },
        }

        # 从每日记忆构建索引
        memory_count = 0
        if os.path.exists(self.memory_path):
            logger.info(f"[HotIndex] 扫描每日记忆目录: {self.memory_path}")
            for filename in sorted(os.listdir(self.memory_path), reverse=True):
                if not filename.endswith(".md"):
                    continue
                if self._count_index_size(index) >= self.MAX_SIZE_BYTES:
                    logger.info(
                        f"[HotIndex] 索引达到大小限制 ({self.MAX_SIZE_BYTES} bytes)，停止添加"
                    )
                    break

                filepath = os.path.join(self.memory_path, filename)
                before_count = len(index["entries"])
                self._add_file_to_index(index, filepath)
                after_count = len(index["entries"])
                memory_count += 1
                if after_count > before_count:
                    logger.info(
                        f"[HotIndex] 从 {filename} 提取了 {after_count - before_count} 条记忆"
                    )
        else:
            logger.info(f"[HotIndex] 每日记忆目录不存在: {self.memory_path}")

        # 从话题文件构建索引
        topic_count = 0
        if os.path.exists(self.topics_path):
            logger.info(f"[HotIndex] 扫描话题目录: {self.topics_path}")
            for filename in sorted(os.listdir(self.topics_path), reverse=True):
                if not filename.endswith(".md"):
                    continue
                if self._count_index_size(index) >= self.MAX_SIZE_BYTES:
                    logger.info(
                        f"[HotIndex] 索引达到大小限制 ({self.MAX_SIZE_BYTES} bytes)，停止添加"
                    )
                    break

                filepath = os.path.join(self.topics_path, filename)
                before_count = len(index["entries"])
                self._add_file_to_index(index, filepath)
                after_count = len(index["entries"])
                topic_count += 1
                if after_count > before_count:
                    logger.info(
                        f"[HotIndex] 从话题 {filename} 提取了 {after_count - before_count} 条记忆"
                    )
        else:
            logger.info(f"[HotIndex] 话题目录不存在: {self.topics_path}")

        # 更新统计
        index["stats"]["total"] = len(index["entries"])
        for entry in index["entries"]:
            cat = entry.get("category", "fact")
            if cat in index["stats"]:
                index["stats"][cat] += 1

        logger.info(
            f"[HotIndex] 索引构建完成 - 扫描了 {memory_count} 个每日记忆文件, {topic_count} 个话题文件, 共 {len(index['entries'])} 条记录"
        )
        return index

    def _add_file_to_index(self, index: Dict, filepath: str):
        """从文件提取关键记忆条目添加到索引"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # 提取带分类标记的记忆
            import re

            # 匹配 [category] 内容
            pattern = r"- \[(preference|decision|entity|fact)\]\s*(.+?)(?=\n|$)"
            for match in re.finditer(pattern, content):
                category = match.group(1)
                memory_text = match.group(2).strip()

                # 生成指针
                entry = {
                    "id": f"mem_{len(index['entries']) + 1:04d}",
                    "category": category,
                    "content": memory_text[:100],  # 截断到 100 字符
                    "source": os.path.basename(filepath).replace(".md", ""),
                    "timestamp": datetime.now().strftime("%H:%M"),
                }
                index["entries"].append(entry)
        except Exception:
            pass

    def _count_index_size(self, index: Dict) -> int:
        """估算索引大小（字节）"""
        return len(json.dumps(index, ensure_ascii=False))

    def get_compact_index(self) -> str:
        """获取精简版索引（用于上下文）"""
        logger.info("[HotIndex] get_compact_index() 获取精简索引")
        index = self.load_index()

        entry_count = len(index["entries"])
        logger.info(f"[HotIndex] 当前索引共有 {entry_count} 条记录")

        # 生成精简格式：自然描述，避免模型复述内部标签格式
        lines = []

        for entry in index["entries"][:50]:  # 最多 50 条
            source = entry.get("source", "unknown")
            cat = entry.get("category", "fact")
            content = entry.get("content", "")[:60]
            lines.append(f"- 记忆（{cat}）: {content}。来源: {source}")

        if not index["entries"]:
            lines.append("暂无记忆")

        result = "\n".join(lines)
        logger.info(
            f"[HotIndex] 生成的精简索引长度: {len(result)} 字符，包含 {min(entry_count, 50)} 条指针"
        )
        return result

    def add_entry(self, content: str, category: str, source: str = "today"):
        """添加新记忆到索引"""
        logger.info(
            f"[HotIndex] add_entry() 添加记忆 - category: {category}, source: {source}, content: {content[:50]}..."
        )
        index = self.load_index()

        # 检查重复
        content_lower = content.lower()
        for entry in index["entries"]:
            if entry.get("content", "").lower() == content_lower:
                logger.info("[HotIndex] 记忆已存在，跳过")
                return  # 已存在，跳过

        entry = {
            "id": f"mem_{len(index['entries']) + 1:04d}",
            "category": category,
            "content": content[:100],
            "source": source,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
        index["entries"].append(entry)
        index["last_updated"] = datetime.now().isoformat()
        index["stats"]["total"] = len(index["entries"])
        if category in index["stats"]:
            index["stats"][category] += 1

        self.save_index(index)
        logger.info(
            f"[HotIndex] 记忆已添加，当前索引共有 {len(index['entries'])} 条记录"
        )

    def get_entry_by_id(self, entry_id: str) -> Optional[Dict]:
        """根据 ID 获取记忆条目"""
        index = self.load_index()
        for entry in index["entries"]:
            if entry.get("id") == entry_id:
                return entry
        return None

    def search_by_keyword(self, keyword: str) -> List[Dict]:
        """在索引中搜索关键词"""
        index = self.load_index()
        keyword_lower = keyword.lower()
        results = []

        for entry in index["entries"]:
            if keyword_lower in entry.get("content", "").lower():
                results.append(entry)

        return results

    def get_stats(self) -> Dict:
        """获取索引统计"""
        index = self.load_index()
        return {
            "total": index["stats"]["total"],
            "categories": {k: v for k, v in index["stats"].items() if k != "total"},
            "size_bytes": self._count_index_size(index),
            "last_updated": index.get("last_updated", ""),
        }

    def rebuild_index(self):
        """重建索引"""
        self._index_cache = None
        self._build_index()
        self.save_index(self.load_index())


def get_hot_index(workspace_path: str) -> HotIndexManager:
    """获取 Hot 索引管理器实例"""
    return HotIndexManager(workspace_path)
