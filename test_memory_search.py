"""记忆搜索与精炼测试"""

import pytest
import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

from src.workspace.manager import WorkspaceManager
from src.tools.builtin.memory import MemoryTool
from src.memory.memory_refiner import MemoryRefiner


class TestMemorySearchRefine:
    """测试 memory_search 的精炼逻辑"""

    @pytest.fixture
    def temp_workspace(self):
        """创建临时工作空间"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 memory 目录
            memory_dir = os.path.join(tmpdir, "memory")
            os.makedirs(memory_dir, exist_ok=True)
            yield tmpdir

    @pytest.fixture
    def workspace_manager(self, temp_workspace):
        """创建工作空间管理器"""
        return WorkspaceManager(temp_workspace)

    @pytest.fixture
    def memory_tool(self, workspace_manager):
        """创建记忆工具"""
        return MemoryTool(workspace_manager)

    def test_add_daily_memory(self, workspace_manager):
        """测试添加每日记忆"""
        content = "- [preference] 用户喜欢周杰伦"
        workspace_manager.append_to_daily_memory(content)

        # 验证文件已创建
        today = datetime.now().strftime("%Y-%m-%d.md")
        memory_path = os.path.join(workspace_manager.memory_path, today)
        assert os.path.exists(memory_path)

    def test_search_memory_returns_raw_results(self, workspace_manager):
        """测试搜索返回原始结果（带行号）"""
        workspace_manager.append_to_daily_memory("- [preference] 用户喜欢周杰伦")

        results = workspace_manager.search_memory_enhanced("周杰伦", context_lines=2)

        assert len(results) > 0
        assert "source" in results[0]
        assert "matches" in results[0]
        assert any("用户喜欢周杰伦" in m["content"] for m in results[0]["matches"])

    @patch("openai.OpenAI")
    def test_refiner_produces_natural_language(self, mock_openai_class, temp_workspace):
        """测试精炼器产生自然语言而非内部格式"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="用户喜欢周杰伦的歌"))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        os.environ["LLM_API_KEY"] = "test-key"
        os.environ["LLM_BASE_URL"] = "http://test"

        refiner = MemoryRefiner()
        raw = """**memory/2026-04-05.md** (行 3):
- [preference] 用户喜欢周杰伦

**memory/2026-04-04.md** (行 5):
- 用户最近在听周杰伦"""

        result = refiner.refine(raw)

        assert "行" not in result
        assert ".md" not in result
        assert "**" not in result
        assert "用户喜欢周杰伦" in result

    def test_memory_search_includes_refined_field(self, memory_tool, workspace_manager):
        """测试 memory_search 返回包含 refined 字段的结果"""
        workspace_manager.append_to_daily_memory("- [preference] 用户喜欢周杰伦")

        # Mock 精炼过程，直接返回自然语言
        with patch.object(
            memory_tool._refiner, "arefine", new_callable=AsyncMock
        ) as mock_refine:
            mock_refine.return_value = "用户喜欢周杰伦的歌"

            response = memory_tool._search_memory("周杰伦")

            assert response.data is not None
            assert "refined" in response.data
            assert response.data["refined"] == "用户喜欢周杰伦的歌"

    def test_refiner_removes_internal_format(self):
        """测试精炼提示词要求移除内部格式"""
        from src.memory.memory_refiner import DEFAULT_REFINE_PROMPT

        assert "不要包含文件名、行号、标签等内部格式" in DEFAULT_REFINE_PROMPT
        assert "口语化" in DEFAULT_REFINE_PROMPT


class TestMemoryRefiner:
    """测试记忆精炼器"""

    def test_refiner_empty_input(self):
        """测试空输入返回无相关信息"""
        refiner = MemoryRefiner()

        result = refiner.refine("")
        assert result == "无相关信息"

        result = refiner.refine("   ")
        assert result == "无相关信息"

    def test_refiner_short_input(self):
        """测试过短输入返回无相关信息"""
        refiner = MemoryRefiner()

        result = refiner.refine("abc")
        assert result == "无相关信息"

    @patch("openai.OpenAI")
    def test_refiner_fallback_on_error(self, mock_openai_class):
        """测试失败时回退到原始内容"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_openai_class.return_value = mock_client

        refiner = MemoryRefiner()
        raw = "用户喜欢周杰伦的一些歌"

        result = refiner.refine(raw)
        assert result == raw  # 回退到原始内容


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
