"""Actuvara MongoDB (Azure Cosmos DB for MongoDB vCore) read-only MCP server (stdio).

Copilot (or any MCP client) starts this process and calls its tools to learn
the structure of the Actuvara database - collections, indexes, inferred
document fields and inferred relationships - and to read documents with
find / aggregate. Nothing can be inserted, updated or deleted.

Run:  python mcp_server.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env from this project folder, whatever directory the client starts us
# from. override=True makes .env win over anything the client passed in, so a
# client that mangles the URI (e.g. the '$' in a password) can't break it.
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from idp_flow import IdpFlow  # noqa: E402
from mongo_db import MongoMetadataClient  # noqa: E402
from query_guard import QueryGuardError  # noqa: E402

MAX_ROWS = int(os.getenv("MCP_MAX_ROWS", "200"))


def _log(msg: str) -> None:
    # stdout carries the MCP protocol, so logs must go to stderr.
    print(f"[actuvara-mongo-mcp] {msg}", file=sys.stderr, flush=True)


_client: MongoMetadataClient | None = None


def _db() -> MongoMetadataClient:
    """Create the MongoDB client on first use, so the server still starts (and
    reports a clear error) when the connection string isn't filled in yet."""
    global _client
    if _client is None:
        _client = MongoMetadataClient()
    return _client


def _idp() -> IdpFlow:
    return IdpFlow(_db().database())


def _envelope(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        rows = [rows]
    total = len(rows)
    if total <= MAX_ROWS:
        return {"rows": rows, "row_count": total, "truncated": False}
    return {"rows": rows[:MAX_ROWS], "row_count": MAX_ROWS, "total_found": total,
            "truncated": True, "note": f"Showing first {MAX_ROWS} of {total} rows"}


def _err(ex: Exception) -> dict[str, Any]:
    if isinstance(ex, QueryGuardError):
        return {"error": str(ex)}
    return {"error": f"{type(ex).__name__}: {ex}"}


mcp = FastMCP(
    "actuvara-cosmos-db",
    instructions="\n".join([
        "Read-only server for the Actuvara database on Azure Cosmos DB for MongoDB (vCore).",
        "It can READ: structure (collections, fields, indexes, relationships) and data (run_find, "
        "run_aggregate, get_distinct_values, count_documents). It can NOT insert, update or delete - "
        "if asked to change data, say this server is read-only.",
        "Filters, projections, sorts and pipelines are JSON strings (MongoDB Extended JSON is accepted, "
        "e.g. {\"_id\": {\"$oid\": \"...\"}}). $out, $merge, $where, $function and $accumulator are rejected.",
        "Collections are MongoDB's equivalent of tables. There is no fixed schema and no foreign keys: "
        "fields are inferred by sampling and relationships from field names like 'policyId' (checked "
        "against a sample, reported as a match %). Say 'inferred' when reporting them.",
        "For the whole picture call get_database_overview. Otherwise: list_collections -> "
        "infer_collection_schema -> get_inferred_relationships -> run_find / run_aggregate for data.",
        "Pass `database` only when working outside the default database (MONGODB_DATABASE).",
        f"Row cap: {MAX_ROWS} per call.",
        "",
        "IDP SUBMISSIONS - for any question about a submission, its files, extraction or workflow/node "
        "status, use the idp_* tools instead of run_find: a submission is an email trigger (emails), "
        "webhook trigger (webhooks) or manual upload (manual_extractions); each has files; each file has "
        "one or more runs (extraction_results, one per process, retries add runs); each run has workflow "
        "nodes (file_process_tracker).",
        "Flow: idp_find_submissions (find the id) -> idp_get_submission (files -> runs with node progress "
        "and what needs attention) -> idp_get_run_details (every node, in workflow order). Any submission, "
        "file or run id works in idp_get_submission.",
        "Present a submission as a collapsed tree: the submission header, then one line per file, then one "
        "line per run (process, status, node progress, failed/awaiting nodes). Do NOT list every node unless "
        "asked; offer to expand a run, and use idp_get_run_details for it. Where the chat supports HTML, "
        "use <details><summary>...</summary>...</details> for each run so it opens like a dropdown.",
    ]),
)


# --- connectivity ------------------------------------------------------------
@mcp.tool()
async def ping_db() -> dict[str, Any]:
    """Check that the MongoDB cluster is reachable with the configured credentials."""
    try:
        return {"connected": _db().ping()}
    except Exception as ex:
        return {"connected": False, **_err(ex)}


@mcp.tool()
async def server_info() -> dict[str, Any]:
    """Cluster hosts, default database and server version."""
    try:
        return _db().server_info()
    except Exception as ex:
        return _err(ex)


# --- discovery ---------------------------------------------------------------
@mcp.tool()
async def list_databases() -> dict[str, Any]:
    """List the databases on the cluster."""
    try:
        return _envelope(_db().list_databases())
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def list_collections(database: str = "") -> dict[str, Any]:
    """List collections and views (MongoDB's equivalent of tables)."""
    try:
        return _envelope(_db().list_collections(database or None))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def find_collections_like(name_pattern: str, database: str = "") -> dict[str, Any]:
    """Find collections whose name contains a pattern (case-insensitive)."""
    try:
        return _envelope(_db().find_collections_like(name_pattern, database or None))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def collection_exists(collection: str, database: str = "") -> dict[str, Any]:
    """Check whether an exact collection name exists (empty rows = it doesn't)."""
    try:
        return _envelope(_db().collection_exists(collection, database or None))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def get_collection_details(collection: str, database: str = "") -> dict[str, Any]:
    """Options (validator, capped, view definition), indexes and size stats of a collection."""
    try:
        return _db().get_collection_details(collection, database or None)
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def list_indexes(collection: str, database: str = "") -> dict[str, Any]:
    """Indexes on a collection: keys, uniqueness and other options."""
    try:
        return _envelope(_db().list_indexes(collection, database or None))
    except Exception as ex:
        return _err(ex)


# --- inferred schema & relationships -----------------------------------------
@mcp.tool()
async def infer_collection_schema(collection: str, database: str = "", sample_size: int = 100) -> dict[str, Any]:
    """Field paths and types found in a random sample of documents, with how
    often each field appears. Use run_find to read the values."""
    try:
        return _envelope(_db().infer_collection_schema(collection, database or None, sample_size))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def find_fields_like(field_pattern: str, database: str = "", sample_size: int = 50) -> dict[str, Any]:
    """Find which collections have a field whose name contains a pattern
    (where a data point lives). Samples every collection, so it's slower."""
    try:
        return _envelope(_db().find_fields_like(field_pattern, database or None, sample_size))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def field_exists(collection: str, field_path: str, database: str = "") -> dict[str, Any]:
    """Exact check over the whole collection: how many documents have this
    field (dotted path, e.g. 'address.city')."""
    try:
        return _envelope(_db().field_exists(collection, field_path, database or None))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def get_inferred_relationships(collection: str = "", database: str = "", verify: bool = True) -> dict[str, Any]:
    """Likely links between collections, guessed from '<name>Id' fields. With
    verify=True each link is checked on a sample and reported as a match %
    (only the percentage is returned). Leave `collection` empty to scan all."""
    try:
        return _envelope(_db().get_inferred_relationships(collection, database or None, verify=verify))
    except Exception as ex:
        return _err(ex)


# --- read-only data access -----------------------------------------------------
@mcp.tool()
async def count_documents(collection: str, filter: str = "", database: str = "") -> dict[str, Any]:
    """Number of documents in a collection, optionally matching a JSON filter
    (e.g. '{"status": "open"}')."""
    try:
        return _db().count_documents(collection, database or None, filter)
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def get_distinct_values(collection: str, field_path: str, database: str = "", limit: int = 100) -> dict[str, Any]:
    """Distinct values of one field with how many documents have each -
    useful for status/type/category fields."""
    try:
        return _envelope(_db().get_distinct_values(collection, field_path, database or None, limit))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def run_find(
    collection: str, filter: str = "", projection: str = "", sort: str = "", database: str = "", max_rows: int = 100
) -> dict[str, Any]:
    """Read documents with one find() (the SELECT of MongoDB). Arguments are
    JSON strings, e.g. filter='{"status": "open"}', projection='{"name": 1, "_id": 0}',
    sort='{"created_at": -1}'. Leave filter empty to read all documents (up to max_rows)."""
    try:
        return _envelope(_db().run_find(collection, filter, projection, sort, database or None, max_rows))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def run_aggregate(collection: str, pipeline: str, database: str = "", max_rows: int = 100) -> dict[str, Any]:
    """Run one read-only aggregation pipeline given as a JSON array, e.g.
    '[{"$match": {"status": "open"}}, {"$group": {"_id": "$type", "n": {"$sum": 1}}}]'.
    Rejected if it contains $out, $merge or server-side JavaScript."""
    try:
        return _envelope(_db().run_aggregate(collection, pipeline, database or None, max_rows))
    except Exception as ex:
        return _err(ex)


# --- IDP submission flow (intellidoc-specific) -----------------------------------
@mcp.tool()
async def idp_find_submissions(
    source: str = "", status: str = "", search: str = "", days: int = 0, limit: int = 20
) -> dict[str, Any]:
    """List IDP submissions, newest first, across email triggers, webhook
    triggers and manual uploads, with file count, run count and run status.
    source: 'email' | 'webhook' | 'manual_upload' (empty = all).
    status: the submission's own status (e.g. processed, failed, received).
    search: text in subject / sender / claim or policy number (case-insensitive).
    days: only submissions received in the last N days (0 = any time)."""
    try:
        return _envelope(_idp().find_submissions(source, status, search, days, limit))
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def idp_get_submission(submission_id: str, include_nodes: bool = False) -> dict[str, Any]:
    """Everything about one submission in one call: its details, every file,
    and for each file its runs (extraction results) with process name, status,
    node progress (e.g. 9/11 completed), the current step and the nodes that
    failed or await approval. A file id or run id is also accepted.
    include_nodes=True also lists every node of every run (bigger response)."""
    try:
        return _idp().get_submission(submission_id, include_nodes)
    except Exception as ex:
        return _err(ex)


@mcp.tool()
async def idp_get_run_details(
    run_id: str, include_extracted_data: bool = False, include_node_outputs: bool = False
) -> dict[str, Any]:
    """Expand one run (extraction_results id): every workflow node in order
    with status, start/end, duration, outcome (decision, rules passed/failed,
    confidence), errors, manual approval and documents fetched by API
    connectors. include_extracted_data adds the extracted fields;
    include_node_outputs adds each node's full execution context."""
    try:
        return _idp().get_run_details(run_id, include_extracted_data, include_node_outputs)
    except Exception as ex:
        return _err(ex)


# --- overview ------------------------------------------------------------------


@mcp.tool()
async def get_database_overview(database: str = "", sample_size: int = 30) -> dict[str, Any]:
    """Structure of the whole database in one call: every collection with its
    document count and inferred fields/types, plus inferred relationships.
    Takes a while on large databases."""
    try:
        client = _db()
        db = database or None
        collections = []
        for c in client.list_collections(db):
            name = c["collection"]
            fields = client.infer_collection_schema(name, db, sample_size)
            collections.append({
                "collection": name,
                "type": c["type"],
                "document_count": client.count_documents(name, db)["document_count"],
                "fields": {f["field"]: f["types"] for f in fields},
            })
        return {
            "database": database or client.default_database,
            "collection_count": len(collections),
            "collections": collections,
            "relationships": client.get_inferred_relationships("", db, sample_size),
        }
    except Exception as ex:
        return _err(ex)


if __name__ == "__main__":
    _log("starting (stdio)")
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        _log("stopped")
