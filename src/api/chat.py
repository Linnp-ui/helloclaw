"""聊天 API 路由"""

import json
import os
import uuid
import base64
import logging
from typing import Optional, List

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import EventSourceResponse
from pydantic import BaseModel

os.environ["SSE_STARLETTE_DEBUG"] = "0"

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ContentPart(BaseModel):
    """消息内容片段"""

    type: str
    text: Optional[str] = None
    image_url: Optional[dict] = None


class ChatRequest(BaseModel):
    """聊天请求"""

    message: str
    session_id: Optional[str] = None
    images: Optional[List[str]] = None  # base64 编码的图片列表


class ChatResponse(BaseModel):
    """聊天响应"""

    content: str
    session_id: Optional[str] = None


def get_agent():
    """获取全局 Agent 实例"""
    from ..main import get_agent as _get_agent

    return _get_agent()


@router.post("/send/sync", response_model=ChatResponse)
async def send_message_sync(request: ChatRequest):
    """发送消息并获取同步响应"""
    agent = get_agent()
    if not agent:
        return ChatResponse(
            content="Agent not initialized", session_id=request.session_id
        )

    response = agent.chat(request.message, request.session_id)
    return ChatResponse(content=response, session_id=request.session_id)


@router.post("/send/stream")
async def send_message_stream(request: ChatRequest, http_request: Request = None):
    """发送消息并获取流式响应 (SSE)

    支持多模态输入：
    - message: 文本消息
    - session_id: 会话 ID
    - images: 图片文件引用列表（如 ["uploads/123.jpg"]）

    事件类型：
    - session: 会话信息（包含 session_id）
    - step_start: 步骤开始
    - chunk: LLM 文本块
    - tool_start: 工具调用开始
    - tool_finish: 工具调用结束
    - step_finish: 步骤结束
    - done: 完成
    - error: 错误
    """
    parsed_images = request.images

    async def event_generator():
        import asyncio
        import time

        agent = get_agent()
        if not agent:
            logger.error("Agent not initialized")
            yield {
                "event": "error",
                "data": json.dumps(
                    {"error": "Agent not initialized"}, ensure_ascii=False
                ),
            }
            return

        queue = asyncio.Queue()

        async def populate_queue():
            try:
                logger.info("Starting agent.achat")
                start_time = time.time()

                # 读取引用的图片转换为 base64
                processed_images = []
                if parsed_images:
                    for img_ref in parsed_images:
                        if img_ref.startswith("uploads/"):
                            # 从 workspace 获取对应文件
                            img_path = os.path.join(
                                agent.workspace.workspace_path, img_ref
                            )
                            if os.path.exists(img_path):
                                with open(img_path, "rb") as f:
                                    img_data = base64.b64encode(f.read()).decode(
                                        "utf-8"
                                    )
                                    # 推断格式
                                    ext = img_ref.split(".")[-1].lower()
                                    mime_type = (
                                        f"image/{ext}"
                                        if ext in ["png", "jpeg", "jpg", "webp", "gif"]
                                        else "image/jpeg"
                                    )
                                    processed_images.append(
                                        f"data:{mime_type};base64,{img_data}"
                                    )
                            else:
                                logger.warning(f"Image not found: {img_path}")
                        else:
                            # 可能是 base64 或外链，直接使用
                            processed_images.append(img_ref)

                async for event in agent.achat(
                    request.message, request.session_id, images=processed_images
                ):
                    await queue.put({"type": "event", "data": event})
                await queue.put({"type": "done"})
                logger.info(f"agent.achat completed in {time.time() - start_time:.2f}s")
            except Exception as e:
                import traceback

                logger.exception(f"agent.achat error: {e}")
                await queue.put({"type": "error", "error": str(e)})

        task = asyncio.create_task(populate_queue())

        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)

                if item["type"] == "done":
                    break
                elif item["type"] == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {"error": item["error"]}, ensure_ascii=False
                        ),
                    }
                    break

                event = item["data"]
                event_type = event.type.value
                event_data = event.data

                # 处理不同类型的事件
                if event_type == "agent_start":
                    # 发送会话信息
                    current_session_id = getattr(agent, "_current_session_id", None)
                    yield {
                        "event": "session",
                        "data": json.dumps(
                            {"session_id": current_session_id}, ensure_ascii=False
                        ),
                    }

                elif event_type == "step_start":
                    # 步骤开始
                    yield {
                        "event": "step_start",
                        "data": json.dumps(
                            {
                                "step": event_data.get("step", 1),
                                "max_steps": event_data.get("max_steps", 10),
                            },
                            ensure_ascii=False,
                        ),
                    }

                elif event_type == "llm_chunk":
                    # LLM 文本块
                    chunk = event_data.get("chunk", "")
                    yield {
                        "event": "chunk",
                        "data": json.dumps({"content": chunk}, ensure_ascii=False),
                    }

                elif event_type == "tool_call_start":
                    # 工具调用开始
                    yield {
                        "event": "tool_start",
                        "data": json.dumps(
                            {
                                "tool": event_data.get("tool_name", ""),
                                "args": event_data.get("args", {}),
                            },
                            ensure_ascii=False,
                        ),
                    }

                elif event_type == "tool_call_finish":
                    # 工具调用结束
                    yield {
                        "event": "tool_finish",
                        "data": json.dumps(
                            {
                                "tool": event_data.get("tool_name", ""),
                                "result": event_data.get("result", ""),
                            },
                            ensure_ascii=False,
                        ),
                    }

                elif event_type == "step_finish":
                    # 步骤结束
                    yield {
                        "event": "step_finish",
                        "data": json.dumps(
                            {"step": event_data.get("step", 1)}, ensure_ascii=False
                        ),
                    }

                elif event_type == "agent_finish":
                    # Agent 完成，保存会话
                    current_session_id = agent.save_current_session()
                    final_content = event_data.get("result", "")

                    yield {
                        "event": "done",
                        "data": json.dumps(
                            {
                                "content": final_content,
                                "session_id": current_session_id,
                            },
                            ensure_ascii=False,
                        ),
                    }

                elif event_type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {"error": event_data.get("error", "Unknown error")},
                            ensure_ascii=False,
                        ),
                    }

            except asyncio.TimeoutError:
                # 超过 15 秒没有事件，发送 Keep-alive Ping
                yield {"event": "ping", "data": json.dumps({"timestamp": time.time()})}

    try:
        return EventSourceResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.exception(f"EventSourceResponse failed: {e}")
        return {"error": str(e)}


@router.post("/send")
async def send_message(request: ChatRequest):
    """发送消息（暂返回同步响应）"""
    return await send_message_sync(request)


class UploadResponse(BaseModel):
    url: str


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """上传文件"""
    agent = get_agent()
    if not agent:
        # 如果没有 agent，默认按环境处理
        workspace_path = os.path.expanduser(
            os.getenv("WORKSPACE_PATH", "~/.helloclaw/workspace")
        )
    else:
        workspace_path = agent.workspace.workspace_path

    uploads_dir = os.path.join(workspace_path, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    # 生成唯一文件名
    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(uploads_dir, filename)

    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    return UploadResponse(url=f"uploads/{filename}")
