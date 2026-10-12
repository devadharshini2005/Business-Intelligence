"""Chatbot over the Actuvara database. Azure OpenAI (gpt-5 by default) answers questions by calling the
tools of the MCP server (mcp_server.py) - the same read-only tools Copilot and Claude Code use - and
attaches charts that build_chart makes from real query results.

Every answer is checked before it is accepted: figures must come from a query, appear in the tool results
and carry a chart; "there is none" must not rest only on empty results; ids must exist. A failing answer is
sent back to the model (at most MAX_CORRECTIONS times).

.env: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, optional AZURE_OPENAI_DEPLOYMENT (gpt-5),
AZURE_OPENAI_API_VERSION, AZURE_OPENAI_REASONING_EFFORT (low | medium | high).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from typing import Any, Callable
from urllib.parse import urlparse

import openai
from mcp import ClientSession

from charts import run_steps_table, submission_table

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
REASONING = DEPLOYMENT.lower().startswith(("gpt-5", "o1", "o3", "o4"))  # no temperature; max_completion_tokens
REASONING_EFFORT = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "low")
MAX_TURNS, MAX_CORRECTIONS, MAX_CHARTS, MAX_RESULT_CHARS = 15, 2, 4, 40_000

# MCP tools the chatbot may use (admin / heavy ones are left to Copilot).
CHAT_TOOLS = {"list_collections", "infer_collection_schema", "get_distinct_values", "count_documents", "run_find",
              "run_aggregate", "find_fields_like", "get_inferred_relationships", "find_id", "idp_find_submissions",
              "idp_get_submission", "idp_get_run_details", "build_chart"}
DATA_TOOLS = {"run_aggregate", "run_find", "count_documents", "build_chart"}

SYSTEM_PROMPT = """You are the analytics assistant for Actuvara's IDP (intelligent document processing) platform. You answer
questions about its MongoDB database with read-only tools. You cannot change data - if asked to, say so.

Data model:
  submission  emails | webhooks | manual_extractions   (email trigger / webhook trigger / manual upload)
    -> files  files.source_email_id | source_webhook_id | source_manual_extraction_id
      -> runs  extraction_results: status, file_id, proccess_id (sic), created_at, completed_at, confidence_score
               (0-1), total_processing_time_ms, email_id | webhook_id | manual_extraction_id
        -> nodes  file_process_tracker (one row per workflow step: extraction_result_id, node_id, status)
  processes.name; received: emails.date_received, webhooks.received_at, manual_extractions.uploaded_at
  platform users: app_users; logins: app_sessions (name, email, created_at = login time); system_logs (action "Login")
Definitions - use them consistently and say which one you counted:
  files processed by a process = DISTINCT file_id in extraction_results for its proccess_id;
  runs = extraction_results documents; submissions = emails + webhooks + manual_extractions;
  when a file/run was processed = extraction_results.created_at (completed_at only if asked about completion).
Rules:
- Every number you state must come from a tool result in this conversation; never estimate, count lists or add up
  yourself - compute with $count / $sum / $group. List results carry row_count.
- Never invent ids. Find a process by name first: {"name": {"$regex": "<words>", "$options": "i"}} on processes,
  then filter extraction_results by proccess_id {"$oid": ...}. If nothing matches, list the available names.
- If unsure of a field or value, check with infer_collection_schema / get_distinct_values first.
- For one submission, file, run or step id call idp_get_submission first (any of these ids works), then
  idp_get_run_details for a run's steps; find_id tells what an unknown id is. These two idp tools attach a table
  themselves. If a submission record is reported deleted, say so and still describe its files and runs.
Charts: answers with numbers MUST have charts from build_chart (they appear below your text). Make 2-3 charts that
each show something different: a single number is a kpi PLUS breakdowns that explain it (trend per day/week, by
status, by type, by source, top items). Types: line = over time (sort by date; $match the date field
{"$type": "date"}; per day "%Y-%m-%d" under ~2 months, per week "%G-W%V" under ~6, else per month - at least 5
points), bar = categories, hbar = rankings / long labels, doughnut = parts of a whole (<= 6), kpi = one number,
table = row detail. One line/bar per category: long rows {day, source, n} + series_field="source". Compare
collections with $unionWith. Label with names, not ids: after grouping by proccess_id add {"$lookup": {"from":
"processes", "localField": "_id", "foreignField": "_id", "as": "p"}}, {"$set": {"name": {"$ifNull": [{"$first":
"$p.name"}, "Unknown / deleted process"]}}}. Confidence as % (x100, unit "%"). Never mix units in one chart.
If a tool returns an error, fix the call and retry.
Answer: the direct answer in 1-2 sentences, then short Markdown detail; read each value next to its own label.
Last line, exactly: FOLLOW_UPS: <question> | <question> | <question>   (2-3 follow-ups answerable from this data)
"""


IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


def system_prompt() -> str:
    """Instructions + today's date. Users are in India, so 'today' is the IST day (dates are stored in UTC)."""
    now = dt.datetime.now(IST)
    utc = lambda d: d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (SYSTEM_PROMPT + f"\nNow: {now:%A %d %B %Y, %H:%M} IST (India). Dates are stored in UTC, so use these "
            f'boundaries: today = {{"$gte": {{"$date": "{utc(today)}"}}}}, yesterday from '
            f"{utc(today - dt.timedelta(days=1))}, last 7 days from {utc(today - dt.timedelta(days=7))}, last 30 days "
            f"from {utc(today - dt.timedelta(days=30))}. Show times in IST ($dateToString with timezone \"+05:30\"). "
            f"Never use another year.\n")


def _log(msg: str) -> None:
    print(f"[actuvara-chat] {msg}", file=sys.stderr, flush=True)


# --- answer checks ---------------------------------------------------------------------------------------------
_IDS_AND_DATES = re.compile(r"\b[0-9a-f]{24}\b|\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?\b|FOLLOW_UPS:.*", re.I | re.S)
_HEX_ID = re.compile(r"\b[0-9a-f]{24}\b", re.I)
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_PERIOD = re.compile(r"\s*(?:days?|weeks?|months?|years?|hours?|minutes?)\b", re.I)


def ids_in(value: Any) -> set[str]:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return {i.lower() for i in _HEX_ID.findall(text)}


def split_follow_ups(text: str) -> tuple[str, list[str]]:
    """Strip the trailing 'FOLLOW_UPS: a | b' line from an answer."""
    lines = text.rstrip().splitlines()
    for i in range(len(lines) - 1, max(len(lines) - 4, -1), -1):
        line = lines[i].strip().strip("*_` ")
        if line.upper().startswith("FOLLOW_UPS:"):
            qs = [q.strip(" -*_`") for q in line[len("FOLLOW_UPS:"):].split("|")]
            return "\n".join(lines[:i]).rstrip(), [q for q in qs if q][:3]
    return text.strip(), []


def is_empty(result: Any) -> bool:
    """No rows, only a row of zeros ($count over nothing on Cosmos DB), count 0, or nothing charted."""
    if not isinstance(result, dict):
        return False
    if "charts" in result:
        return not result["charts"]
    if "document_count" in result:
        return not result["document_count"]
    rows = result.get("rows")
    if rows is None:
        return False
    zero_row = len(rows) == 1 and isinstance(rows[0], dict) and any(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in rows[0].values()) and all(
        v == 0 for k, v in rows[0].items() if k != "_id" and isinstance(v, (int, float)) and not isinstance(v, bool))
    return not rows or zero_row


def unverified_numbers(text: str, sources: list[str]) -> list[str]:
    """Figures in the answer that no tool result (or the question) contains, allowing for 1,234 formatting,
    rounding, 0.366 shown as 36.6% and a % of two results. Whole numbers <= 12 and periods are not checked."""
    tokens = set(_NUMBER.findall("\n".join(sources)))
    values = [float(t.replace(",", "")) for t in list(tokens)[:3000]]
    small = sorted({abs(v) for v in values if v})[:150]
    ratios = {round(100 * a / b, 1) for a in small for b in small if a <= b}
    clean, bad = _IDS_AND_DATES.sub(" ", text), []
    for m in _NUMBER.finditer(clean):
        tok = m.group()
        n = float(tok.replace(",", ""))
        if tok in tokens or _PERIOD.match(clean, m.end()) or (n.is_integer() and n <= 12):
            continue
        near = lambda v: abs(n - v) <= max(0.051, 0.0051 * abs(v))  # noqa: E731
        if not (any(near(v) or near(v * 100) for v in values) or round(n, 1) in ratios):
            bad.append(tok)
    return list(dict.fromkeys(bad))


def answer_problem(text: str, steps: list[dict[str, Any]], charts: list[dict[str, Any]],
                   sources: list[str]) -> str | None:
    """Why a final answer can't be accepted yet (sent back to the model), or None."""
    data = [s for s in steps if s["tool"] in DATA_TOOLS and s["ok"]]
    if data and all(s.get("empty") for s in data) and not charts:
        return ("Every query returned no data - don't conclude there is none yet; the filter is probably wrong. Look "
                "up processes by name (case-insensitive) and filter by proccess_id, check values with "
                "get_distinct_values, compare dates as dates. Query again, then answer.")
    if not re.search(r"\d", _IDS_AND_DATES.sub("", text)):
        return None
    if not any(s["ok"] for s in steps):
        return "Your answer has figures but you queried nothing. Query the data now and use only the results."
    if not charts:
        return "Your answer has figures but no chart. Call build_chart with the data behind them, then answer."
    thin = [c["title"] for c in charts if c["type"] == "line" and len(c.get("labels") or []) < 3]
    if thin:
        return (f"The trend '{thin[0]}' has fewer than 3 points. Make it per day or per week instead, with a title "
                f"naming the grain; the old chart is removed automatically.")
    if all(c["type"] == "kpi" for c in charts):
        return ("Only a headline number is attached. Add 1-2 breakdown charts that explain it (trend over time, by "
                "status, by type, by source or top items), then answer.")
    bad = unverified_numbers(text, sources)
    if bad:
        return (f"These figures are not in any tool result: {', '.join(bad)}. Get every number from a query "
                f"($count / $sum / $group) and state only numbers the results contain.")
    return None


# --- agent -----------------------------------------------------------------------------------------------------
async def call_tool(session: ClientSession, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
    """Call an MCP tool and return (result as JSON data, is_error)."""
    res = await session.call_tool(name, args)
    text = "".join(c.text for c in res.content if getattr(c, "type", "") == "text")
    data = res.structuredContent
    if data is None:
        try:
            data = json.loads(text)
        except ValueError:
            data = text
    if isinstance(data, dict) and set(data) == {"result"}:  # FastMCP wraps non-object returns
        data = data["result"]
    error = res.isError or (isinstance(data, dict) and "error" in data)
    return (data.get("error", text) if isinstance(data, dict) and error else data), bool(error)


class ChatAgent:
    def __init__(self, session: ClientSession) -> None:
        self.mcp = session
        url = urlparse(os.getenv("AZURE_OPENAI_ENDPOINT", "").strip())
        if not url.scheme or not url.netloc:
            raise ValueError("Set AZURE_OPENAI_ENDPOINT in .env (e.g. https://<resource>.openai.azure.com/)")
        # Only the host: a Foundry project / agent path pasted from the portal is rejected by the API.
        self.llm = openai.AsyncAzureOpenAI(azure_endpoint=f"{url.scheme}://{url.netloc}/",
                                           api_key=os.environ["AZURE_OPENAI_API_KEY"], api_version=API_VERSION)
        self._tools: list[dict[str, Any]] | None = None
        _log(f"deployment {DEPLOYMENT} via Azure OpenAI, tools from the MCP server")

    async def tools(self) -> list[dict[str, Any]]:
        if self._tools is None:
            listed = (await self.mcp.list_tools()).tools
            self._tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                              "parameters": t.inputSchema}}
                           for t in listed if t.name in CHAT_TOOLS]
        return self._tools

    async def call(self, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
        """Call one of the chatbot's MCP tools; returns (result, is_error)."""
        if name not in CHAT_TOOLS:
            return f"unknown tool {name}", True
        return await call_tool(self.mcp, name, args)

    async def unknown_ids(self, args: dict[str, Any], known: set[str]) -> list[str]:
        """Ids in a query that were never seen in the chat or a tool result and don't exist (invented)."""
        missing = []
        for i in ids_in(args) - known:
            found, _ = await self.call("find_id", {"id": i})
            if isinstance(found, dict) and found.get("rows"):
                known.add(i)
            else:
                missing.append(i)
        return missing

    async def answer(self, history: list[dict[str, str]],
                     emit: Callable[[str, Any], None] = lambda *_: None) -> dict[str, Any]:
        """history ends with the user's question. emit(event, data) reports ("step", ...) / ("chart", ...) live.
        Returns {"answer": markdown, "charts": [...], "steps": [...], "follow_ups": [...]}."""
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system_prompt()},
                                      *({"role": h["role"], "content": h["content"]} for h in history if h["content"])]
        charts: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        sources = [h["content"] for h in history if h["role"] == "user"]  # what figures are checked against
        known = ids_in([h["content"] for h in history])
        corrections, text = 0, "I couldn't finish within the step limit - try a more specific question."

        def attach(spec: dict[str, Any], replaces: str = "") -> None:
            title = replaces or spec["title"]
            charts[:] = [c for c in charts if c["title"] not in (title, spec["title"])
                         and not c["title"].startswith(title + " - ")]
            if len(charts) < MAX_CHARTS:
                charts.append(spec)
                emit("chart", spec)

        for _ in range(MAX_TURNS):
            kw = ({"max_completion_tokens": 16000, "reasoning_effort": REASONING_EFFORT} if REASONING
                  else {"temperature": 0, "max_tokens": 8000})
            choice = (await self.llm.chat.completions.create(
                model=DEPLOYMENT, messages=msgs, tools=await self.tools(), **kw)).choices[0]
            msg = choice.message
            if choice.finish_reason == "content_filter":
                text = "I can't help with that request."
                break
            if not msg.tool_calls:
                text = msg.content or ""
                problem = answer_problem(text, steps, charts, sources) if choice.finish_reason != "length" else None
                if problem and corrections < MAX_CORRECTIONS:
                    corrections += 1
                    _log(f"answer sent back: {problem[:70]}")
                    msgs += [{"role": "assistant", "content": text}, {"role": "system", "content": problem}]
                    continue
                if choice.finish_reason == "length":
                    text += "\n\n_(The answer was cut off - try a narrower question.)_"
                break

            msgs.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    invented = await self.unknown_ids(args, known) if name in DATA_TOOLS else []
                    if invented:
                        result, error = (f"id {', '.join(invented)} does not exist and was not returned by any tool. "
                                         f"Never invent ids - look them up first."), True
                    else:
                        result, error = await self.call(name, args)
                except ValueError as ex:
                    args, result, error = {}, f"Invalid arguments: {ex}", True
                if not error:
                    known |= ids_in(result)
                    self._auto_charts(name, args, result, attach)
                content = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
                if len(content) > MAX_RESULT_CHARS:
                    content = content[:MAX_RESULT_CHARS] + "... [truncated - narrow the query]"
                if error:
                    _log(f"{name} failed: {content[:200]}")
                else:
                    sources.append(content)
                    if name in ("idp_get_submission", "idp_get_run_details", "list_collections"):
                        content += "\n(A table/chart of this result is attached to the answer automatically.)"
                step = {"tool": name, "input": args, "ok": not error}
                if name in DATA_TOOLS and not error:
                    step["empty"] = is_empty(result)
                steps.append(step)
                emit("step", step)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": content})

        # A superseded trend with < 3 points is noise once other charts exist.
        charts = [c for c in charts if not (c["type"] == "line" and len(c.get("labels") or []) < 3)] or charts
        answer, follow_ups = split_follow_ups(text)
        bad = unverified_numbers(answer, sources) if steps else []
        if bad:
            answer += f"\n\n> ⚠ Could not verify {', '.join(bad)} against the query results - check the charts."
        return {"answer": answer, "charts": charts, "steps": steps, "follow_ups": follow_ups}

    @staticmethod
    def _auto_charts(name: str, args: dict[str, Any], result: Any, attach: Callable[..., None]) -> None:
        """Charts that come with a tool result: build_chart's specs, and tables / counts for lookups."""
        if name == "build_chart":
            for i, spec in enumerate(result.get("charts", [])):
                attach(spec, replaces=args.get("title", "") if i == 0 else "")  # a remade chart replaces the old one
        elif name == "idp_get_submission":
            attach(submission_table(result))
        elif name == "idp_get_run_details":
            attach(run_steps_table(result))
        elif name == "list_collections":
            top = sorted(result["rows"], key=lambda r: -(r.get("approx_documents") or 0))[:15]
            attach({"title": "Collections in the database", "type": "kpi", "value": result["row_count"]})
            attach({"title": "Largest collections (documents)", "type": "hbar", "labels": [r["collection"] for r in top],
                    "series": [{"name": "Documents", "data": [r.get("approx_documents") for r in top]}]})
