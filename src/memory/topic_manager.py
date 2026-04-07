"""Warm 层话题管理器 - 按需加载话题文件"""

import os
import re
import json
from datetime import datetime
from typing import List, Optional, Dict, Tuple


class TopicManager:
    """Warm 层话题管理器

    负责管理话题文件（Topic Files）：
    - 智能筛选最相关的 5 个话题
    - Frontmatter 元信息管理
    - 按需加载（仅当模型判断需要深入某个领域时）
    """

    TOPICS_DIR = "topics"
    MAX_TOPICS = 5  # 最多返回 5 个话题

    def __init__(self, workspace_path: str):
        """初始化话题管理器

        Args:
            workspace_path: 工作空间根目录
        """
        self.workspace_path = os.path.expanduser(workspace_path)
        self.topics_path = os.path.join(self.workspace_path, self.TOPICS_DIR)
        self._ensure_topics_dir()

    def _ensure_topics_dir(self):
        """确保 topics 目录存在"""
        os.makedirs(self.topics_path, exist_ok=True)

    @staticmethod
    def _extract_frontmatter(content: str) -> Tuple[Dict, str]:
        """提取 Frontmatter 元信息

        Args:
            content: 文件内容

        Returns:
            (元信息字典, 正文内容)
        """
        frontmatter = {}
        body = content

        # 匹配 --- 包裹的 YAML frontmatter
        match = re.match(r"^---\n([\s\S]*?)\n---\n([\s\S]*)$", content)
        if match:
            yaml_str = match.group(1)
            body = match.group(2)

            # 解析简单的 key: value 格式
            for line in yaml_str.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key == "tags":
                        frontmatter[key] = [t.strip() for t in value.split(",")]
                    else:
                        frontmatter[key] = value

        return frontmatter, body

    @staticmethod
    def _create_frontmatter(metadata: Dict) -> str:
        """创建 Frontmatter

        Args:
            metadata: 元信息字典

        Returns:
            Frontmatter 字符串
        """
        lines = ["---"]
        for key, value in metadata.items():
            if isinstance(value, list):
                lines.append(f"{key}: [{', '.join(value)}]")
            else:
                lines.append(f'{key}: "{value}"')
        lines.append("---")
        return "\n".join(lines)

    def create_topic(
        self,
        title: str,
        content: str,
        tags: List[str] = None,
        relevance: float = 0.5,
    ) -> str:
        """创建新话题

        Args:
            title: 话题标题
            content: 话题内容
            tags: 标签列表
            relevance: 相关度 (0-1)

        Returns:
            话题文件名
        """
        topic_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{topic_id}.md"
        filepath = os.path.join(self.topics_path, filename)

        metadata = {
            "created": datetime.now().strftime("%Y-%m-%d"),
            "title": title,
            "tags": tags or [],
            "relevance": relevance,
        }

        full_content = (
            self._create_frontmatter(metadata) + "\n\n" + f"# {title}\n\n" + content
        )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_content)

        return filename

    def update_topic(
        self,
        filename: str,
        content: str = None,
        tags: List[str] = None,
        relevance: float = None,
    ):
        """更新话题内容

        Args:
            filename: 话题文件名
            content: 新内容（可选）
            tags: 新标签（可选）
            relevance: 相关度（可选）
        """
        filepath = os.path.join(self.topics_path, filename)
        if not os.path.exists(filepath):
            return

        with open(filepath, "r", encoding="utf-8") as f:
            old_content = f.read()

        frontmatter, body = self._extract_frontmatter(old_content)

        if tags:
            frontmatter["tags"] = tags

        if relevance is not None:
            frontmatter["relevance"] = relevance

        frontmatter["updated"] = datetime.now().strftime("%Y-%m-%d")

        new_content_body = content if content is not None else body
        new_content = self._create_frontmatter(frontmatter) + "\n\n" + new_content_body

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)

    def get_topic(self, filename: str) -> Optional[Dict]:
        """获取话题内容

        Args:
            filename: 话题文件名

        Returns:
            话题信息字典，包含 frontmatter 和 content
        """
        filepath = os.path.join(self.topics_path, filename)
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        frontmatter, body = self._extract_frontmatter(content)

        return {
            "filename": filename,
            "frontmatter": frontmatter,
            "content": body.strip(),
        }

    def list_topics(self) -> List[Dict]:
        """列出所有话题

        Returns:
            话题信息列表（按相关度排序）
        """
        topics = []

        if not os.path.exists(self.topics_path):
            return topics

        for filename in os.listdir(self.topics_path):
            if not filename.endswith(".md"):
                continue

            filepath = os.path.join(self.topics_path, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            frontmatter, body = self._extract_frontmatter(content)

            topics.append(
                {
                    "filename": filename,
                    "title": frontmatter.get("title", filename[:-3]),
                    "tags": frontmatter.get("tags", []),
                    "relevance": float(frontmatter.get("relevance", 0.5)),
                    "created": frontmatter.get("created", ""),
                    "updated": frontmatter.get("updated", ""),
                    "preview": body[:100].replace("\n", " "),
                }
            )

        # 按相关度排序
        topics.sort(key=lambda x: x["relevance"], reverse=True)
        return topics

    def find_relevant_topics(
        self,
        query: str,
        max_topics: int = None,
    ) -> List[Dict]:
        """根据查询找到最相关的话题

        使用关键词匹配 + 相关度评分。

        Args:
            query: 查询关键词
            max_topics: 最大返回数量，默认 5

        Returns:
            最相关的话题列表
        """
        max_topics = max_topics or self.MAX_TOPICS

        query_lower = query.lower()
        query_keywords = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", query_lower))

        topics = self.list_topics()
        scored_topics = []

        for topic in topics:
            score = 0.0
            title = topic.get("title", "").lower()
            tags = topic.get("tags", [])
            preview = topic.get("preview", "").lower()

            # 标题匹配权重最高
            if query_lower in title:
                score += 3.0

            # 标签匹配
            for tag in tags:
                if query_lower in tag.lower():
                    score += 2.0

            # 关键词匹配
            topic_keywords = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", preview))
            if query_keywords:
                overlap = len(query_keywords & topic_keywords)
                score += overlap * 0.5

            # 加上基础相关度
            score += topic.get("relevance", 0.5)

            if score > 0:
                scored_topics.append((score, topic))

        # 按得分排序
        scored_topics.sort(key=lambda x: x[0], reverse=True)
        return [t[1] for t in scored_topics[:max_topics]]

    def merge_into_topic(
        self,
        source_type: str,
        source_name: str,
        topic_title: str,
    ) -> str:
        """将每日记忆或会话总结合并到话题

        Args:
            source_type: 来源类型 ("daily_memory" | "session_summary")
            source_name: 来源文件名
            topic_title: 目标话题标题

        Returns:
            创建的话题文件名
        """
        content = ""
        tags = []

        if source_type == "daily_memory":
            memory_path = os.path.join(self.workspace_path, "memory", source_name)
            if os.path.exists(memory_path):
                with open(memory_path, "r", encoding="utf-8") as f:
                    content = f.read()
                tags = ["daily_memory", source_name.replace(".md", "")]
        elif source_type == "session_summary":
            summary_path = os.path.join(self.workspace_path, "memory", source_name)
            if os.path.exists(summary_path):
                with open(summary_path, "r", encoding="utf-8") as f:
                    content = f.read()
                tags = [
                    "session_summary",
                    source_name.split("-")[-1].replace(".md", ""),
                ]

        return self.create_topic(
            title=topic_title,
            content=content,
            tags=tags,
            relevance=0.6,
        )

    def delete_topic(self, filename: str) -> bool:
        """删除话题

        Args:
            filename: 话题文件名

        Returns:
            是否成功删除
        """
        filepath = os.path.join(self.topics_path, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False

    def search_in_topics(self, keyword: str) -> List[Dict]:
        """在话题中搜索关键词

        Args:
            keyword: 搜索关键词

        Returns:
            匹配的话题列表
        """
        keyword_lower = keyword.lower()
        results = []

        topics = self.list_topics()
        for topic in topics:
            filepath = os.path.join(self.topics_path, topic["filename"])
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if keyword_lower in content.lower():
                # 提取匹配片段
                lines = content.split("\n")
                matches = []
                for i, line in enumerate(lines):
                    if keyword_lower in line.lower():
                        matches.append({"line": i + 1, "content": line.strip()[:100]})

                results.append(
                    {
                        "filename": topic["filename"],
                        "title": topic["title"],
                        "matches": matches[:3],  # 最多返回 3 个匹配
                    }
                )

        return results


def get_topic_manager(workspace_path: str) -> TopicManager:
    """获取话题管理器实例"""
    return TopicManager(workspace_path)
