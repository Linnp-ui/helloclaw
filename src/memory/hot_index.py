"""Hot 层记忆索引管理器 - 指针化存储"""

import os
import json
from datetime import datetime
from typing import List, Optional, Dict
from pathlib import Path


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
        if self._index_cache is not None:
            return self._index_cache

        index_path = self.get_index_path()
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    self._index_cache = json.load(f)
                return self._index_cache
            except (json.JSONDecodeError, IOError):
                pass

        self._index_cache = self._build_index()
        return self._index_cache

    def save_index(self, index: Dict):
        """保存索引到文件"""
        index_path = self.get_index_path()
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        self._index_cache = index

    def _build_index(self) -> Dict:
        """构建索引（从每日记忆和话题中提取）"""
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
        if os.path.exists(self.memory_path):
            for filename in sorted(os.listdir(self.memory_path), reverse=True):
                if not filename.endswith(".md"):
                    continue
                if self._count_index_size(index) >= self.MAX_SIZE_BYTES:
                    break

                filepath = os.path.join(self.memory_path, filename)
                self._add_file_to_index(index, filepath)

        # 从话题文件构建索引
        if os.path.exists(self.topics_path):
            for filename in sorted(os.listdir(self.topics_path), reverse=True):
                if not filename.endswith(".md"):
                    continue
                if self._count_index_size(index) >= self.MAX_SIZE_BYTES:
                    break

                filepath = os.path.join(self.topics_path, filename)
                self._add_file_to_index(index, filepath)

        # 更新统计
        index["stats"]["total"] = len(index["entries"])
        for entry in index["entries"]:
            cat = entry.get("category", "fact")
            if cat in index["stats"]:
                index["stats"][cat] += 1

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
        index = self.load_index()

        # 生成精简格式：仅包含指针
        lines = ["# MEMORY.md - 长期记忆索引（指针）", "", "## 最近记忆指针", ""]

        for entry in index["entries"][:50]:  # 最多 50 条
            source = entry.get("source", "unknown")
            cat = entry.get("category", "fact")
            content = entry.get("content", "")[:60]
            lines.append(f"- [{cat}] {content}... [{source}]")

        if not index["entries"]:
            lines.append("（暂无记忆，请继续对话以积累）")

        return "\n".join(lines)

    def add_entry(self, content: str, category: str, source: str = "today"):
        """添加新记忆到索引"""
        index = self.load_index()

        # 检查重复
        content_lower = content.lower()
        for entry in index["entries"]:
            if entry.get("content", "").lower() == content_lower:
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
