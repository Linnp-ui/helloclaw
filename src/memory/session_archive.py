"""Cold 层会话归档管理器 - .jsonl 格式存储 + Grep 搜索"""

import os
import json
import subprocess
import re
from datetime import datetime
from typing import List, Optional, Dict, Generator


class SessionArchiveManager:
    """Cold 层会话归档管理器

    负责：
    - 将历史会话转换为 .jsonl 格式
    - 使用 Grep 进行高效全文搜索
    - 不依赖 RAG 或向量数据库
    """

    ARCHIVE_DIR = "archive"
    SESSIONS_DIR = "sessions"

    def __init__(self, workspace_path: str):
        """初始化会话归档管理器

        Args:
            workspace_path: 工作空间根目录
        """
        self.workspace_path = os.path.expanduser(workspace_path)
        self.archive_path = os.path.join(self.workspace_path, self.ARCHIVE_DIR)
        self.sessions_path = os.path.join(self.workspace_path, self.SESSIONS_DIR)
        self._ensure_archive_dir()

    def _ensure_archive_dir(self):
        """确保归档目录存在"""
        os.makedirs(self.archive_path, exist_ok=True)

    def get_archive_file_path(self, year: str = None) -> str:
        """获取归档文件路径

        Args:
            year: 年份，默认当前年份

        Returns:
            .jsonl 文件路径
        """
        year = year or datetime.now().strftime("%Y")
        return os.path.join(self.archive_path, f"sessions_{year}.jsonl")

    def archive_session(self, session_id: str) -> Optional[str]:
        """归档指定会话

        Args:
            session_id: 会话 ID

        Returns:
            归档文件名，失败返回 None
        """
        session_file = os.path.join(self.sessions_path, f"{session_id}.json")
        if not os.path.exists(session_file):
            return None

        try:
            with open(session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)

            year = datetime.now().strftime("%Y")
            archive_file = self.get_archive_file_path(year)

            # 读取历史记录
            history = session_data.get("history", [])

            # 转换每条消息为 jsonl 记录
            records = []
            for msg in history:
                role = msg.get("role", "")
                content = msg.get("content", "")

                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    content = "\n".join(text_parts)

                if role in ("user", "assistant", "tool") and content:
                    record = {
                        "session_id": session_id,
                        "date": session_data.get("created_at", ""),
                        "role": role,
                        "content": content,
                        "tokens": len(content) // 4,  # 估算 token 数
                    }
                    records.append(record)

            # 追加到归档文件
            with open(archive_file, "a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            return archive_file

        except Exception as e:
            print(f"⚠️ 归档会话失败: {e}")
            return None

    def archive_all_sessions(self) -> Dict:
        """归档所有未归档的会话

        Returns:
            归档结果统计
        """
        archived_count = 0
        failed_count = 0

        if not os.path.exists(self.sessions_path):
            return {"archived": 0, "failed": 0}

        for filename in os.listdir(self.sessions_path):
            if not filename.endswith(".json"):
                continue

            session_id = filename[:-5]
            result = self.archive_session(session_id)
            if result:
                archived_count += 1
            else:
                failed_count += 1

        return {"archived": archived_count, "failed": failed_count}

    def grep_search(
        self,
        keyword: str,
        year: str = None,
        context_lines: int = 2,
    ) -> List[Dict]:
        """使用 Grep 搜索归档文件

        Args:
            keyword: 搜索关键词
            year: 年份筛选
            context_lines: 上下文行数

        Returns:
            搜索结果列表
        """
        results = []

        # 确定搜索的归档文件
        if year:
            archive_files = [self.get_archive_file_path(year)]
        else:
            archive_files = []
            if os.path.exists(self.archive_path):
                for f in os.listdir(self.archive_path):
                    if f.startswith("sessions_") and f.endswith(".jsonl"):
                        archive_files.append(os.path.join(self.archive_path, f))

        for archive_file in archive_files:
            if not os.path.exists(archive_file):
                continue

            # 使用 Grep 搜索
            try:
                # -n: 显示行号, -i: 忽略大小写, -C: 上下文行数
                cmd = [
                    "grep",
                    "-n",
                    "-i",
                    f"-C{context_lines}",
                    keyword,
                    archive_file,
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )

                if result.returncode == 0:
                    # 解析 Grep 输出
                    lines = result.stdout.strip().split("\n--\n")
                    for block in lines:
                        block_lines = block.strip().split("\n")
                        if not block_lines:
                            continue

                        # 解析文件名和行号
                        first_line = block_lines[0]
                        match = re.match(r"([^:]+):(\d+):(.*)", first_line)
                        if match:
                            results.append(
                                {
                                    "file": match.group(1),
                                    "line": int(match.group(2)),
                                    "content": match.group(3).strip(),
                                    "context": "\n".join(block_lines[1:]),
                                }
                            )

            except Exception as e:
                print(f"⚠️ Grep 搜索失败: {e}")
                # 后备方案：Python 逐行搜索
                results.extend(
                    self._fallback_search(archive_file, keyword, context_lines)
                )

        return results

    def _fallback_search(
        self,
        archive_file: str,
        keyword: str,
        context_lines: int,
    ) -> List[Dict]:
        """后备搜索方案（当 Grep 不可用时）"""
        results = []
        keyword_lower = keyword.lower()

        try:
            with open(archive_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                try:
                    record = json.loads(line)
                    if keyword_lower in record.get("content", "").lower():
                        results.append(
                            {
                                "file": archive_file,
                                "line": i + 1,
                                "content": record.get("content", "")[:100],
                                "session_id": record.get("session_id", ""),
                                "role": record.get("role", ""),
                            }
                        )
                except json.JSONDecodeError:
                    continue

        except Exception:
            pass

        return results

    def jsonl_search(
        self,
        keyword: str,
        year: str = None,
        role_filter: str = None,
        limit: int = 50,
    ) -> List[Dict]:
        """使用 Python JSONL 搜索（备选方案）

        Args:
            keyword: 搜索关键词
            year: 年份筛选
            role_filter: 角色筛选 (user/assistant/tool)
            limit: 返回结果上限

        Returns:
            匹配记录列表
        """
        results = []
        keyword_lower = keyword.lower()

        # 确定搜索的归档文件
        if year:
            archive_files = [self.get_archive_file_path(year)]
        else:
            archive_files = []
            if os.path.exists(self.archive_path):
                for f in os.listdir(self.archive_path):
                    if f.startswith("sessions_") and f.endswith(".jsonl"):
                        archive_files.append(os.path.join(self.archive_path, f))

        for archive_file in archive_files:
            if not os.path.exists(archive_file):
                continue

            try:
                with open(archive_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if len(results) >= limit:
                            break

                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # 角色过滤
                        if role_filter and record.get("role") != role_filter:
                            continue

                        # 关键词搜索
                        if keyword_lower in record.get("content", "").lower():
                            results.append(record)

            except Exception as e:
                print(f"⚠️ JSONL 搜索失败: {e}")

        return results

    def get_archive_stats(self) -> Dict:
        """获取归档统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "total_files": 0,
            "total_records": 0,
            "years": [],
            "by_role": {"user": 0, "assistant": 0, "tool": 0},
        }

        if not os.path.exists(self.archive_path):
            return stats

        for filename in os.listdir(self.archive_path):
            if not filename.startswith("sessions_") or not filename.endswith(".jsonl"):
                continue

            stats["total_files"] += 1

            year = filename.replace("sessions_", "").replace(".jsonl", "")
            if year not in stats["years"]:
                stats["years"].append(year)

            filepath = os.path.join(self.archive_path, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        stats["total_records"] += 1
                        role = record.get("role", "")
                        if role in stats["by_role"]:
                            stats["by_role"][role] += 1
                    except json.JSONDecodeError:
                        continue

        return stats

    def stream_search(
        self,
        keyword: str,
        year: str = None,
    ) -> Generator[Dict, None, None]:
        """流式搜索（用于处理大量数据）

        Args:
            keyword: 搜索关键词
            year: 年份筛选

        Yields:
            匹配的记录
        """
        keyword_lower = keyword.lower()

        # 确定搜索的归档文件
        if year:
            archive_files = [self.get_archive_file_path(year)]
        else:
            archive_files = []
            if os.path.exists(self.archive_path):
                for f in os.listdir(self.archive_path):
                    if f.startswith("sessions_") and f.endswith(".jsonl"):
                        archive_files.append(os.path.join(self.archive_path, f))

        for archive_file in archive_files:
            if not os.path.exists(archive_file):
                continue

            try:
                with open(archive_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                            if keyword_lower in record.get("content", "").lower():
                                yield record
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue


def get_archive_manager(workspace_path: str) -> SessionArchiveManager:
    """获取会话归档管理器实例"""
    return SessionArchiveManager(workspace_path)
