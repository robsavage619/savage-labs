from __future__ import annotations

import asyncio
import json
import logging

import anthropic
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from shc.ai.briefing import CHAT_SYSTEM, build_daily_context
from shc.config import settings
from shc.db.schema import get_read_conn

router = APIRouter(tags=["chat"])
log = logging.getLogger(__name__)

MODEL = "claude-opus-4-7"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


def _build_system(conn) -> list[dict]:
    """Build the system prompt blocks: static clinical profile + live data."""
    live_context = build_daily_context(conn)
    return [
        {
            "type": "text",
            "text": CHAT_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": live_context,
        },
    ]


async def _stream_response(messages: list[dict]):
    if not settings.anthropic_api_key:
        yield "data: " + json.dumps({
            "type": "error",
            "text": "Advisor not configured — add ANTHROPIC_API_KEY to shc.env",
        }) + "\n\n"
        return

    conn = get_read_conn()
    try:
        system = _build_system(conn)
    finally:
        conn.close()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _run_stream():
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=1024,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    asyncio.run_coroutine_threadsafe(queue.put(text), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                queue.put(json.dumps({"__error": str(e)})), loop
            )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    thread = loop.run_in_executor(None, _run_stream)

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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


