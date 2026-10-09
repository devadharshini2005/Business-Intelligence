"""Read-only client for the Actuvara Azure Cosmos DB for MongoDB (vCore).

What it offers:
  * database / collection names, collection options and indexes;
  * document "shape" - field paths, their types and how often each appears -
    INFERRED by sampling documents;
  * relationships - INFERRED from naming (`policyId` -> `policies`) and
    checked against a sample, reported as a match percentage;
  * read-only data access: find, aggregate, distinct values, counts.

READ-ONLY: this module never calls insert / update / delete / drop or any
other write. Filters and pipelines are checked by query_guard, which rejects
$out / $merge (the only way a read can write) and server-side JavaScript.
The real protection is still a database user that only has read rights.

Configuration (read from environment / .env):
  MONGODB_URI        mongodb://<user>:<password>@<cluster>.mongocluster.cosmos.azure.com:10260/...
                     (COSMOS_CONNECTION_STRING is accepted as a fallback name)
  MONGODB_DATABASE   default database used when a tool isn't given one
                     (falls back to COSMOS_DATABASE, then to the database in the URI)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import warnings
from typing import Any

from bson import Binary, Decimal128, ObjectId, json_util
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri

from query_guard import parse_filter, parse_pipeline, parse_projection, parse_sort

MAX_SAMPLE = 1000
MAX_ROWS = 1000
RELATIONSHIP_SAMPLE = 50


class MongoConfigError(Exception):
    """Missing/invalid MongoDB configuration."""


def _env(*names: str) -> str:
    """First non-empty variable among `names`, with stray quotes / a trailing
    ';' removed (a common .env mistake that breaks the URI)."""
    for name in names:
        value = os.getenv(name, "").strip().rstrip(";").strip().strip("'\"").strip()
        if value:
            return value
    return ""


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float, Decimal128)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, ObjectId):
        return "objectId"
    if isinstance(value, dt.datetime):
        return "date"
    if isinstance(value, (bytes, Binary)):
        return "binary"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _collect_fields(value: Any, prefix: str, out: dict[str, set[str]]) -> None:
    """Record every field path in one document with the types seen for it.
    Nested objects use dots (`address.city`); objects inside arrays use `[]`
    (`lines[].amount`)."""
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.setdefault(path, set()).add(_type_name(child))
            _collect_fields(child, path, out)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                _collect_fields(item, f"{prefix}[]", out)


def _field_path(field_path: str) -> str:
    """Validate a dotted field path and turn `lines[].amount` into
    `lines.amount` (MongoDB walks into arrays on its own). Segments may not
    start with '$', so a field name can never become an operator."""
    path = (field_path or "").replace("[]", "")
    segments = path.split(".")
    if not path or any(not seg or seg.startswith("$") for seg in segments):
        raise ValueError("field_path must be a dotted field name (e.g. 'status' or 'address.city')")
    return path


def _normalize_name(name: str) -> str:
    n = name.lower().replace("_", "").replace("-", "")
    if n.endswith("ies"):
        return n[:-3] + "y"
    if n.endswith("s") and not n.endswith("ss"):
        return n[:-1]
    return n


def _to_json(value: Any) -> Any:
    """BSON -> plain JSON. Only used on metadata (options, index keys)."""
    return json.loads(json_util.dumps(value, json_options=json_util.RELAXED_JSON_OPTIONS))


def _cap(n: int, limit: int) -> int:
    return max(1, min(int(n), limit))


class MongoMetadataClient:
    """Metadata-only client for the Actuvara MongoDB (vCore) cluster."""

    def __init__(self) -> None:
        uri = _env("MONGODB_URI", "COSMOS_CONNECTION_STRING")
        if not uri:
            raise MongoConfigError("Set MONGODB_URI (mongodb://...) in the .env file")
        if not uri.startswith(("mongodb://", "mongodb+srv://")):
            raise MongoConfigError("MONGODB_URI must start with mongodb:// or mongodb+srv://")

        parsed = parse_uri(uri)
        self.hosts = [f"{h}:{p}" for h, p in parsed["nodelist"]]  # never the credentials
        self.default_database = _env("MONGODB_DATABASE", "COSMOS_DATABASE") or parsed.get("database") or ""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # pymongo's "you appear to be connected to CosmosDB" notice
            self._client: MongoClient = MongoClient(
                uri,
                appname="actuvara-mcp-metadata",
                serverSelectionTimeoutMS=15000,
                timeoutMS=60000,  # caps every operation, so a big scan can't run forever
                tz_aware=True,
            )

    # --- helpers ------------------------------------------------------------
    def _db(self, database: str | None):
        name = database or self.default_database
        if not name:
            raise MongoConfigError("No database given and MONGODB_DATABASE is not set")
        return self._client[name]

    def database(self, database: str | None = None):
        """The pymongo Database handle, for the app-specific read-only tools (idp_flow)."""
        return self._db(database)

    def _coll(self, collection: str, database: str | None):
        return self._db(database)[collection]

    def _sample(self, collection: str, database: str | None, sample_size: int) -> list[dict[str, Any]]:
        """Internal only - callers must reduce these documents to names/types."""
        n = _cap(sample_size, MAX_SAMPLE)
        coll = self._coll(collection, database)
        try:
            return list(coll.aggregate([{"$sample": {"size": n}}]))
        except Exception:
            # Views and some server versions refuse $sample - take the first n instead.
            return list(coll.find({}, limit=n))

    # --- connectivity -------------------------------------------------------
    def ping(self) -> bool:
        self._client.admin.command("ping")
        return True

    def server_info(self) -> dict[str, Any]:
        info = self._client.server_info()
        return {
            "hosts": self.hosts,
            "default_database": self.default_database or None,
            "version": info.get("version"),
        }

    # --- discovery ----------------------------------------------------------
    def list_databases(self) -> list[dict[str, Any]]:
        return [{"database": name} for name in sorted(self._client.list_database_names())]

    def list_collections(self, database: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for c in self._db(database).list_collections():
            options = c.get("options", {})
            rows.append({
                "collection": c["name"],
                "type": c.get("type", "collection"),
                "view_on": options.get("viewOn"),
                "capped": options.get("capped", False),
                "has_validator": "validator" in options,
            })
        return sorted(rows, key=lambda r: r["collection"].lower())

    def find_collections_like(self, name_pattern: str, database: str | None = None) -> list[dict[str, Any]]:
        pat = name_pattern.lower()
        return [r for r in self.list_collections(database) if pat in r["collection"].lower()]

    def collection_exists(self, collection: str, database: str | None = None) -> list[dict[str, Any]]:
        return [r for r in self.list_collections(database) if r["collection"].lower() == collection.lower()]

    def get_collection_details(self, collection: str, database: str | None = None) -> dict[str, Any]:
        db = self._db(database)
        found = list(db.list_collections(filter={"name": collection}))
        if not found:
            raise ValueError(f"collection '{collection}' not found in database '{db.name}'")
        meta = found[0]
        details: dict[str, Any] = {
            "collection": collection,
            "type": meta.get("type", "collection"),
            "options": _to_json(meta.get("options", {})),  # validator / view definition, not documents
            "indexes": self.list_indexes(collection, database),
        }
        try:
            stats = db.command("collStats", collection)
            details["stats"] = {
                "document_count": stats.get("count"),
                "size_bytes": stats.get("size"),
                "avg_doc_size_bytes": stats.get("avgObjSize"),
                "storage_size_bytes": stats.get("storageSize"),
                "index_count": stats.get("nindexes"),
                "sharded": stats.get("sharded"),
            }
        except Exception:
            details["stats"] = "not available on this server / with this user"
        return details

    def list_indexes(self, collection: str, database: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for ix in self._coll(collection, database).list_indexes():
            ix = dict(ix)
            rows.append({
                "name": ix.pop("name"),
                "keys": _to_json(ix.pop("key")),
                "unique": ix.pop("unique", False),
                "other": _to_json({k: v for k, v in ix.items() if k not in ("v", "ns")}),
            })
        return rows

    # --- inferred schema ----------------------------------------------------
    def infer_collection_schema(
        self, collection: str, database: str | None = None, sample_size: int = 100
    ) -> list[dict[str, Any]]:
        """Field paths, types and presence across a random sample of documents.
        Only names and types are returned - the sampled values are discarded."""
        docs = self._sample(collection, database, sample_size)
        presence: dict[str, int] = {}
        types: dict[str, set[str]] = {}
        for doc in docs:
            fields: dict[str, set[str]] = {}
            _collect_fields(doc, "", fields)
            for path, seen in fields.items():
                presence[path] = presence.get(path, 0) + 1
                types.setdefault(path, set()).update(seen)
        total = len(docs)
        return [
            {
                "field": path,
                "types": ", ".join(sorted(types[path])),
                "present_in": presence[path],
                "sampled_docs": total,
                "presence_pct": round(100 * presence[path] / total, 1) if total else 0,
            }
            for path in sorted(presence)
        ]

    def find_fields_like(
        self, field_pattern: str, database: str | None = None, sample_size: int = 50
    ) -> list[dict[str, Any]]:
        """Search every collection's inferred schema for fields whose name contains the pattern."""
        pat = field_pattern.lower()
        rows = []
        for c in self.list_collections(database):
            for f in self.infer_collection_schema(c["collection"], database, sample_size):
                if pat in f["field"].lower():
                    rows.append({"collection": c["collection"], **f})
        return rows

    def field_exists(
        self, collection: str, field_path: str, database: str | None = None
    ) -> list[dict[str, Any]]:
        """Exact check across the WHOLE collection (not a sample): how many
        documents have this field."""
        path = _field_path(field_path)
        n = self._coll(collection, database).count_documents({path: {"$exists": True}})
        return [{"collection": collection, "field": field_path, "exists": n > 0, "documents_with_field": n}]

    # --- relationships ------------------------------------------------------
    def _match_pct(self, src: str, field: str, target: str, database: str | None) -> float | None:
        """Share of sampled `src` documents whose `field` points at an existing
        `target._id`. Ids stored as strings are converted to ObjectId first.
        The pipeline ends in two counts, so no value leaves the server.
        None = no non-empty values to check, or the check failed."""
        path = _field_path(field)
        to_oid = {"$convert": {"input": "$$this", "to": "objectId", "onError": "$$this", "onNull": None}}
        pipeline = [
            {"$match": {path: {"$exists": True, "$ne": None}}},
            {"$sample": {"size": RELATIONSHIP_SAMPLE}},
            {"$addFields": {"_k": {"$let": {"vars": {"v": f"${path}"}, "in": {"$cond": [
                {"$isArray": "$$v"},
                {"$map": {"input": "$$v", "in": to_oid}},
                {"$convert": {"input": "$$v", "to": "objectId", "onError": "$$v", "onNull": None}},
            ]}}}}},
            {"$lookup": {"from": target, "localField": "_k", "foreignField": "_id", "as": "_m"}},
            {"$group": {"_id": None, "n": {"$sum": 1},
                        "hits": {"$sum": {"$cond": [{"$gt": [{"$size": "$_m"}, 0]}, 1, 0]}}}},
        ]
        try:
            res = list(self._coll(src, database).aggregate(pipeline))
        except Exception:
            return None
        if not res or not res[0]["n"]:
            return None
        return round(100 * res[0]["hits"] / res[0]["n"], 1)

    def get_inferred_relationships(
        self, collection: str = "", database: str | None = None, sample_size: int = 50, verify: bool = True
    ) -> list[dict[str, Any]]:
        """Guess links between collections from `<name>Id` / `<name>_id` fields
        and (optionally) check a sample of them against the target's `_id`.
        MongoDB has no foreign keys, so every row here is inferred."""
        all_colls = [c["collection"] for c in self.list_collections(database)]
        by_norm = {_normalize_name(name): name for name in all_colls}
        sources = [c for c in all_colls if not collection or c.lower() == collection.lower()]

        rows = []
        for src in sources:
            for f in self.infer_collection_schema(src, database, sample_size):
                leaf = f["field"].split(".")[-1].replace("[]", "")
                low = leaf.lower()
                if low in ("id", "_id") or not low.endswith("id"):
                    continue
                base = _normalize_name(leaf[:-2].rstrip("_-"))
                target = by_norm.get(base)
                if not target:
                    continue
                row: dict[str, Any] = {
                    "from_collection": src,
                    "field": f["field"],
                    "field_types": f["types"],
                    "to_collection": target,
                    "basis": f"field name '{leaf}' matches collection '{target}'",
                }
                if verify:
                    pct = self._match_pct(src, f["field"], target, database)
                    row["sample_match_pct"] = pct
                    row["confidence"] = (
                        "unverified (field always empty, or check not supported)" if pct is None
                        else "confirmed" if pct >= 80
                        else "partial" if pct > 0
                        else "name only (values don't match target _id)"
                    )
                rows.append(row)
        return rows

    # --- counts & read-only data access ---------------------------------------
    def count_documents(self, collection: str, database: str | None = None, filter_json: str = "") -> dict[str, Any]:
        """Documents in a collection, optionally matching a JSON filter."""
        flt = parse_filter(filter_json)
        return {"collection": collection, "filter": _to_json(flt),
                "document_count": self._coll(collection, database).count_documents(flt)}

    def get_distinct_values(
        self, collection: str, field_path: str, database: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Distinct values of one field with how many documents have each."""
        path = (field_path or "").replace("[]", "")
        if not path or any(not seg or seg.startswith("$") for seg in path.split(".")):
            raise ValueError("field_path must be a dotted field name (e.g. 'status' or 'address.city')")
        pipeline = [
            {"$match": {path: {"$exists": True}}},
            {"$group": {"_id": f"${path}", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": _cap(limit, MAX_ROWS)},
        ]
        rows = _to_json(list(self._coll(collection, database).aggregate(pipeline)))
        return [{"value": r["_id"], "count": r["count"]} for r in rows]

    def run_find(
        self,
        collection: str,
        filter_json: str = "",
        projection_json: str = "",
        sort_json: str = "",
        database: str | None = None,
        max_rows: int = 100,
    ) -> list[dict[str, Any]]:
        """One read-only find(). All arguments are JSON checked by query_guard."""
        cursor = self._coll(collection, database).find(
            parse_filter(filter_json),
            projection=parse_projection(projection_json),
            sort=parse_sort(sort_json),
            limit=_cap(max_rows, MAX_ROWS),
        )
        return _to_json(list(cursor))

    def run_aggregate(
        self, collection: str, pipeline_json: str, database: str | None = None, max_rows: int = 100
    ) -> list[dict[str, Any]]:
        """One read-only aggregation. Rejected if it contains a write stage
        ($out/$merge) or server-side JavaScript; a $limit is always appended."""
        pipeline = parse_pipeline(pipeline_json)
        pipeline.append({"$limit": _cap(max_rows, MAX_ROWS)})
        rows = _to_json(list(self._coll(collection, database).aggregate(pipeline)))
        return [r if isinstance(r, dict) else {"value": r} for r in rows]
