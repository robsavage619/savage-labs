from __future__ import annotations

import asyncio
import json
import logging

import anthropic
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from shc.ai.briefing import CHAT_SYSTEM
from shc.config import settings

router = APIRouter(tags=["chat"])
log = logging.getLogger(__name__)

MODEL = "claude-opus-4-7"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


async def _stream_response(messages: list[dict]):
    if not settings.anthropic_api_key:
        yield "data: " + json.dumps({"type": "error", "text": "Advisor not configured — add ANTHROPIC_API_KEY to shc.env"}) + "\n\n"
        return

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _run_stream():
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": CHAT_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
                thinking={"type": "adaptive"},
            ) as stream:
                for text in stream.text_stream:
                    asyncio.run_coroutine_threadsafe(queue.put(text), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                queue.put(json.dumps({"__error": str(e)})), loop
            )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    thread = asyncio.get_event_loop().run_in_executor(None, _run_stream)

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        if isinstance(chunk, str) and chunk.startswith('{"__error":'):
            yield "data: " + json.dumps({"type": "error", "text": json.loads(chunk)["__error"]}) + "\n\n"
            break
        yield "data: " + json.dumps({"type": "text", "text": chunk}) + "\n\n"

    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
    await thread


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    return StreamingResponse(
        _stream_response(messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
