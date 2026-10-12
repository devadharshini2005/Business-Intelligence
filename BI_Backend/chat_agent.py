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

import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anthropic
import openai
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from bi_analytics import metric_rows
from charts import CHART_TYPES, from_rows

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

Charts: for the common analytics - runs by status, runs by process, submissions by source, failing workflow nodes,
submissions or runs per day - ALWAYS use chart_metric: its numbers come from the dashboard's tested queries and are
labelled with real names. Use create_chart only for anything else.
Whenever the answer contains numbers that compare, rank, break down or trend (counts by status, per day,
per process, top N, shares), call chart_metric or create_chart with data that produces exactly those numbers -
usually 1 chart, at most 3, each showing something different. Pick the chart type by the data's job: line for change
over time (sort by date ascending), bar for comparing categories, hbar for ranked lists or long labels, doughnut for
parts of a whole with at most 6 parts, kpi for one headline number, table for row-level detail (ids, names, dates).
Do not chart a single yes/no or a single record. Charts appear below your text automatically.
If the user asks for a specific chart type ("pie chart", "bar chart", "line chart"), use exactly that type (pie for
"pie", bar for "bar" or "column", hbar for "horizontal bar"), and if they ask for more than one chart, make each one.
The app colours each category of a pie or single-series bar chart differently, so one series is enough.
Label charts and answers with names, never raw ids when a name exists. For processes, after grouping by
"$proccess_id" add {"$lookup": {"from": "processes", "localField": "_id", "foreignField": "_id", "as": "p"}},
{"$project": {"_id": 0, "name": {"$ifNull": [{"$first": "$p.name"}, {"$toString": "$_id"}]}, "n": 1}} and chart x_field
"name". Likewise use emails.subject / webhooks.reference_subject / files.filename instead of ids where it helps.
Only mention a chart in your answer if a chart tool returned "charted": true; if one failed or found no data, say so.

Every number, name or id in an answer must come from a tool you called while answering THIS question - earlier
answers in the conversation may be wrong, so look again. Never say a value came from a tool you did not call.

Counting: never count items in a list yourself - you will miscount long lists. Take every number from a field
the tools return: row_count (list results), document_count, collection_count, or a $count / $group / $sum query you
run. "How many collections" = row_count of list_collections; "how many X" = count_documents or an aggregation.

Corrections: if the user says a number is wrong, re-check it with a tool before replying - do not simply agree.
If your earlier answer was wrong, say so plainly ("I miscounted - the correct number is 60") and give the checked
value. Never invent a reason for an error (e.g. "the database changed" or "the data was out of date") unless a tool
result shows it.

Answer format: start with the direct answer in one or two sentences, then any short supporting detail in Markdown.
Do not repeat every number a chart shows - mention the key ones. Keep ids exactly as returned.
"""


STALE_DATE_DAYS = 400  # a $date further back than this is flagged to the model


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_context(now: dt.datetime | None = None) -> str:
    """Today's date and ready-made window starts. The model has no clock: without this it
    computes "last 30 days" from its training-era sense of the date and filters on the wrong year."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).replace(microsecond=0)
    midnight = now.replace(hour=0, minute=0, second=0)
    windows = [
        ("last 24 hours", now - dt.timedelta(hours=24)),
        ("today", midnight),
        ("last 7 days", now - dt.timedelta(days=7)),
        ("last 30 days", now - dt.timedelta(days=30)),
        ("last 90 days", now - dt.timedelta(days=90)),
        ("this month", midnight.replace(day=1)),
        ("this year", midnight.replace(month=1, day=1)),
    ]
    lines = "\n".join(f'  {name}: {{"$gte": {{"$date": "{_iso(start)}"}}}}' for name, start in windows)
    return (f"CURRENT DATE: today is {now:%A %d %B %Y}; the time now is {_iso(now)} (UTC). Your own sense of the "
            "date is out of date - always compute relative periods (\"last 30 days\", \"this week\", \"yesterday\") "
            "from this date, never from memory. Ready-made $match bounds for date fields:\n"
            f"{lines}\n"
            "Use these exact values (or compute from today the same way), and say the date range you used in the "
            "answer, e.g. 'from 12 Sep 2026 to 12 Oct 2026'. For idp_find_submissions pass `days` instead.")


def _dates_in(value: Any) -> list[dt.datetime]:
    """Every {"$date": ...} literal inside a JSON string / dict / list from a tool call."""
    if isinstance(value, str):
        if '"$date"' not in value:
            return []
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    found: list[dt.datetime] = []
    if isinstance(value, dict):
        raw = value.get("$date")
        if isinstance(raw, str):
            try:
                found.append(dt.datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                pass
        elif isinstance(raw, (int, float)):
            found.append(dt.datetime.fromtimestamp(raw / 1000, dt.timezone.utc))
        for child in value.values():
            found += _dates_in(child)
    elif isinstance(value, list):
        for child in value:
            found += _dates_in(child)
    return found


def date_warning(args: dict[str, Any], now: dt.datetime | None = None) -> str | None:
    """A note for the model when a query filters on a date in the future or far in the past -
    the usual sign it guessed today's date instead of using the one it was given."""
    now = now or dt.datetime.now(dt.timezone.utc)
    odd = []
    for d in _dates_in([args.get(k) for k in ("pipeline", "filter")]):
        d = d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        if d > now + dt.timedelta(days=1):
            odd.append(f"{_iso(d)} is in the future")
        elif d < now - dt.timedelta(days=STALE_DATE_DAYS):
            odd.append(f"{_iso(d)} is {(now - d).days} days before today")
    if not odd:
        return None
    return (f"Check the date filter: {'; '.join(odd)} (today is {_iso(now.replace(microsecond=0))}). If the question "
            "is about a recent period, recompute the bound from today's date and run the query again; if the date is "
            "intended, carry on.")


def _log(msg: str) -> None:
    print(f"[actuvara-chat] {msg}", file=sys.stderr, flush=True)


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}

TOOLS: list[dict[str, Any]] = [
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


OPENAI_TOOLS = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in TOOLS]


class ChatAgent:
    def __init__(self) -> None:
        self.client, self.fallback_args = _make_client()
        if USE_AZURE_OPENAI:
            _log(f"deployment {AZURE_DEPLOYMENT} via Azure OpenAI")
        else:
            _log(f"model {MODEL} via {'Microsoft Foundry' if USE_FOUNDRY else 'Claude API'}"
                 + (f", fallback {FALLBACK_MODEL}" if USE_FOUNDRY and FALLBACK_MODEL else ""))

    @staticmethod
    def _result_text(value: Any) -> str:
        text = json.dumps(value, default=str, ensure_ascii=False)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + (f'... [truncated: {len(text)} chars total - only part of the rows are '
                                              'shown; row_count above is the full count. Narrow the query for details]')
        return text

    # --- conversation ----------------------------------------------------------
    def answer(self, history: list[dict[str, str]]) -> dict[str, Any]:
        """history: [{"role": "user" | "assistant", "content": str}, ...] ending with the user's question.
        Returns {"answer": markdown, "charts": [spec], "steps": [{"tool", "input", "ok"}]}."""
        return asyncio.run(self._answer_with_mcp(history))

    async def _answer_with_mcp(self, history: list[dict[str, str]]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": h["role"], "content": h["content"]}
                                          for h in history if h.get("content")]
        charts: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        warned: set[str] = set()  # tool calls already sent back once with a date warning
        server_path = Path(__file__).with_name("mcp_server.py")
        params = StdioServerParameters(command=sys.executable, args=[str(server_path)],
                                       cwd=str(server_path.parent))
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                mcp_tools = (await session.list_tools()).tools
                if USE_AZURE_OPENAI:
                    return await self._loop_openai(messages, charts, steps, warned, session, mcp_tools)
                # Pins this question's follow-up requests to whichever model accepted (Foundry middleware).
                with anthropic.BetaFallbackState():
                    return await self._loop(messages, charts, steps, warned, session, mcp_tools)

    @staticmethod
    def _mcp_value(result: Any) -> Any:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        texts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return texts[0]
        return texts

    async def _call_tool(self, name: str, args: dict[str, Any], charts: list[dict[str, Any]],
                         steps: list[dict[str, Any]], warned: set[str], session: ClientSession,
                         mcp_tool_names: set[str]) -> tuple[str, bool]:
        warning = date_warning(args)
        key = name + json.dumps(args, sort_keys=True, default=str)
        if warning and name == "create_chart" and key not in warned:
            warned.add(key)
            _log(f"date warning, chart held back: {warning}")
            result: Any = {"charted": False, "date_warning": warning,
                           "note": "Not charted yet. Fix the date and call again, or re-send this exact call "
                                   "if the date is intended."}
            steps.append({"tool": name, "input": args, "ok": True})
            return self._result_text(result), False
        try:
            if name == "create_chart":
                if len(charts) >= MAX_CHARTS:
                    value: Any = {"error": f"at most {MAX_CHARTS} charts per answer"}
                    is_error = True
                else:
                    result = await session.call_tool(
                        "run_aggregate",
                        {"collection": args["collection"], "pipeline": args["pipeline"], "max_rows": 200},
                    )
                    value = self._mcp_value(result)
                    is_error = result.isError or (isinstance(value, dict) and "error" in value)
                    if not is_error and (not isinstance(value, dict) or "rows" not in value):
                        raise RuntimeError("MCP run_aggregate returned an unexpected result")
                    rows = value.get("rows", []) if isinstance(value, dict) else []
                    if not is_error and rows:
                        charts.append(from_rows(args["title"], args["chart_type"], rows, args["x_field"],
                                                args["y_fields"], args.get("series_names"), args.get("unit", "")))
                        value = {"charted": True, "row_count": len(rows), "rows": rows[:50]}
                    elif not is_error:
                        value = {"charted": False, "note": "The pipeline returned no rows, so no chart was added."}
            elif name in mcp_tool_names:
                result = await session.call_tool(name, args)
                value = self._mcp_value(result)
                is_error = result.isError or (isinstance(value, dict) and "error" in value)
                if not is_error and not isinstance(value, dict):
                    raise RuntimeError(f"MCP tool {name} returned an unexpected result")
                if not is_error and name == "chart_metric":
                    chart_data = value
                    if len(charts) >= MAX_CHARTS:
                        value = {"error": f"at most {MAX_CHARTS} charts per answer"}
                        is_error = True
                    elif not chart_data.get("rows") or not any(
                        any(row.get(field) for field in chart_data["y_fields"]) for row in chart_data["rows"]
                    ):
                        value = {"charted": False, "note": "No data for this metric in the requested period.",
                                 "rows": chart_data.get("rows", [])}
                    else:
                        charts.append(from_rows(chart_data["title"], chart_data["chart_type"], chart_data["rows"],
                                                chart_data["x_field"], chart_data["y_fields"],
                                                chart_data["series_names"]))
                        value = {"charted": True, "row_count": len(chart_data["rows"]),
                                 "rows": chart_data["rows"][:50]}
            else:
                raise ValueError(f"unknown tool {name}")
            if warning:
                _log(f"date warning: {warning}")
                value = {"date_warning": warning, "result": value}
            content = self._result_text(value)
        except Exception as ex:
            content, is_error = f"{type(ex).__name__}: {ex}", True
            _log(f"{name} failed: {content}")
        steps.append({"tool": name, "input": args, "ok": not is_error})
        return content, is_error

    @staticmethod
    def _openai_tool_specs(mcp_tools: list[Any]) -> list[dict[str, Any]]:
        mcp_specs = [
            {"type": "function", "function": {
                "name": tool.name, "description": tool.description or "",
                "parameters": tool.inputSchema,
            }}
            for tool in mcp_tools
        ]
        return mcp_specs + OPENAI_TOOLS

    @staticmethod
    def _anthropic_tool_specs(mcp_tools: list[Any]) -> list[dict[str, Any]]:
        return [
            {"name": tool.name, "description": tool.description or "", "input_schema": tool.inputSchema}
            for tool in mcp_tools
        ] + TOOLS

    async def _loop_openai(self, messages: list[dict[str, Any]], charts: list[dict[str, Any]],
                           steps: list[dict[str, Any]], warned: set[str], session: ClientSession,
                           mcp_tools: list[Any]) -> dict[str, Any]:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + date_context()}, *messages]
        mcp_tool_names = {tool.name for tool in mcp_tools}
        tool_specs = self._openai_tool_specs(mcp_tools)
        for turn in range(MAX_TURNS):
            # First call of each question must use a tool: left to choose, GPT sometimes answers a data
            # question from memory (e.g. "13 collections" with no lookup) and cites a tool it never called.
            request_args: dict[str, Any] = {
                "model": AZURE_DEPLOYMENT,
                "messages": msgs,
                "tools": tool_specs,
                "tool_choice": "required" if turn == 0 else "auto",
            }
            if AZURE_DEPLOYMENT.lower().startswith("gpt-5"):
                request_args["max_completion_tokens"] = 8000
            else:
                request_args.update(temperature=0, max_tokens=8000)
            response = await asyncio.to_thread(self.client.chat.completions.create, **request_args)
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
                    content, _ = await self._call_tool(call.function.name, args, charts, steps, warned,
                                                       session, mcp_tool_names)
                except json.JSONDecodeError as ex:
                    content = f"Invalid JSON arguments: {ex}"
                msgs.append({"role": "tool", "tool_call_id": call.id, "content": content})

        return {"answer": "I couldn't finish within the step limit - try a more specific question.",
                "charts": charts, "steps": steps}

    async def _loop(self, messages: list[dict[str, Any]], charts: list[dict[str, Any]],
                    steps: list[dict[str, Any]], warned: set[str], session: ClientSession,
                    mcp_tools: list[Any]) -> dict[str, Any]:
        # The stable prompt first (cached), then today's date, which changes daily.
        system = [{"type": "text", "text": SYSTEM_PROMPT}, {"type": "text", "text": date_context()}]
        mcp_tool_names = {tool.name for tool in mcp_tools}
        tool_specs = self._anthropic_tool_specs(mcp_tools)
        for _ in range(MAX_TURNS):
            response = await asyncio.to_thread(self._anthropic_response, system, messages, tool_specs)

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
                content, is_error = await self._call_tool(block.name, dict(block.input), charts, steps, warned,
                                                          session, mcp_tool_names)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content,
                                "is_error": is_error})
            messages.append({"role": "user", "content": results})

        return {"answer": "I couldn't finish within the step limit - try a more specific question.",
                "charts": charts, "steps": steps}

    def _anthropic_response(self, system: list[dict[str, Any]], messages: list[dict[str, Any]],
                            tools: list[dict[str, Any]]) -> Any:
        with self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},
            **self.fallback_args,
        ) as stream:
            return stream.get_final_message()
