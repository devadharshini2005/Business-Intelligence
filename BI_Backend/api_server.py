"""HTTP API for the Angular frontend. Everything goes through the MCP server: on start-up this app
launches mcp_server.py (the same read-only server Copilot uses) and calls its tools over MCP.

    python api_server.py        (= uvicorn api_server:app --reload --port 8000)

  GET  /api/health                 database reachable? chatbot configured?        (MCP: ping_db)
  GET  /api/dashboard?days=30      KPI tiles + charts                              (MCP: get_dashboard)
  GET  /api/mcp                    MCP server, transport and tool list for the source panel (MCP: list_tools,
                                   server_info)
  GET  /api/submissions?source=&status=&search=&days=&limit=
                                   submission list, newest first                   (MCP: idp_find_submissions)
  GET  /api/collections            collections with approximate document counts    (MCP: list_collections)
  GET  /api/collections/{c}/schema inferred fields and types of one collection    (MCP: infer_collection_schema)
  GET  /api/submissions/{id}       one submission (or file / run id) for the panel (MCP: idp_get_submission)
  POST /api/chat/stream            {"messages": [{"role", "content"}]} -> server-sent events:
                                   step / chart while the answer is built, then done {answer, charts, steps,
                                   follow_ups} or error {detail}                   (MCP: chat_agent tools)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env", override=True)

import openai  # noqa: E402
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from chat_agent import ChatAgent, call_tool  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    server = StdioServerParameters(command=sys.executable, args=[str(HERE / "mcp_server.py")], cwd=str(HERE))
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        app.state.mcp = session
        app.state.agent = ChatAgent(session) if os.getenv("AZURE_OPENAI_API_KEY") else None
        yield


app = FastAPI(title="Actuvara BI API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_methods=["GET", "POST"], allow_headers=["*"],
                   allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:4200").split(","))


async def mcp_tool(name: str, args: dict[str, Any], not_found: bool = False) -> Any:
    """Call an MCP tool for an endpoint; a tool error becomes 404 (lookups), 504 (timed out) or 503."""
    data, error = await call_tool(app.state.mcp, name, args)
    if error:
        status = 404 if not_found and "found" in str(data) else 504 if "timed out" in str(data) else 503
        raise HTTPException(status, f"{name}: {data}")
    return data


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


@app.get("/api/health")
async def health() -> dict:
    ping, _ = await call_tool(app.state.mcp, "ping_db", {})
    ping = ping if isinstance(ping, dict) else {}
    return {"database": bool(ping.get("connected")), "database_error": ping.get("error"),
            "database_name": os.getenv("MONGODB_DATABASE", ""), "chat_configured": app.state.agent is not None}


@app.get("/api/dashboard")
async def dashboard(days: int = Query(30, ge=0, le=3650)) -> dict:
    return await mcp_tool("get_dashboard", {"days": days})


@app.get("/api/mcp")
async def mcp_info() -> dict:
    tools = await app.state.mcp.list_tools()
    info, error = await call_tool(app.state.mcp, "server_info", {})
    return {"server": "actuvara-cosmos-db", "transport": "stdio", "server_info": None if error else info,
            "tools": [{"name": t.name, "description": (t.description or "").strip().split("\n")[0]}
                      for t in tools.tools]}


@app.get("/api/submissions")
async def submissions(source: str = "", status: str = "", search: str = "",
                      days: int = Query(0, ge=0, le=3650), limit: int = Query(50, ge=1, le=200)) -> dict:
    return await mcp_tool("idp_find_submissions",
                          {"source": source, "status": status, "search": search, "days": days, "limit": limit})


@app.get("/api/collections")
async def collections() -> dict:
    return await mcp_tool("list_collections", {})


@app.get("/api/collections/{collection}/schema")
async def collection_schema(collection: str) -> dict:
    return await mcp_tool("infer_collection_schema", {"collection": collection, "sample_size": 100}, not_found=True)


@app.get("/api/submissions/{submission_id}")
async def submission(submission_id: str) -> dict:
    return await mcp_tool("idp_get_submission", {"submission_id": submission_id}, not_found=True)


def _chat_error(ex: Exception) -> str:
    if isinstance(ex, openai.AuthenticationError):
        return "Model key rejected (401): check AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in BI_Backend/.env"
    if isinstance(ex, openai.NotFoundError):
        return "Model deployment not found (404): check AZURE_OPENAI_DEPLOYMENT in BI_Backend/.env"
    if isinstance(ex, openai.RateLimitError):
        return "The assistant is busy (rate limited) - try again in a minute"
    if isinstance(ex, openai.APIConnectionError):
        return "Could not reach the model endpoint - check AZURE_OPENAI_ENDPOINT in BI_Backend/.env"
    if isinstance(ex, openai.APIStatusError):
        return f"Model API error ({ex.status_code}): {str(ex.message)[:300]}"
    return f"{type(ex).__name__}: {ex}"


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    if req.messages[-1].role != "user":
        raise HTTPException(400, "The last message must be the user's question")
    if app.state.agent is None:
        raise HTTPException(500, "Chatbot not configured: set AZURE_OPENAI_API_KEY in BI_Backend/.env")
    events: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

    async def work() -> None:
        try:
            history = [m.model_dump() for m in req.messages]
            events.put_nowait(("done", await app.state.agent.answer(history, emit=lambda *e: events.put_nowait(e))))
        except Exception as ex:
            print(f"[actuvara-api] chat failed: {ex!r}", file=sys.stderr, flush=True)
            events.put_nowait(("error", {"detail": _chat_error(ex)}))
        finally:
            events.put_nowait(None)

    async def stream() -> AsyncIterator[str]:
        task = asyncio.create_task(work())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(events.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # stops proxies closing an idle connection
                    continue
                if item is None:
                    return
                yield f"event: {item[0]}\ndata: {json.dumps(item[1], default=str)}\n\n"
        finally:
            task.cancel()  # the browser went away (Stop / closed tab)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="127.0.0.1", port=int(os.getenv("BI_API_PORT", "8000")), reload=True)
