"""Read-only guard for the ad-hoc MongoDB tools (`run_find`, `run_aggregate`,
`count_documents`).

Arguments arrive as JSON text (MongoDB Extended JSON is accepted, e.g.
{"_id": {"$oid": "..."}}). Every key at every depth is checked, and anything
that could write data or run server-side JavaScript is rejected before the
request is sent:
  * $out / $merge  - aggregation stages that write to a collection
  * $where / $function / $accumulator - run JavaScript on the server

Inserts, updates and deletes are separate driver calls (insert_one,
update_many, delete_many, ...) that this project never makes, so a filter or
pipeline is the only way a request could write - and that is what's checked
here. The real protection is still a database user with read-only rights.
"""
from __future__ import annotations

from typing import Any

from bson import json_util

FORBIDDEN_OPERATORS = {"$out", "$merge", "$where", "$function", "$accumulator"}

# Stages Azure Cosmos DB for MongoDB rejects. Caught here so the caller gets a usable hint instead of the
# server's bare "unrecognized pipeline stage" error.
UNSUPPORTED_STAGES = {
    "$setwindowfields": "Cosmos DB does not support $setWindowFields. For running totals or ranks, $group/$sort "
                        "the rows and compute per group, or return the rows and chart them with build_chart.",
}

# Field names that are misspelt in the stored data. The data is read-only, so the queries must use the stored
# spelling; a query using the "correct" spelling would silently match nothing.
MISSPELT_FIELDS = {
    "extraction_results": {"process_id": "proccess_id"},
}


class QueryGuardError(Exception):
    """Raised when a query fails the read-only guard."""


def check_stages(pipeline: list[dict[str, Any]]) -> None:
    """Reject stages Cosmos DB does not support (at any depth, e.g. inside $lookup or $facet)."""
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                hint = UNSUPPORTED_STAGES.get(key.lower()) if isinstance(key, str) else None
                if hint:
                    raise QueryGuardError(hint)
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(pipeline)


def check_field_names(collection: str, query: Any, extra_fields: list[str] | None = None) -> None:
    """Reject a query on `collection` that uses a field under its corrected spelling.

    A name the query itself defines (e.g. {"$project": {"process_id": "$proccess_id"}}) is allowed."""
    wrong = MISSPELT_FIELDS.get(collection)
    if not wrong:
        return
    used: set[str] = set(extra_fields or [])
    defined: set[str] = set()

    def walk(value: Any, defining: bool) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                if key == "localField" and isinstance(child, str):  # $lookup names a stored field, no "$"
                    used.add(child.split(".")[0])
                elif key.startswith("$"):
                    # $project / $group / $set / $addFields keys are output names, not stored fields.
                    walk(child, key in ("$project", "$group", "$set", "$addFields"))
                else:
                    (defined if defining else used).add(key.split(".")[0])
                    walk(child, False)
        elif isinstance(value, list):
            for item in value:
                walk(item, defining)
        elif isinstance(value, str) and value.startswith("$") and not value.startswith("$$"):
            used.add(value[1:].split(".")[0])

    walk(query, False)
    for bad, stored in wrong.items():
        if bad in used and bad not in defined:
            raise QueryGuardError(f"{collection} has no field '{bad}' - in the stored data it is spelt "
                                  f"'{stored}'. Use '{stored}' (the data is read-only, so the spelling can't "
                                  f"be changed).")


def _check(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_OPERATORS:
                raise QueryGuardError(f"operator '{key}' is not allowed (read-only server)")
            _check(child)
    elif isinstance(value, list):
        for item in value:
            _check(item)


def _load(text: str, what: str) -> Any:
    try:
        value = json_util.loads(text)
    except Exception as ex:
        raise QueryGuardError(f"{what} is not valid JSON: {ex}") from None
    _check(value)
    return value


def parse_filter(text: str) -> dict[str, Any]:
    """Filter document for find()/count. Empty means 'all documents'."""
    if not text or not text.strip():
        return {}
    value = _load(text, "filter")
    if not isinstance(value, dict):
        raise QueryGuardError("filter must be a JSON object, e.g. {\"status\": \"open\"}")
    return value


def parse_projection(text: str) -> dict[str, Any] | None:
    if not text or not text.strip():
        return None
    value = _load(text, "projection")
    if not isinstance(value, dict):
        raise QueryGuardError("projection must be a JSON object, e.g. {\"name\": 1, \"_id\": 0}")
    return value


def parse_sort(text: str) -> list[tuple[str, int]] | None:
    if not text or not text.strip():
        return None
    value = _load(text, "sort")
    if not isinstance(value, dict) or not all(v in (1, -1) for v in value.values()):
        raise QueryGuardError("sort must be a JSON object of 1/-1, e.g. {\"createdAt\": -1}")
    return list(value.items())


def parse_pipeline(text: str) -> list[dict[str, Any]]:
    """Aggregation pipeline: a JSON array of stage objects."""
    if not text or not text.strip():
        raise QueryGuardError("empty pipeline")
    value = _load(text, "pipeline")
    if not isinstance(value, list) or not all(isinstance(stage, dict) for stage in value):
        raise QueryGuardError("pipeline must be a JSON array of stages, e.g. [{\"$match\": {...}}]")
    return value
