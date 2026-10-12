"""Chatbot over the Actuvara database: an LLM answers questions using the same
read-only tools the MCP server exposes, and attaches charts built from real
query results.

The model never writes chart numbers itself: `create_chart` takes an
aggregation pipeline, this module runs it (through query_guard, read-only) and
turns the rows into a chart spec. The chart and the text come from the same data.

Configuration (.env) - the first provider whose key is set is used:
  Azure OpenAI (e.g. GPT-4.1 in Azure AI Foundry)
                      AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT,
                      optional AZURE_OPENAI_API_VERSION
  Claude on Foundry   ANTHROPIC_FOUNDRY_API_KEY + ANTHROPIC_FOUNDRY_RESOURCE (or ANTHROPIC_FOUNDRY_BASE_URL);
                      CHAT_MODEL = your Claude deployment name; optional CHAT_FALLBACK_MODEL
  Claude API          ANTHROPIC_API_KEY; optional CHAT_MODEL
optional for Claude: CHAT_EFFORT.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable
from urllib.parse import urlparse

import anthropic
import openai

from charts import CHART_TYPES, from_rows
from idp_flow import IdpFlow
from mongo_db import MongoMetadataClient

MODEL = os.getenv("CHAT_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("CHAT_EFFORT", "medium")
FALLBACK_MODEL = os.getenv("CHAT_FALLBACK_MODEL", "").strip()
USE_AZURE_OPENAI = bool(os.getenv("AZURE_OPENAI_API_KEY"))
USE_FOUNDRY = not USE_AZURE_OPENAI and bool(os.getenv("ANTHROPIC_FOUNDRY_API_KEY"))
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
MAX_TURNS = 15               # model <-> tool round trips per question
MAX_RESULT_CHARS = 40_000    # per tool result, keeps the context small
MAX_CHARTS = 4

SYSTEM_PROMPT = """You are the analytics assistant for Actuvara's IDP (intelligent document processing) platform.
You answer questions about the data in its MongoDB database (Azure Cosmos DB for MongoDB vCore) by calling the
read-only tools you have. You can read data; you cannot change it - if asked to, say this assistant is read-only.

Ground every statement in tool results from this conversation. Never guess a count, name, id, date or field;
if the data doesn't answer the question, say so and say what you checked.

How the IDP data fits together:
  submission  emails | webhooks | manual_extractions   (email trigger / webhook trigger / manual upload)
    -> files  files.source_email_id | source_webhook_id | source_manual_extraction_id
      -> runs  extraction_results (one per file x process; retries add runs). Fields: status, file_id,
               proccess_id (sic), created_at, completed_at, confidence_score, total_processing_time_ms,
               email_id | webhook_id | manual_extraction_id
        -> nodes  file_process_tracker (one row per workflow node; extraction_result_id, node_id, status)
  process names: processes.name; workflow node labels: processes.workflow.nodes[].label
  received dates: emails.date_received, webhooks.received_at, manual_extractions.uploaded_at; files.uploaded_at
For questions about a specific submission, file or run use the idp_* tools. For counts, trends and breakdowns
use run_aggregate. If you are unsure of a field name or its type, check with infer_collection_schema or
get_distinct_values before building a pipeline - do not assume. Dates are BSON dates unless a schema says otherwise.

Charts: whenever the answer contains numbers that compare, rank, break down or trend (counts by status, per day,
per process, top N, shares), call create_chart with an aggregation pipeline that produces exactly those numbers -
usually 1 chart, at most 3, each showing something different. Pick the chart type by the data's job: line for change
over time (sort by date ascending), bar for comparing categories, hbar for ranked lists or long labels, doughnut for
parts of a whole with at most 6 parts, kpi for one headline number, table for row-level detail (ids, names, dates).
Do not chart a single yes/no or a single record. Charts appear below your text automatically.

Answer format: start with the direct answer in one or two sentences, then any short supporting detail in Markdown.
Do not repeat every number a chart shows - mention the key ones. Keep ids exactly as returned.
"""


def _log(msg: str) -> None:
    print(f"[actuvara-chat] {msg}", file=sys.stderr, flush=True)


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}

TOOLS: list[dict[str, Any]] = [
    {"name": "list_collections", "description": "List collections (MongoDB's tables) with their approximate document counts.",
     "input_schema": _schema({}, [])},
    {"name": "infer_collection_schema",
     "description": "Field paths and types found in a sample of a collection's documents, with how often each appears.",
     "input_schema": _schema({"collection": S, "sample_size": I}, ["collection"])},
    {"name": "get_distinct_values",
     "description": "Distinct values of one field with document counts - use for status/type/category fields.",
     "input_schema": _schema({"collection": S, "field_path": S, "limit": I}, ["collection", "field_path"])},
    {"name": "count_documents",
     "description": 'Number of documents in a collection, optionally matching a JSON filter string, e.g. \'{"status": "failed"}\'.',
     "input_schema": _schema({"collection": S, "filter": S}, ["collection"])},
    {"name": "run_find",
     "description": "Read documents with one find(). filter, projection and sort are JSON strings "
                    '(MongoDB Extended JSON accepted, e.g. {"_id": {"$oid": "..."}}). Always project only the fields you need.',
     "input_schema": _schema({"collection": S, "filter": S, "projection": S, "sort": S, "max_rows": I}, ["collection"])},
    {"name": "run_aggregate",
     "description": "Run one read-only aggregation pipeline given as a JSON array string. $out, $merge and "
                    "server-side JavaScript are rejected. Dates in $match: {\"$date\": \"2026-01-01T00:00:00Z\"}.",
     "input_schema": _schema({"collection": S, "pipeline": S, "max_rows": I}, ["collection", "pipeline"])},
    {"name": "get_inferred_relationships",
     "description": "Likely links between collections, inferred from '<name>_id' fields and checked on a sample.",
     "input_schema": _schema({"collection": S}, [])},
    {"name": "idp_find_submissions",
     "description": "List IDP submissions newest first across email, webhook and manual uploads, with file and run counts. "
                    "source: email | webhook | manual_upload (empty = all); status: the submission's status; "
                    "search: text in subject/sender/claim or policy number; days: last N days (0 = any).",
     "input_schema": _schema({"source": S, "status": S, "search": S, "days": I, "limit": I}, [])},
    {"name": "idp_get_submission",
     "description": "One submission (or the submission of a file id / run id): details, files, and per file its runs with "
                    "node progress, current step and failed / awaiting-approval nodes.",
     "input_schema": _schema({"submission_id": S, "include_nodes": B}, ["submission_id"])},
    {"name": "idp_get_run_details",
     "description": "One run (extraction_results id): every workflow node in order with status, timing, errors and approvals.",
     "input_schema": _schema({"run_id": S, "include_extracted_data": B}, ["run_id"])},
    {"name": "create_chart",
     "description": "Attach a chart to your answer. The pipeline runs on `collection` and each output row becomes one "
                    "point: x_field gives the label (category or date string), y_fields the numeric values (one series "
                    "each). Sort the pipeline output the way the chart should read. For kpi, the pipeline returns one row "
                    "and y_fields[0] is the value. For table, x_field and y_fields are the columns in order. The result "
                    "returns the rows that were charted.",
     "input_schema": _schema({
         "title": {"type": "string", "description": "Short title that says what is measured, e.g. 'Failed runs per day'"},
         "chart_type": {"type": "string", "enum": list(CHART_TYPES)},
         "collection": S,
         "pipeline": {"type": "string", "description": "JSON array of aggregation stages"},
         "x_field": {"type": "string", "description": "Field of each output row used as the label, e.g. '_id' or 'day'"},
         "y_fields": {"type": "array", "items": {"type": "string"}},
         "series_names": {"type": "array", "items": {"type": "string"},
                          "description": "Human names for y_fields, same order (e.g. ['Runs'])"},
         "unit": {"type": "string", "description": "Optional unit shown with values, e.g. '%' or 's'"},
     }, ["title", "chart_type", "collection", "pipeline", "x_field", "y_fields"])},
]


def _make_client() -> tuple[Any, dict[str, Any]]:
    """The model client plus any extra per-request arguments it needs.
    Claude on Foundry has no server-side fallbacks, so there the SDK middleware retries a
    declined request on CHAT_FALLBACK_MODEL (a deployment that must exist in the same resource)."""
    if USE_AZURE_OPENAI:
        url = urlparse(os.getenv("AZURE_OPENAI_ENDPOINT", "").strip())
        if not url.scheme or not url.netloc:
            raise ValueError("Set AZURE_OPENAI_ENDPOINT in .env (e.g. https://<resource>.openai.azure.com/)")
        # Only the host is used: a Foundry project / agent / Target URI path ('/api/projects/...',
        # '/openai/deployments/...') pasted from the portal makes Azure reject the API version.
        endpoint = f"{url.scheme}://{url.netloc}/"
        return openai.AzureOpenAI(azure_endpoint=endpoint, api_key=os.environ["AZURE_OPENAI_API_KEY"],
                                  api_version=AZURE_API_VERSION, max_retries=2), {}
    if USE_FOUNDRY:
        middleware = ([anthropic.BetaRefusalFallbackMiddleware([{"model": FALLBACK_MODEL}])]
                      if FALLBACK_MODEL else None)
        # Reads ANTHROPIC_FOUNDRY_API_KEY and ANTHROPIC_FOUNDRY_RESOURCE / _BASE_URL.
        return anthropic.AnthropicFoundry(middleware=middleware), {}
    return anthropic.Anthropic(), {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


# Same tools in the OpenAI function-calling shape.
OPENAI_TOOLS = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in TOOLS]


class ChatAgent:
    def __init__(self, mongo: MongoMetadataClient) -> None:
        self.mongo = mongo
        self.client, self.fallback_args = _make_client()
        if USE_AZURE_OPENAI:
            _log(f"deployment {AZURE_DEPLOYMENT} via Azure OpenAI")
        else:
            _log(f"model {MODEL} via {'Microsoft Foundry' if USE_FOUNDRY else 'Claude API'}"
                 + (f", fallback {FALLBACK_MODEL}" if USE_FOUNDRY and FALLBACK_MODEL else ""))

    # --- tools -----------------------------------------------------------------
    def _handlers(self, charts: list[dict[str, Any]]) -> dict[str, Callable[..., Any]]:
        m = self.mongo
        idp = IdpFlow(m.database())

        def list_collections() -> Any:
            db = m.database()
            return [{"collection": c["collection"], "type": c["type"],
                     "approx_documents": db[c["collection"]].estimated_document_count()
                     if c["type"] == "collection" else None} for c in m.list_collections()]

        def create_chart(title: str, chart_type: str, collection: str, pipeline: str, x_field: str,
                         y_fields: list[str], series_names: list[str] | None = None, unit: str = "") -> Any:
            if len(charts) >= MAX_CHARTS:
                return {"error": f"at most {MAX_CHARTS} charts per answer"}
            rows = m.run_aggregate(collection, pipeline, None, 200)
            if not rows:
                return {"charted": False, "note": "The pipeline returned no rows, so no chart was added."}
            charts.append(from_rows(title, chart_type, rows, x_field, y_fields, series_names, unit))
            return {"charted": True, "row_count": len(rows), "rows": rows[:50]}

        return {
            "list_collections": list_collections,
            "infer_collection_schema": lambda collection, sample_size=100:
                m.infer_collection_schema(collection, None, sample_size),
            "get_distinct_values": lambda collection, field_path, limit=50:
                m.get_distinct_values(collection, field_path, None, limit),
            "count_documents": lambda collection, filter="": m.count_documents(collection, None, filter),
            "run_find": lambda collection, filter="", projection="", sort="", max_rows=50:
                m.run_find(collection, filter, projection, sort, None, max_rows),
            "run_aggregate": lambda collection, pipeline, max_rows=100:
                m.run_aggregate(collection, pipeline, None, max_rows),
            "get_inferred_relationships": lambda collection="":
                m.get_inferred_relationships(collection, None, verify=True),
            "idp_find_submissions": lambda source="", status="", search="", days=0, limit=20:
                idp.find_submissions(source, status, search, days, limit),
            "idp_get_submission": lambda submission_id, include_nodes=False:
                idp.get_submission(submission_id, include_nodes),
            "idp_get_run_details": lambda run_id, include_extracted_data=False:
                idp.get_run_details(run_id, include_extracted_data, False),
            "create_chart": create_chart,
        }

    @staticmethod
    def _result_text(value: Any) -> str:
        text = json.dumps(value, default=str, ensure_ascii=False)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f'... [truncated: {len(text)} chars total - narrow the query]'
        return text

    # --- conversation ----------------------------------------------------------
    def answer(self, history: list[dict[str, str]]) -> dict[str, Any]:
        """history: [{"role": "user" | "assistant", "content": str}, ...] ending with the user's question.
        Returns {"answer": markdown, "charts": [spec], "steps": [{"tool", "input", "ok"}]}."""
        messages: list[dict[str, Any]] = [{"role": h["role"], "content": h["content"]}
                                          for h in history if h.get("content")]
        charts: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        handlers = self._handlers(charts)
        if USE_AZURE_OPENAI:
            return self._loop_openai(messages, charts, steps, handlers)
        # Pins this question's follow-up requests to whichever model accepted (Foundry middleware).
        with anthropic.BetaFallbackState():
            return self._loop(messages, charts, steps, handlers)

    def _run_tool(self, name: str, args: dict[str, Any], handlers: dict[str, Callable[..., Any]],
                  steps: list[dict[str, Any]]) -> tuple[str, bool]:
        fn = handlers.get(name)
        try:
            if fn is None:
                raise ValueError(f"unknown tool {name}")
            content, is_error = self._result_text(fn(**args)), False
        except Exception as ex:
            content, is_error = f"{type(ex).__name__}: {ex}", True
            _log(f"{name} failed: {content}")
        steps.append({"tool": name, "input": args, "ok": not is_error})
        return content, is_error

    def _loop_openai(self, messages: list[dict[str, Any]], charts: list[dict[str, Any]],
                     steps: list[dict[str, Any]], handlers: dict[str, Callable[..., Any]]) -> dict[str, Any]:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
        for _ in range(MAX_TURNS):
            response = self.client.chat.completions.create(
                model=AZURE_DEPLOYMENT, messages=msgs, tools=OPENAI_TOOLS, temperature=0, max_tokens=8000)
            choice = response.choices[0]
            msg = choice.message
            if choice.finish_reason == "content_filter":
                return {"answer": "I can't help with that request.", "charts": charts, "steps": steps}
            if not msg.tool_calls:
                text = msg.content or ""
                if choice.finish_reason == "length":
                    text += "\n\n_(The answer was cut off - try a narrower question.)_"
                return {"answer": text.strip(), "charts": charts, "steps": steps}

            msgs.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                    content, _ = self._run_tool(call.function.name, args, handlers, steps)
                except json.JSONDecodeError as ex:
                    content = f"Invalid JSON arguments: {ex}"
                msgs.append({"role": "tool", "tool_call_id": call.id, "content": content})

        return {"answer": "I couldn't finish within the step limit - try a more specific question.",
                "charts": charts, "steps": steps}

    def _loop(self, messages: list[dict[str, Any]], charts: list[dict[str, Any]],
              steps: list[dict[str, Any]], handlers: dict[str, Callable[..., Any]]) -> dict[str, Any]:
        for _ in range(MAX_TURNS):
            with self.client.beta.messages.stream(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                **self.fallback_args,
            ) as stream:
                response = stream.get_final_message()

            if response.stop_reason == "refusal":
                return {"answer": "I can't help with that request.", "charts": charts, "steps": steps}

            text = "".join(b.text for b in response.content if b.type == "text")
            if response.stop_reason != "tool_use":
                if response.stop_reason == "max_tokens":
                    text += "\n\n_(The answer was cut off - try a narrower question.)_"
                return {"answer": text.strip(), "charts": charts, "steps": steps}

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                content, is_error = self._run_tool(block.name, dict(block.input), handlers, steps)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content,
                                "is_error": is_error})
            messages.append({"role": "user", "content": results})

        return {"answer": "I couldn't finish within the step limit - try a more specific question.",
                "charts": charts, "steps": steps}
