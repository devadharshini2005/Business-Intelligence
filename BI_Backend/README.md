# Actuvara DB – MCP Server (Azure Cosmos DB for MongoDB vCore)

A **read-only MCP server** that lets GitHub Copilot (or any MCP client) explore the Actuvara
database on **Azure Cosmos DB for MongoDB (vCore)**: collections, indexes, document fields,
how collections relate – and the documents themselves.

**Reads only.** The server never calls insert, update, delete, drop or any other write.
Filters and pipelines are checked before they are sent: `$out` and `$merge` (the only ways a
read can write) and server-side JavaScript (`$where`, `$function`, `$accumulator`) are rejected.

Copilot is the AI; this server is only its toolbox. The MCP server itself has no HTTP API and no LLM.

The **BI API** (`api_server.py`) used by the Angular frontend in `../BI_Frontend` is an MCP *client* of
this server: it starts `mcp_server.py` and gets everything - dashboard, submission details, chatbot
answers and charts - through these MCP tools. See [BI API](#bi-api-for-the-angular-frontend).

## Files

| File | Purpose |
|---|---|
| `mongo_db.py` | Talks to MongoDB, read-only: collections, indexes/stats, inferred fields and relationships, find/aggregate |
| `idp_flow.py` | Actuvara IDP-specific tools: submission → files → runs → workflow nodes |
| `query_guard.py` | Parses JSON filters/pipelines and rejects write stages and server-side JavaScript |
| `mcp_server.py` | The MCP server: exposes the tools to Copilot over stdio |
| `api_server.py` | BI HTTP API for the Angular frontend - an MCP client of `mcp_server.py` |
| `chat_agent.py` | Chatbot: Azure OpenAI (gpt-5) calling the MCP tools, plus the checks every answer must pass |
| `dashboard.py` | Fixed read-only aggregations behind the `get_dashboard` tool |
| `charts.py` | Turns aggregation rows into chart specs (`build_chart`, dashboard) |
| `.vscode/mcp.json` | Registers the server with Copilot in VS Code |
| `.mcp.json` | Registers the same server with Claude Code |
| `.claude/settings.local.json` | Pre-approves that server in Claude Code (local, not shared) |
| `.env.example` | Template for your connection settings (copy to `.env`) |
| `tests/` | Guard, schema-helper and "no write tools" tests (no database needed) |

## Setup

### 1. Add your connection string

```powershell
copy .env.example .env
```

Open `.env` and set (no quotes needed, no trailing `;`):

```
MONGODB_URI=mongodb://<read-only-user>:<password>@<cluster>.mongocluster.cosmos.azure.com:10260/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false
MONGODB_DATABASE=intellidoc
```

**Use a read-only database user.** The code only ever reads, but the credential is what
enforces it at the database. `.env` is git-ignored – never commit it.

### 2. Install (PowerShell, from this folder)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Check it

```powershell
pytest -q                 # offline tests, no DB needed
python mcp_server.py      # starts and waits for an MCP client; Ctrl+C to stop
```

### 4. Use it from Copilot

1. Open **this folder** (`actuvara-db`) as the VS Code workspace.
2. Open `.vscode/mcp.json` and click **Start** (or **Restart**) above `actuvara-cosmos-db`.
3. In Copilot Chat, switch to **Agent** mode and ask, e.g. *"Show the documents in access_requests"*.

### 5. Use it from Claude Code

Claude Code reads `.mcp.json` in this folder (Copilot reads `.vscode/mcp.json`; both start
the same `mcp_server.py`, so they share one implementation and one `.env`).

1. Open **this folder** in Claude Code (VS Code extension or `claude` in a terminal started here).
2. Start a **new** Claude Code session. `.claude/settings.local.json` pre-approves the
   `actuvara-cosmos-db` server; otherwise approve it when prompted.
3. Check it with `/mcp` (should show `actuvara-cosmos-db` connected), then ask, e.g.
   *"Using actuvara-cosmos-db, show the documents in access_requests"*.

## Tools

| Tool | What it answers |
|---|---|
| `get_database_overview` | Everything at once: every collection, its document count, fields/types, and relationships |
| `ping_db`, `server_info` | Can we connect? Which hosts, which server version? |
| `list_databases`, `list_collections` | What's on the cluster / in the database? |
| `find_collections_like`, `collection_exists` | Find a collection by partial or exact name |
| `get_collection_details`, `list_indexes` | Options, validator, indexes, size stats |
| `infer_collection_schema` | Fields, types and how often each appears (sampled) |
| `find_fields_like` | Which collections have a field like "email"? |
| `field_exists` | Exact count of documents that have a field |
| `get_inferred_relationships` | Links between collections from `<name>_id` fields, checked on a sample and reported as a match % |
| `count_documents` | Documents in a collection, optionally matching a JSON filter |
| `get_distinct_values` | Distinct values of a field with counts (e.g. all `status` values) |
| `run_find` | Read documents: JSON `filter`, `projection`, `sort`, `max_rows` |
| `run_aggregate` | One read-only aggregation pipeline (JSON array) |
| `find_id` | Which collection(s) hold a document with a given `_id` |
| `build_chart` | Chart spec(s) built from one aggregation - every number comes from the data |
| `get_dashboard` | The IDP analytics dashboard (KPIs + charts) for the last N days |

## IDP submission tools (Actuvara / intellidoc)

How a submission is stored:

```
submission   emails | webhooks | manual_extractions        (email trigger / webhook trigger / manual upload)
  └─ files   files.source_email_id | source_webhook_id | source_manual_extraction_id
      └─ runs   extraction_results  (one per file × process; a retry adds a run)
          └─ nodes   file_process_tracker  (one row per workflow node, with status)
node names + order:  processes.workflow.nodes[].label / .edges
fetched documents:   files.metadata.parent_ref_id = run id (API connector nodes)
```

| Tool | Level | Returns |
|---|---|---|
| `idp_find_submissions` | list | Submissions (filter by source, status, text, last N days) with file / run counts and run status |
| `idp_get_submission` | collapsed tree | Submission details → files → runs with node progress (e.g. 9/11), current step and failed / awaiting-approval nodes. Accepts a submission, file or run id. `include_nodes=True` expands every run |
| `idp_get_run_details` | expanded run | Every node in workflow order: status, timing, outcome, errors, approval, fetched documents. Optional extracted data |

Example questions: *"Show the latest webhook submissions"*, *"What happened to submission 6abbb08c31e9b1852284e1ab?"*,
*"Expand the P&C Claims run"*, *"Which manual uploads failed this week?"*

## BI API (for the Angular frontend)

```powershell
python api_server.py          # http://127.0.0.1:8000 - starts mcp_server.py itself
```

Set `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` in `.env` (see `.env.example`); the chatbot uses
the `gpt-5` deployment unless `AZURE_OPENAI_DEPLOYMENT` says otherwise. **Don't** run `mcp_server.py`
for the app - `api_server.py` launches it as an MCP subprocess, exactly as Copilot does.

| Endpoint | MCP tool(s) |
|---|---|
| `GET /api/health` | `ping_db` |
| `GET /api/dashboard?days=30` | `get_dashboard` |
| `GET /api/submissions/{id}` | `idp_get_submission` |
| `POST /api/chat/stream` | the chatbot's tools (`run_aggregate`, `build_chart`, `idp_*`, ...) - server-sent events |

**How chat answers stay grounded.** Charts come only from `build_chart`, which runs the aggregation and
builds the chart from its rows. Before an answer is shown it is checked: its figures must appear in the tool
results and come with charts (a single number needs breakdowns), "none found" must not rest on empty results,
and ids must exist (`find_id`). An answer that fails is sent back to the model (at most twice); figures that
still can't be verified are flagged in the answer.
