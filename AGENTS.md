# HelloClaw Development Guide

## 核心原则

当你遇到**不知道如何操作**的任务时，必须尝试使用 **find_skill** 工具搜索相关 skills 来解决问题，不要直接回答不会。

### find_skill 工具使用场景
- 遇到不熟悉的技术栈或工具时
- 不知道如何完成某个具体操作时
- 需要执行但缺乏相关知识的功能时

### 使用方法
1. 使用 `find_skill search <关键词>` 搜索相关 skills
2. 根据搜索结果，使用 `find_skill install <skill包名>` 安装需要的 skill
3. 安装后即可使用该 skill 扩展的能力

## Skills 系统

项目集成了两层 Skills 系统：

### 1. FindSkillTool（远程搜索/安装）
- 功能：搜索 skills.sh 仓库、安装远程 skills
- 使用：`find_skill search <关键词>` 或 `find_skill install <包名>`
- 安装的 skills 会保存到工作空间的 `skills/` 目录

### 2. SkillTool（hello_agents 内置 - 本地加载）
- 功能：加载本地 skills 目录中的技能知识
- 自动注册：当 `config.skills_enabled=True` 时启用
- Skills 目录：`~/.helloclaw/workspace/skills/`

### 本地 Skill 目录结构
```
skills/
├── <skill-name>/
│   ├── SKILL.md        # 技能定义（必需）
│   ├── scripts/        # 脚本文件
│   ├── references/     # 参考文档
│   ├── assets/         # 资源文件
│   └── examples/       # 示例代码
```

## Project Overview

HelloClaw is an AI agent backend built on FastAPI and HelloAgents framework. It provides chat interfaces with streaming support, memory management, and tool execution capabilities.

## Build Commands

### Backend (Python)

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (with auto-reload)
PYTHONIOENCODING=utf-8 python -m src.main

# Or run directly
PYTHONIOENCODING=utf-8 python src/main.py

# Run tests (if available)
pytest
pytest tests/test_file.py::TestClass::test_method  # Single test
```

### Frontend (Vue + TypeScript)

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Type check only
npm run type-check
```

## Code Style Guidelines

### Python Backend

#### Imports

- Use absolute imports (`from src.api import chat`)
- Order: stdlib → third-party → local
- Group with blank lines: stdlib, third-party, local

```python
import os
import json
from typing import Optional, List

from fastapi import APIRouter
from pydantic import BaseModel

from src.api import chat
from src.agent import HelloClawAgent
```

#### Formatting

- Max line length: 100 characters
- Use 4 spaces for indentation
- Use blank lines: 2 between top-level, 1 between methods

#### Types

- Use type hints for function signatures and return values
- Use `Optional[T]` instead of `T | None` for compatibility
- Avoid `Any` when possible

```python
def process_data(items: List[str], options: Optional[Dict] = None) -> Dict[str, Any]:
    pass
```

#### Naming Conventions

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_private_method`

#### Error Handling

- Use try/except sparingly, only when recovery is possible
- Prefer returning error responses over raising exceptions in API handlers
- Log errors with appropriate level

```python
try:
    result = do_something()
except ValueError as e:
    logger.warning(f"Invalid input: {e}")
    return {"error": "Invalid input"}
```

### TypeScript Frontend

- Use functional components with Composition API
- Use TypeScript strict mode
- Follow Vue 3 composition API patterns

```typescript
import { ref, computed } from 'vue'

interface Props {
  title: string
}

const props = defineProps<Props>()
const count = ref(0)
```

### Git Commit Messages

- Use imperative mood: "Add feature" not "Added feature"
- First line: max 50 characters
- Body: max 72 characters per line

## Project Structure

```
.
├── src/
│   ├── main.py              # FastAPI entry point
│   ├── api/                 # API routes (chat, session, config, memory)
│   ├── agent/               # Agent implementations
│   ├── workspace/           # Workspace manager
│   ├── memory/             # Memory management
│   └── tools/builtin/      # Custom tools (memory, execute, web)
├── frontend/                # Vue 3 + TypeScript frontend
├── requirements.txt        # Python dependencies
└── AGENTS.md              # This file
```

## Key Patterns

### API Route Structure

```python
from fastapi import APIRouter

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/send")
async def send_message(request: RequestModel):
    return ResponseModel(data=...)
```

### Agent Tool Implementation

```python
from hello_agents.tools import Tool, ToolParameter, tool_action

class CustomTool(Tool):
    def __init__(self, workspace_manager):
        super().__init__(name="custom", description="...")
        self.workspace = workspace_manager

    @tool_action("action_name", "Description")
    def _do_action(self, param: str) -> str:
        return result
```

## Testing Guidelines

- No formal test suite exists yet
- When adding tests, use `pytest`
- Place tests in `tests/` directory
- Test file naming: `test_*.py` or `*_test.py`

## Environment Variables

Create `.env` file for local development:

```env
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4
WORKSPACE_PATH=~/.helloclaw/workspace
PORT=8000
CORS_ORIGINS=http://localhost:5173
```

## Common Tasks

### Restart Backend After Config Change

```bash
# Kill existing process
taskkill //IM python.exe //F

# Restart
PYTHONIOENCODING=utf-8 python -m src.main
```

### Add New API Endpoint

1. Create/modify router in `src/api/`
2. Register in `src/main.py` via `app.include_router()`
3. Update frontend API client if needed

### Add New Tool

1. Create tool class in `src/tools/builtin/`
2. Register in `HelloClawAgent._setup_tools()`
3. Tool follows `@tool_action` pattern for sub-commands

## MCP Services

### Chrome DevTools MCP

配置浏览器调试功能，用于操作网页和调试：

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": [
        "-y",
        "chrome-devtools-mcp@latest"
      ]
    }
  }
}
```

使用方法：
1. 确保已安装 Chrome 浏览器
2. 以远程调试模式启动 Chrome：`chrome.exe --remote-debugging-port=9222`
3. 通过 Agent 使用浏览器调试功能

