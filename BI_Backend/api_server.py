"""HTTP API for the BI frontend (Angular): analytics dashboard + chatbot.

Read-only, like the MCP server: it reuses the same MongoDB client and IDP
tools. Run from this folder:

    uvicorn api_server:app --reload --port 8000

Endpoints
  GET  /api/health                 database reachable? chatbot configured?
  GET  /api/dashboard?days=30      KPIs + charts for the dashboard
  POST /api/chat                   {"messages": [{"role": "user"|"assistant", "content": str}]}
                                   -> {"answer": markdown, "charts": [chart spec], "steps": [...]}
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

import anthropic  # noqa: E402
import openai  # noqa: E402
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from chat_agent import ChatAgent  # noqa: E402
from dashboard import Dashboard  # noqa: E402
from mongo_db import MongoMetadataClient  # noqa: E402

app = FastAPI(title="Actuvara BI API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:4200").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_mongo: MongoMetadataClient | None = None
_agent: ChatAgent | None = None


def _db() -> MongoMetadataClient:
    global _mongo
    if _mongo is None:
        _mongo = MongoMetadataClient()
    return _mongo


def _chat() -> ChatAgent:
    global _agent
    if _agent is None:
        _agent = ChatAgent(_db())
    return _agent


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


@app.get("/api/health")
def health() -> dict:
    out = {"database": False, "chat_configured": bool(
        os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("ANTHROPIC_FOUNDRY_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))}
    try:
        out["database"] = _db().ping()
        out["database_name"] = _db().default_database
    except Exception as ex:
        out["database_error"] = f"{type(ex).__name__}: {ex}"
    return out


@app.get("/api/dashboard")
def dashboard(days: int = Query(30, ge=0, le=3650)) -> dict:
    try:
        return Dashboard(_db().database()).build(days)
    except Exception as ex:
        raise HTTPException(503, f"Database unavailable: {type(ex).__name__}: {ex}") from ex


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict:
    if req.messages[-1].role != "user":
        raise HTTPException(400, "The last message must be the user's question")
    try:
        return await run_in_threadpool(_chat().answer, [m.model_dump() for m in req.messages])
    except (anthropic.AuthenticationError, openai.AuthenticationError) as ex:
        raise HTTPException(500, "Model key rejected (401): check the API key and endpoint in BI_Backend/.env "
                                 "- they must come from the same resource") from ex
    except (anthropic.NotFoundError, openai.NotFoundError) as ex:
        raise HTTPException(500, "Model deployment not found (404): check AZURE_OPENAI_DEPLOYMENT / CHAT_MODEL "
                                 "and the endpoint in BI_Backend/.env") from ex
    except (anthropic.RateLimitError, openai.RateLimitError) as ex:
        raise HTTPException(429, "The assistant is busy (rate limited) - try again in a minute") from ex
    except (anthropic.APIConnectionError, openai.APIConnectionError) as ex:
        print(f"[actuvara-api] connection failed: {ex.__cause__ or ex}", file=sys.stderr, flush=True)
        raise HTTPException(502, "Could not reach the model endpoint - check the endpoint / resource name "
                                 "in BI_Backend/.env") from ex
    except (anthropic.APIStatusError, openai.APIStatusError) as ex:
        print(f"[actuvara-api] model API error {ex.status_code}: {ex.message}", file=sys.stderr, flush=True)
        raise HTTPException(502, f"Model API error ({ex.status_code}): {str(ex.message)[:300]}") from ex
    except Exception as ex:
        print(f"[actuvara-api] chat failed: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
        raise HTTPException(500, f"{type(ex).__name__}: {ex}") from ex
