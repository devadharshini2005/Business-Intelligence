"""HTTP API for the BI frontend (Angular): analytics dashboard + chatbot.

Read-only, like the MCP server: it reuses the same MongoDB client and IDP
tools. Run from this folder:

    uvicorn api_server:app --reload --port 8000

Endpoints
  GET  /api/health                 database reachable? chatbot configured?
  GET  /api/dashboard?days=30      KPIs + charts for the dashboard
  POST /api/chat                   {"messages": [{"role": "user"|"assistant", "content": str}]}
                                   -> {"answer": markdown, "charts": [chart spec], "steps": [...]}
  Angular dashboard pages (bi_analytics.py / idp_flow.py, read-only):
  GET  /api/overview?days=30       KPIs vs the previous period, run status counts, file funnel
  GET  /api/trend?days=30          submissions per day by source, runs per day
  GET  /api/processes?days=30      runs per process: completed / failed / other, success rate, avg time
  GET  /api/node-hotspots?days=30  workflow nodes most often failed / rejected / awaiting approval
  GET  /api/collections            every collection with its estimated document count
  GET  /api/submissions            same as the idp_find_submissions tool (source, status, search, days, limit)
  GET  /api/submissions/{id}       same as idp_get_submission
  GET  /api/runs/{id}              same as idp_get_run_details
  /                                the built Angular app (BI_Frontend: `npm run build`), if present
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

from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from bi_analytics import BiAnalytics  # noqa: E402
from chat_agent import ChatAgent  # noqa: E402
from dashboard import Dashboard  # noqa: E402
from idp_flow import IdpFlow  # noqa: E402
from mongo_db import MongoMetadataClient  # noqa: E402
from query_guard import QueryGuardError  # noqa: E402

# Production build of the Angular app (BI_Frontend: `npm run build`), served at "/".
FRONTEND_DIST = Path(os.getenv("BI_FRONTEND_DIST") or
                     Path(__file__).resolve().parents[1] / "BI_Frontend" / "dist" / "actuvara-bi" / "browser")

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
        _agent = ChatAgent()
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


# --- Angular dashboard pages ------------------------------------------------------
# Each call is a fixed read-only pipeline; FastAPI runs these sync handlers in a thread pool.

def _analytics() -> BiAnalytics:
    return BiAnalytics(_db().database())


def _idp() -> IdpFlow:
    return IdpFlow(_db().database())


def _read(fn):
    """Bad ids / arguments -> 400, anything else (e.g. database down) -> 503."""
    try:
        return fn()
    except (ValueError, QueryGuardError) as ex:
        raise HTTPException(400, str(ex)) from ex
    except Exception as ex:
        print(f"[actuvara-api] read failed: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
        raise HTTPException(503, f"Database unavailable: {type(ex).__name__}: {ex}") from ex


@app.get("/api/overview")
def overview(days: int = Query(30, ge=1, le=365)) -> dict:
    return _read(lambda: _analytics().overview(days))


@app.get("/api/trend")
def trend(days: int = Query(30, ge=1, le=365)) -> dict:
    return _read(lambda: _analytics().trend(days))


@app.get("/api/processes")
def processes(days: int = Query(30, ge=1, le=365)) -> list:
    return _read(lambda: _analytics().processes(days))


@app.get("/api/node-hotspots")
def node_hotspots(days: int = Query(30, ge=1, le=365)) -> list:
    return _read(lambda: _analytics().node_hotspots(days))


@app.get("/api/collections")
def collections() -> list:
    return _read(lambda: _analytics().collections())


@app.get("/api/submissions")
def submissions(source: str = "", status: str = "", search: str = "",
                days: int = Query(0, ge=0, le=3650), limit: int = Query(25, ge=1, le=200)) -> list:
    return _read(lambda: _idp().find_submissions(source, status, search, days, limit))


@app.get("/api/submissions/{submission_id}")
def submission(submission_id: str) -> dict:
    return _read(lambda: _idp().get_submission(submission_id))


@app.get("/api/runs/{run_id}")
def run_details(run_id: str) -> dict:
    return _read(lambda: _idp().get_run_details(run_id))


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


# --- Angular frontend ---------------------------------------------------------------
# Registered last so every /api route above wins. The app uses hash routes (/#/overview),
# so index.html at "/" covers every page.
@app.api_route("/api/{rest:path}", methods=["GET", "POST"], include_in_schema=False)
def api_not_found(rest: str) -> None:
    raise HTTPException(404, f"unknown endpoint /api/{rest}")


if (FRONTEND_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def frontend_missing() -> HTMLResponse:
        return HTMLResponse(
            "<h2>Actuvara BI API is running</h2><p>The dashboard hasn't been built yet: in <code>BI_Frontend</code> "
            "run <code>npm install</code> and <code>npm run build</code>, then restart this server "
            f"(or use <code>npm start</code> for development).</p><p>Looked in <code>{FRONTEND_DIST}</code></p>",
            status_code=503)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("BI_API_HOST", "127.0.0.1"), port=int(os.getenv("BI_API_PORT", "8000")))
