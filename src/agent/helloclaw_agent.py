"""HelloClaw Agent - 基于 HelloAgents SimpleAgent 的个性化 AI 助手"""

import os
import logging
from typing import List, Optional

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from hello_agents import Config
from .enhanced_simple_agent import EnhancedSimpleAgent
from .enhanced_llm import (
    EnhancedHelloAgentsLLM,
)  # HelloClaw 专用 LLM（支持流式工具调用）
from .response_sanitizer import sanitize_user_facing_text
from ..memory.memory_flush import MemoryFlushManager
from ..memory.capture import MemoryCaptureManager
from ..memory.hot_index import HotIndexManager
from hello_agents.tools import (
    ToolRegistry,
    ReadTool,
    WriteTool,
    EditTool,
    CalculatorTool,
)

from ..workspace.manager import WorkspaceManager
from ..tools import (
    MemoryTool,
    ExecuteCommandTool,
    WebSearchTool,
    WebFetchTool,
    WeatherTool,
    FindSkillTool,
)


class HelloClawAgent:
    """HelloClaw Agent - 个性化 AI 助手

    基于 HelloAgents SimpleAgent，增加了：
    - 工作空间管理（配置文件、记忆文件）
    - 从 AGENTS.md 读取系统提示词
    - HelloClaw 专属工具集
    """

    def __init__(
        self,
        workspace_path: str = None,
        name: str = None,
        model_id: str = None,
        api_key: str = None,
        base_url: str = None,
        max_tool_iterations: int = 10,
    ):
        """初始化 HelloClaw Agent

        Args:
            workspace_path: 工作空间路径，默认 ~/.helloclaw/workspace
            name: Agent 名称（从 IDENTITY.md 读取，无需手动指定）
            model_id: LLM 模型 ID
            api_key: API Key
            base_url: API Base URL
            max_tool_iterations: 最大工具调用迭代次数
        """
        # 确保 workspace_path 正确展开 ~/
        self.workspace_path = os.path.expanduser(
            workspace_path or "~/.helloclaw/workspace"
        )

        # 初始化工作空间管理器
        self.workspace = WorkspaceManager(self.workspace_path)

        # 确保工作空间存在
        self.workspace.ensure_workspace_exists()

        # 从 IDENTITY.md 读取名称，如果没有则使用默认值
        self.name = name or self._read_identity_name() or "HelloClaw"

        # 保存传入的参数（用于热加载时的优先级判断）
        self._override_model_id = model_id
        self._override_api_key = api_key
        self._override_base_url = base_url

        # 初始化 LLM（从 config.json 读取配置）
        self._init_llm()

        # 初始化配置
        self.config = Config(
            session_enabled=True,
            session_dir=os.path.join(self.workspace_path, "sessions"),
            compression_threshold=0.8,
            min_retain_rounds=10,
            enable_smart_compression=False,
            context_window=128000,
            trace_enabled=False,
            skills_enabled=True,
            skills_dir=os.path.join(self.workspace_path, "skills"),
            todowrite_enabled=False,
            devlog_enabled=False,
            subagent_enabled=True,  # 启用子 Agent 支持
        )

        # 初始化工具注册表
        self.tool_registry = self._setup_tools()

        # 初始化 Hot 记忆索引管理器
        self._hot_index_manager = HotIndexManager(self.workspace_path)

        # 初始化 Memory Flush 管理器（带五级压缩）
        self._memory_flush_manager = MemoryFlushManager(
            context_window=self.config.context_window,
            compression_threshold=self.config.compression_threshold,
            soft_threshold_tokens=4000,
            enabled=True,
            workspace_path=self.workspace_path,
        )

        # 初始化 Memory Capture 管理器
        self._memory_capture_manager = MemoryCaptureManager(self.workspace)

        # 构建系统提示词（从 AGENTS.md 读取）
        system_prompt = self._build_system_prompt()

        # 初始化底层 EnhancedSimpleAgent
        # 注意：我们已经手动注册了所有工具，包括skill_tool
        # 所以这里需要创建一个新的ToolRegistry实例，避免重复注册
        from hello_agents.tools.registry import ToolRegistry

        empty_registry = ToolRegistry()

        # 手动将我们的工具注册表中的工具复制到空注册表中
        # 这样可以避免EnhancedSimpleAgent在初始化过程中自动注册skill_tool
        for tool_name, tool in self.tool_registry._tools.items():
            try:
                empty_registry._tools[tool_name] = tool
                logger.info(f"工具 '{tool_name}' 已注册。")
            except Exception:
                pass

        # 创建EnhancedSimpleAgent实例
        self._agent = EnhancedSimpleAgent(
            name=self.name,  # 使用已读取的名字
            llm=self._llm,
            tool_registry=empty_registry,
            system_prompt=system_prompt,
            config=self.config,
            enable_tool_calling=True,
            max_tool_iterations=max_tool_iterations,
        )

        # 覆盖_agent的tool_registry为我们的完整工具注册表
        self._agent.tool_registry = self.tool_registry

    def _read_identity_name(self) -> str:
        """从 IDENTITY.md 读取助手名称

        Returns:
            助手名称，如果未设置则返回 None
        """
        import re

        identity = self.workspace.load_config("IDENTITY")
        if not identity:
            return None

        # 尝试匹配名称字段
        # 格式: - **名称：** xxx 或 - **名称:** xxx
        match = re.search(r"\*\*名称[：:]\*\*\s*(.+?)(?:\n|$)", identity)
        if match:
            name = match.group(1).strip()
            # 检查是否是占位符文本（包含下划线或"选一个"等）
            if (
                name
                and not name.startswith("_")
                and "选一个" not in name
                and "（" not in name
            ):
                return name
        return None

    def _init_llm(self):
        """初始化 LLM（从 config.json 读取配置）

        配置优先级：构造函数参数 > config.json > 环境变量 > 默认值
        """
        llm_config = self.workspace.get_llm_config()

        self._text_model_id = (
            self._override_model_id or llm_config.get("model_id") or "glm-4"
        )
        self._model_id = self._text_model_id
        self._api_key = self._override_api_key or llm_config.get("api_key")
        self._base_url = self._override_base_url or llm_config.get("base_url")

        self._llm = EnhancedHelloAgentsLLM(
            model=self._model_id,
            api_key=self._api_key,
            base_url=self._base_url,
        )

    def _reload_llm_if_changed(self) -> bool:
        """检查配置变化并重新加载 LLM

        如果 config.json 中的配置发生变化，重新创建 LLM 实例。

        Returns:
            是否发生了重新加载
        """
        llm_config = self.workspace.get_llm_config()

        new_model_id = self._override_model_id or llm_config.get("model_id") or "glm-4"
        new_api_key = self._override_api_key or llm_config.get("api_key")
        new_base_url = self._override_base_url or llm_config.get("base_url")

        if (
            new_model_id != self._model_id
            or new_api_key != self._api_key
            or new_base_url != self._base_url
        ):
            logger.info(f"检测到配置变化，重新加载 LLM: {self._model_id} -> {new_model_id}")

            self._model_id = new_model_id
            self._api_key = new_api_key
            self._base_url = new_base_url

            self._llm = EnhancedHelloAgentsLLM(
                model=self._model_id,
                api_key=self._api_key,
                base_url=self._base_url,
            )

            # 更新 Agent 的 LLM 引用
            if hasattr(self, "_agent"):
                self._agent.llm = self._llm

            return True
        return False

    def _switch_to_vision_model(self):
        """切换到多模态模型（当有图片时）"""
        vision_config = self.workspace.get_vision_config()

        # 检查是否启用视觉模型
        if not vision_config.get("enabled", False):
            logger.info("[Vision] 视觉模型未启用，跳过切换")
            return

        vision_model = vision_config.get("model_id", "qwen-vl-max")
        vision_api_key = vision_config.get("api_key") or self._api_key
        vision_base_url = vision_config.get("base_url") or self._base_url

        # 如果已经是视觉模型，不切换
        if hasattr(self, "_vision_model_id") and self._model_id == vision_model:
            return

        logger.info(f"[Vision] 切换到多模态模型: {self._model_id} -> {vision_model}")
        self._vision_model_id = vision_model
        self._model_id = vision_model
        self._api_key = vision_api_key
        self._base_url = vision_base_url

        self._llm = EnhancedHelloAgentsLLM(
            model=self._model_id,
            api_key=self._api_key,
            base_url=self._base_url,
        )

        if hasattr(self, "_agent"):
            self._agent.llm = self._llm

    def _switch_to_text_model(self):
        """切换回文本模型（当无图片时）"""
        # 如果之前切换过视觉模型，切换回来
        if hasattr(self, "_vision_model_id"):
            logger.info(f"[Vision] 切换回文本模型: {self._model_id} -> {self._text_model_id}")
            self._model_id = self._text_model_id

            # 恢复文本模型配置
            llm_config = self.workspace.get_llm_config()
            self._text_model_id = llm_config.get("model_id", "glm-4")
            self._api_key = llm_config.get("api_key")
            self._base_url = llm_config.get("base_url")

            self._llm = EnhancedHelloAgentsLLM(
                model=self._model_id,
                api_key=self._api_key,
                base_url=self._base_url,
            )

            if hasattr(self, "_agent"):
                self._agent.llm = self._llm

            del self._vision_model_id

    def _build_system_prompt(self) -> str:
        """构建系统提示词

        从 AGENTS.md 读取主要内容，附加其他配置文件作为上下文。
        如果入职未完成，注入 BOOTSTRAP.md 引导内容。

        Raises:
            RuntimeError: 如果 AGENTS.md 不存在
        """
        # 从 AGENTS.md 读取（必须存在）
        agents_content = self.workspace.load_config("AGENTS")
        if not agents_content:
            raise RuntimeError("AGENTS.md 配置文件不存在，请检查工作空间初始化")

        base_prompt = agents_content

        # 加载其他配置文件作为上下文
        context_parts = []

        # 检查入职是否完成
        if not self.workspace.is_onboarding_completed():
            bootstrap = self.workspace.load_config("BOOTSTRAP")
            if bootstrap:
                context_parts.append(f"\n## 初始化引导\n\n{bootstrap}")

        # 身份信息
        identity = self.workspace.load_config("IDENTITY")
        if identity:
            context_parts.append(f"\n## 你的身份信息\n{identity}")

        # 用户信息
        user_info = self.workspace.load_config("USER")
        if user_info:
            context_parts.append(f"\n## 用户信息\n{user_info}")

        # 人格模板
        soul = self.workspace.load_config("SOUL")
        if soul:
            context_parts.append(f"\n## 人格模板\n{soul}")

        # 长期记忆（Hot 层 - 指针索引）
        memory = self.workspace.load_config("MEMORY")
        if memory:
            # 使用 Hot 索引的精简版（指针）而非完整内容
            hot_index = self._hot_index_manager.get_compact_index()
            context_parts.append(
                f"\n## 长期记忆（仅内部参考，禁止原样输出标签或来源）\n{hot_index}"
            )
            context_parts.append(
                "\n## 回复风格约束\n"
                "- 你可以使用记忆来回答，但必须自然口语化表达。\n"
                "- 不要直接复述记忆条目，不要输出 Q:/A:/question: 模板。\n"
                "- 不要输出列表符号、来源标记或日期索引。\n"
            )

        if context_parts:
            return base_prompt + "\n" + "\n".join(context_parts)

        return base_prompt

    def _setup_tools(self) -> ToolRegistry:
        """设置工具集"""
        registry = ToolRegistry()

        # 注册工具时捕获Unicode编码错误
        def register_tool_safe(tool, auto_expand=False):
            try:
                registry.register_tool(tool, auto_expand=auto_expand)
            except UnicodeEncodeError:
                # 捕获HelloAgents库中register_tool方法的Unicode编码错误
                logger.info(f"工具 '{tool.name}' 已注册。")

        # HelloAgents 内置工具
        register_tool_safe(ReadTool(project_root=self.workspace_path))
        register_tool_safe(WriteTool(project_root=self.workspace_path))
        register_tool_safe(EditTool(project_root=self.workspace_path))
        register_tool_safe(CalculatorTool())

        # HelloClaw 自定义工具 - 使用 auto_expand=True 自动展开为子工具
        register_tool_safe(MemoryTool(self.workspace), auto_expand=True)
        register_tool_safe(
            ExecuteCommandTool(
                allowed_directories=[self.workspace_path],  # 限制在工作空间目录
                timeout=30,  # 限制命令执行时间
                max_output_size=10000  # 限制输出大小
            ),
            auto_expand=True,
        )
        register_tool_safe(WebSearchTool(), auto_expand=True)  # 网页搜索工具
        register_tool_safe(WebFetchTool(), auto_expand=True)  # 网页抓取工具
        register_tool_safe(WeatherTool(), auto_expand=True)  # 天气查询工具
        register_tool_safe(
            FindSkillTool(workspace_path=self.workspace_path), auto_expand=False
        )  # Skill 搜索安装工具

        return registry

    def chat(self, message: str, session_id: str = None) -> str:
        """同步聊天"""
        # 热加载配置（检测 config.json 变化）
        self._reload_llm_if_changed()

        # 每次都重新读取 IDENTITY.md 确保名字是最新的
        self.name = self._read_identity_name() or "HelloClaw"
        self._agent.name = self.name

        # 构建基础系统提示词
        base_prompt = self._build_system_prompt()

        # 强制前置指令（放在最前面最强）
        force_instruction = f"你叫 Andy，不是其他任何名字。当你被问到你叫什么时，你必须回答「我叫 Andy」。这是你的唯一名字。绝对不要说你叫「小智」或「ChatGPT」或任何其他名字。"

        # 在最前面添加强制指令
        self._agent.system_prompt = force_instruction + "\n\n" + base_prompt

        # 如果有 session_id，检查是否需要加载或清除历史
        if session_id:
            session_file = os.path.join(
                self.workspace_path, "sessions", f"{session_id}.json"
            )
            if os.path.exists(session_file):
                self._agent.load_session(session_file)
            else:
                self._agent.clear_history()
        else:
            self._agent.clear_history()

        # LLM 调用参数（防止重复循环）
        llm_kwargs = {
            "frequency_penalty": 0.5,  # 降低重复相同内容的概率
            "presence_penalty": 0.3,  # 鼓励谈论新话题
        }

        # 运行 Agent
        response = self._agent.run(message, **llm_kwargs)

        # 保存会话
        save_id = session_id or self.create_session()
        try:
            self._agent.save_session(save_id)
        except Exception as e:
            logger.error(f"保存会话失败: {e}")

        return sanitize_user_facing_text(response)

    async def achat(
        self,
        message: str,
        session_id: Optional[str] = None,
        images: Optional[List[str]] = None,
    ):
        """异步聊天（支持流式输出）

        Args:
            message: 用户消息
            session_id: 会话 ID，如果为 None 则创建新会话

        Yields:
            StreamEvent: 流式事件
        """
        import uuid
        import time

        t0 = time.time()
        logger.info(f"[timer {t0:.3f}] achat 开始")

        # 热加载配置（检测 config.json 变化）
        self._reload_llm_if_changed()

        # 如果有图片，切换到多模态模型
        if images:
            self._switch_to_vision_model()
        else:
            # 确保切换回文本模型（如果有配置）
            self._switch_to_text_model()

        # 每次都重新读取 IDENTITY.md 确保名字是最新的
        self.name = self._read_identity_name() or "HelloClaw"
        self._agent.name = self.name

        # 构建基础系统提示词
        base_prompt = self._build_system_prompt()

        # 强制前置指令
        force_instruction = "你叫 Andy，不是其他任何名字。当你被问到你叫什么时，你必须回答「我叫 Andy」。这是你的唯一名字。绝对不要说你叫「小智」或「ChatGPT」或任何其他名字。"

        final_prompt = force_instruction + "\n\n" + base_prompt
        self._agent.system_prompt = final_prompt

        # 调试：打印前100个字符
        logger.debug(f"[Debug] system_prompt 前100字符: {final_prompt[:100]}")
        logger.info(
            f"[timer {time.time():.3f}] 系统提示词构建完成 (+{time.time() - t0:.3f}s)"
        )

        # 如果没有 session_id，创建新的
        if not session_id:
            session_id = str(uuid.uuid4())[:8]
            self._agent.clear_history()
            # 重置 Memory Flush 状态（新会话）
            self._memory_flush_manager.reset()
        else:
            session_file = os.path.join(
                self.workspace_path, "sessions", f"{session_id}.json"
            )
            if os.path.exists(session_file):
                try:
                    self._agent.load_session(session_file)
                except UnicodeEncodeError:
                    # 捕获HelloAgents库中load_session方法的Unicode编码错误
                    logger.info("会话已恢复（Unicode编码错误）")
            else:
                self._agent.clear_history()
                self._memory_flush_manager.reset()
        logger.info(f"[timer {time.time():.3f}] 会话加载完成 (+{time.time() - t0:.3f}s)")

        # 保存 session_id 供后续保存使用
        self._current_session_id = session_id

        # LLM 调用参数（防止重复循环）
        llm_kwargs = {
            "frequency_penalty": 0.5,  # 降低重复相同内容的概率
            "presence_penalty": 0.3,  # 鼓励谈论新话题
        }

        t_llm = time.time()
        logger.info(f"[timer {t_llm:.3f}] 开始调用 LLM ({self._model_id})...")
        first_chunk = True

        async for event in self._agent.arun_stream_with_tools(
            message, images=images, **llm_kwargs
        ):
            if first_chunk and event.type.value == "llm_chunk":
                logger.info(
                    f"[timer {time.time():.3f}] 首个 token 到达 (LLM 延迟: {time.time() - t_llm:.3f}s)"
                )
                first_chunk = False
            yield event

        logger.info(
            f"[timer {time.time():.3f}] LLM 调用完成 (总耗时: {time.time() - t0:.3f}s)"
        )

        # 对话结束后自动捕获记忆（异步执行，不阻塞用户）
        await self._capture_memories(message)

        # 对话结束后检查是否需要触发 Memory Flush（异步执行，不阻塞用户）
        await self._check_and_run_memory_flush()

    async def _capture_memories(self, user_message: str):
        """自动捕获对话中的记忆

        Args:
            user_message: 用户消息
        """
        try:
            # 使用 MemoryCaptureManager 分析并存储记忆
            memories = await self._memory_capture_manager.acapture_and_store(
                user_message
            )

            if memories:
                logger.info(f"自动捕获 {len(memories)} 条记忆")
                for m in memories:
                    logger.info(f"   - [{m['category']}] {m['content'][:50]}...")
        except Exception as e:
            logger.error(f"记忆捕获失败: {e}")

    async def _check_and_run_memory_flush(self):
        """检查并执行 Memory Flush

        如果当前 token 数接近压缩阈值，触发一个静默回合提醒 Agent 保存记忆。
        """
        # 估算当前 token 数（简单估算：字符数 / 4）
        estimated_tokens = self._estimate_tokens()

        if self._memory_flush_manager.should_trigger_flush(estimated_tokens):
            logger.info(f"\n触发 Memory Flush（估算 token: {estimated_tokens}）")

            # 获取 flush 提示词
            flush_prompt = self._memory_flush_manager.get_flush_prompt()

            # 执行静默回合
            try:
                # 使用同步方法执行（不返回给用户）
                response = self._agent.run(flush_prompt)

                # 检查是否是静默响应
                if self._memory_flush_manager.is_silent_response(response):
                    logger.info("Agent 选择不保存记忆")
                else:
                    logger.info(f"Agent 已保存记忆")

            except Exception as e:
                logger.error(f"Memory Flush 失败: {e}")

    def _estimate_tokens(self) -> int:
        """估算当前上下文的 token 数
        使用 tiktoken 进行较精确的 token 计算 (选用 cl100k_base 作为泛用分词器)。
        如果 tiktoken 失败，则后备使用保守的字符估算：字符数 // 3。
        Returns:
            估算的 token 数
        """
        try:
            import tiktoken

            encoding = tiktoken.get_encoding("cl100k_base")
            total_tokens = 0

            # 系统提示词
            if self._agent.system_prompt:
                total_tokens += len(encoding.encode(self._agent.system_prompt))

            # 历史消息
            for msg in self._agent._history:
                if msg.content:
                    # 将内容统一视为字符串进行估算
                    content_str = (
                        msg.content
                        if isinstance(msg.content, str)
                        else str(msg.content)
                    )
                    total_tokens += len(encoding.encode(content_str))

            return total_tokens
        except ImportError:
            # Fallback
            total_chars = 0
            if self._agent.system_prompt:
                total_chars += len(self._agent.system_prompt)
            for msg in self._agent._history:
                if msg.content:
                    content_str = (
                        msg.content
                        if isinstance(msg.content, str)
                        else str(msg.content)
                    )
                    total_chars += len(content_str)
            return total_chars // 3

    def save_current_session(self):
        """保存当前会话"""
        if hasattr(self, "_current_session_id") and self._current_session_id:
            try:
                self._agent.save_session(self._current_session_id)
                return self._current_session_id
            except Exception as e:
                logger.error(f"保存会话失败: {e}")
        return None

    def create_session(self) -> str:
        """创建新会话"""
        import uuid

        session_id = str(uuid.uuid4())[:8]
        return session_id

    def list_sessions(self) -> List[dict]:
        """列出所有会话"""
        import json

        sessions_dir = os.path.join(self.workspace_path, "sessions")
        if not os.path.exists(sessions_dir):
            return []

        sessions = []
        for filename in os.listdir(sessions_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(sessions_dir, filename)
                stat = os.stat(filepath)

                last_user_message = ""
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    history = data.get("history", [])
                    for msg in reversed(history):
                        if msg.get("role") == "user":
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                for part in content:
                                    if (
                                        isinstance(part, dict)
                                        and part.get("type") == "text"
                                    ):
                                        last_user_message = part.get("text", "")
                                        break
                            elif isinstance(content, str):
                                last_user_message = content
                            break
                except Exception:
                    pass

                sessions.append(
                    {
                        "id": filename[:-5],
                        "created_at": stat.st_ctime,
                        "updated_at": stat.st_mtime,
                        "last_user_message": last_user_message[:50],
                    }
                )

        return sorted(sessions, key=lambda x: x["updated_at"], reverse=True)

    async def alist_sessions(self) -> List[dict]:
        """异步列出所有会话"""
        import json
        import asyncio
        import aiofiles

        sessions_dir = os.path.join(self.workspace_path, "sessions")
        if not os.path.exists(sessions_dir):
            return []

        sessions = []
        filenames = [f for f in os.listdir(sessions_dir) if f.endswith(".json")]

        async def _process_file(filename):
            filepath = os.path.join(sessions_dir, filename)
            try:
                # 获取文件的元数据可以使用 asyncio.to_thread 防止阻塞
                stat = await asyncio.to_thread(os.stat, filepath)

                last_user_message = ""
                async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                    content_str = await f.read()
                    data = json.loads(content_str)

                history = data.get("history", [])
                for msg in reversed(history):
                    if msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            for part in content:
                                if (
                                    isinstance(part, dict)
                                    and part.get("type") == "text"
                                ):
                                    last_user_message = part.get("text", "")
                                    break
                        elif isinstance(content, str):
                            last_user_message = content
                        break

                return {
                    "id": filename[:-5],
                    "created_at": stat.st_ctime,
                    "updated_at": stat.st_mtime,
                    "last_user_message": last_user_message[:50],
                }
            except Exception:
                return None

        # 并发读取解析所有文件
        results = await asyncio.gather(*[_process_file(f) for f in filenames])
        for res in results:
            if res:
                sessions.append(res)

        return sorted(sessions, key=lambda x: x["updated_at"], reverse=True)

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        filepath = os.path.join(self.workspace_path, "sessions", f"{session_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False

    def get_session_history(self, session_id: str) -> List[dict]:
        """获取会话历史消息"""
        import json

        filepath = os.path.join(self.workspace_path, "sessions", f"{session_id}.json")
        if not os.path.exists(filepath):
            return []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            return self._format_raw_history(data.get("history", []))
        except Exception as e:
            print(f"Error loading session history: {e}")
            return []

    async def aget_session_history(self, session_id: str) -> List[dict]:
        """异步获取会话历史消息"""
        import json
        import aiofiles

        filepath = os.path.join(self.workspace_path, "sessions", f"{session_id}.json")
        if not os.path.exists(filepath):
            return []

        try:
            async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                content_str = await f.read()
                data = json.loads(content_str)

            return self._format_raw_history(data.get("history", []))
        except Exception as e:
            print(f"Error loading session history async: {e}")
            return []

    def _format_raw_history(self, raw_history: List[dict]) -> List[dict]:
        """统一格式化 raw_history 到标准 messages 结构"""
        messages = []
        for msg in raw_history:
            role = msg.get("role", "")
            if role in ("user", "assistant", "tool"):
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)
                    content = "\n".join(text_parts)

                message_obj: dict = {"role": role, "content": content}
                if "metadata" in msg:
                    message_obj["metadata"] = msg["metadata"]
                messages.append(message_obj)
        return messages

    def clear_all_history(self):
        """清除 Agent 内存中的所有历史记录

        用于初始化时重置 Agent 状态。
        """
        self._agent.clear_history()
        self._current_session_id = None

        # 重置 MemoryFlushManager 状态
        if hasattr(self, "_memory_flush_manager"):
            self._memory_flush_manager.reset()

        # 重新读取 name（因为 IDENTITY.md 可能已被重置）
        self.name = self._read_identity_name() or "HelloClaw"
