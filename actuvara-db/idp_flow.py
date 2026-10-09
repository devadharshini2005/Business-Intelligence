"""Actuvara IDP (intellidoc) submission-flow tools - read-only.

How a submission flows through the database:

  submission      emails | webhooks | manual_extractions      (email trigger / webhook trigger / manual upload)
    -> files      files.source_email_id | source_webhook_id | source_manual_extraction_id
    -> runs       extraction_results (one per file x process; a retry creates a new one)
                  .file_id, .email_id | .webhook_id | .manual_extraction_id, .proccess_id (sic)
    -> nodes      file_process_tracker (one row per workflow node of a run)
                  .extraction_result_id, .node_id, .status
  node names / order   processes.workflow.nodes[].label and .edges
  fetched documents    files.metadata.parent_ref_id = run id, .metadata.api_connector_node_id = node

Three levels, so an assistant can show a collapsed tree and expand on request:
  find_submissions  -> list submissions with file / run counts
  get_submission    -> one submission: files -> runs, each run with node progress and
                       what needs attention (all node steps with include_nodes=True)
  get_run_details   -> one run: every node in workflow order with status, timing,
                       errors, approvals and fetched documents

Every query here is a fixed, read-only pipeline built in this module.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

# How each submission source is stored. `title` / `sender` / `received` are the
# fields shown in lists; `search` are the fields free-text search looks at.
SOURCES: dict[str, dict[str, Any]] = {
    "email": {
        "collection": "emails", "file_fk": "source_email_id", "run_fk": "email_id",
        "title": "subject", "sender": "from_email", "received": "date_received",
        "search": ["subject", "from_email", "from_name"],
        "header": {"subject": 1, "from_email": 1, "from_name": 1, "to_emails": 1, "cc_emails": 1,
                   "date_received": 1, "processed_at": 1, "status": 1, "attachment_count": 1,
                   "has_attachments": 1, "is_spam": 1, "connector_instance_id": 1},
    },
    "webhook": {
        "collection": "webhooks", "file_fk": "source_webhook_id", "run_fk": "webhook_id",
        "title": "reference_subject", "sender": "source_domain", "received": "received_at",
        "search": ["reference_subject", "source_domain", "metadata.payload.claim_number",
                   "metadata.payload.policy_number"],
        "header": {"reference_subject": 1, "channel": 1, "source_domain": 1, "received_at": 1,
                   "processed_at": 1, "status": 1, "metadata.file_count": 1, "metadata.filenames": 1,
                   "metadata.payload.claim_number": 1, "metadata.payload.policy_number": 1,
                   "connector_instance_id": 1},
    },
    "manual_upload": {
        "collection": "manual_extractions", "file_fk": "source_manual_extraction_id",
        "run_fk": "manual_extraction_id",
        "title": "subject", "sender": "user_email", "received": "uploaded_at",
        "search": ["subject", "user_email", "metadata.user_name"],
        "header": {"subject": 1, "user_email": 1, "metadata.user_name": 1, "uploaded_at": 1,
                   "processed_at": 1, "status": 1, "process_ids": 1, "metadata.process_count": 1},
    },
}

FILE_FIELDS = {"filename": 1, "original_filename": 1, "file_type": 1, "mime_type": 1, "file_size": 1,
               "pages": 1, "status": 1, "uploaded_at": 1, "metadata.source": 1, "metadata.parent_file_id": 1}
RUN_FIELDS = {"status": 1, "file_id": 1, "proccess_id": 1, "created_at": 1, "completed_at": 1,
              "confidence_score": 1, "error_message": 1, "total_processing_time_ms": 1, "template_id": 1,
              "is_validated": 1, "email_id": 1, "webhook_id": 1, "manual_extraction_id": 1}

# Node statuses that need someone's attention, and the ones that mean "still going".
ATTENTION = {"failed", "rejected", "awaiting_approval"}
ACTIVE = {"inprogress", "in_progress", "pending", "pending_review", "awaiting_approval"}
MAX_FILES = 200
MAX_RUNS = 500
SUMMARY_CHARS = 600


def _oid(value: str, what: str = "id") -> ObjectId:
    try:
        return ObjectId(str(value).strip())
    except (InvalidId, TypeError):
        raise ValueError(f"{what} must be a 24-character hex id, got {value!r}") from None


def _s(value: Any) -> Any:
    """Plain JSON for ids and dates; everything else unchanged."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _s(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_s(v) for v in value]
    return value


def _get(doc: dict[str, Any], path: str) -> Any:
    for part in path.split("."):
        if not isinstance(doc, dict):
            return None
        doc = doc.get(part)
    return doc


def _duration_s(start: Any, end: Any) -> float | None:
    if isinstance(start, dt.datetime) and isinstance(end, dt.datetime):
        return round((end - start).total_seconds(), 1)
    return None


def _clip(text: Any, limit: int = SUMMARY_CHARS) -> Any:
    if isinstance(text, str) and len(text) > limit:
        return text[:limit].rstrip() + " ..."
    return text


def workflow_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """Node ids in the order the workflow runs: breadth-first from the trigger
    (or any node without incoming edges), following edges in their stored
    order. Back edges (loops) are ignored; unreachable nodes go last."""
    ids = [n.get("id") for n in nodes if n.get("id")]
    nxt: dict[str, list[str]] = {}
    incoming: set[str] = set()
    for e in edges or []:
        s, t = e.get("source"), e.get("target")
        if s and t:
            nxt.setdefault(s, []).append(t)
            incoming.add(t)
    starts = [n["id"] for n in nodes if n.get("type") == "trigger" and n.get("id")]
    starts += [i for i in ids if i not in incoming and i not in starts]
    order: list[str] = []
    queue = list(starts)
    while queue:
        node = queue.pop(0)
        if node in order:
            continue
        order.append(node)
        queue.extend(t for t in nxt.get(node, []) if t not in order)
    return order + [i for i in ids if i not in order]


def rollup(statuses: list[str]) -> str:
    """One word for a set of run (or node) statuses."""
    if not statuses:
        return "no_runs"
    s = {x or "unknown" for x in statuses}
    if s & {"failed", "rejected"}:
        return "has_failures"
    if s & ACTIVE:
        return "in_progress"
    if s <= {"completed", "skipped"}:
        return "completed"
    return "mixed"


class IdpFlow:
    """Submission -> files -> runs -> nodes, for the Actuvara IDP database."""

    def __init__(self, db) -> None:
        self.db = db

    # --- helpers ------------------------------------------------------------
    def _process_maps(self, process_ids: list[ObjectId]) -> dict[str, dict[str, Any]]:
        """process id -> {name, labels: {node_id: node}, order: [node_id]}."""
        out: dict[str, dict[str, Any]] = {}
        for p in self.db.processes.find({"_id": {"$in": list(set(process_ids))}},
                                        {"name": 1, "workflow.nodes": 1, "workflow.edges": 1}):
            nodes = [{"id": n.get("id"), "label": n.get("label"), "type": n.get("type"),
                      "subType": n.get("subType")} for n in _get(p, "workflow.nodes") or []]
            out[str(p["_id"])] = {
                "name": p.get("name"),
                "nodes": {n["id"]: n for n in nodes if n["id"]},
                "order": workflow_order(nodes, _get(p, "workflow.edges") or []),
            }
        return out

    def _resolve(self, any_id: ObjectId) -> tuple[str, dict[str, Any], str | None]:
        """Find the submission for a submission, file or run id."""
        for source, cfg in SOURCES.items():
            doc = self.db[cfg["collection"]].find_one({"_id": any_id}, cfg["header"])
            if doc:
                return source, doc, None
        hints = [("files", "file"), ("extraction_results", "run"), ("file_process_tracker", "node step")]
        for coll, kind in hints:
            doc = self.db[coll].find_one({"_id": any_id})
            if not doc:
                continue
            for source, cfg in SOURCES.items():
                key = cfg["file_fk"] if coll == "files" else cfg["run_fk"]
                if doc.get(key):
                    sub = self.db[cfg["collection"]].find_one({"_id": doc[key]}, cfg["header"])
                    if sub:
                        return source, sub, f"resolved from {kind} {any_id}"
            if coll == "files" and _get(doc, "metadata.parent_file_id"):
                try:
                    return self._resolve(_oid(_get(doc, "metadata.parent_file_id")))
                except ValueError:
                    pass
        raise ValueError(f"no submission, file or run found with id {any_id}")

    def _node_rows(self, run_ids: list[ObjectId]) -> list[dict[str, Any]]:
        return list(self.db.file_process_tracker.find(
            {"extraction_result_id": {"$in": run_ids}},
            {"extraction_result_id": 1, "node_id": 1, "status": 1, "node_data": 1, "started_at": 1,
             "completed_at": 1, "execution_time_ms": 1, "actions_completed": 1, "total_actions": 1,
             "error_details": 1, "manual_approval": 1, "manual_status": 1, "execution_context": 1,
             "summary.content": 1, "summary.status": 1},
        ))

    def _fetched_docs(self, run_ids: list[ObjectId]) -> dict[str, list[dict[str, Any]]]:
        """Documents an API connector fetched during a run, keyed by run id."""
        out: dict[str, list[dict[str, Any]]] = {}
        for f in self.db.files.find({"metadata.parent_ref_id": {"$in": [str(r) for r in run_ids]}},
                                    {"filename": 1, "file_type": 1, "file_size": 1, "status": 1,
                                     "metadata.parent_ref_id": 1, "metadata.api_connector_node_id": 1,
                                     "metadata.source": 1}):
            out.setdefault(_get(f, "metadata.parent_ref_id"), []).append({
                "file_id": str(f["_id"]), "filename": f.get("filename"), "file_type": f.get("file_type"),
                "file_size": f.get("file_size"), "status": f.get("status"),
                "node_id": _get(f, "metadata.api_connector_node_id"), "source": _get(f, "metadata.source"),
            })
        return out

    @staticmethod
    def _node_view(row: dict[str, Any], label_node: dict[str, Any] | None, step: int | None,
                   docs: list[dict[str, Any]], full: bool) -> dict[str, Any]:
        ctx = row.get("execution_context") or {}
        err = row.get("error_details") or {}
        appr = row.get("manual_approval") or {}
        view: dict[str, Any] = {
            "step": step,
            "node_id": row.get("node_id"),
            "name": (label_node or {}).get("label") or _get(row, "node_data.node_sub_type"),
            "type": _get(row, "node_data.node_type"),
            "sub_type": _get(row, "node_data.node_sub_type"),
            "status": row.get("status"),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "duration_s": _duration_s(row.get("started_at"), row.get("completed_at")),
            "actions": f"{row.get('actions_completed', 0)}/{row.get('total_actions', 0)}",
        }
        outcome = {k: ctx.get(k) for k in ("decision", "overall_result", "recommended_action",
                                           "confidence_score", "rules_passed", "rules_failed",
                                           "human_review_required") if ctx.get(k) is not None}
        if ctx.get("issues"):
            outcome["issues"] = len(ctx["issues"])
        if outcome:
            view["outcome"] = outcome
        if err:
            view["error"] = {k: _clip(err.get(k), 300) for k in ("reason", "stage", "exception_type",
                                                                  "http_status", "url", "recommended_action")
                             if err.get(k) is not None}
        if appr:
            view["approval"] = {k: appr.get(k) for k in ("node_name", "decision", "decided_by", "decided_at",
                                                         "reason", "requested_at") if appr.get(k) is not None}
        if row.get("manual_status"):
            view["manual_status"] = row["manual_status"]
        if _get(row, "summary.content"):
            view["summary"] = _get(row, "summary.content") if full else _clip(_get(row, "summary.content"))
        if docs:
            view["fetched_documents"] = docs
        if full:
            view["execution_context"] = ctx or None
            view["error_details"] = err or None
        return view

    def _nodes_for_run(self, run_id: str, rows: list[dict[str, Any]], proc: dict[str, Any] | None,
                       docs: list[dict[str, Any]], full: bool) -> list[dict[str, Any]]:
        order = (proc or {}).get("order") or []
        rank = {nid: i for i, nid in enumerate(order)}
        far = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
        rows = sorted(rows, key=lambda r: (rank.get(r.get("node_id"), len(rank)),
                                           r.get("started_at") or far))
        labels = (proc or {}).get("nodes") or {}
        by_node: dict[str, list[dict[str, Any]]] = {}
        for d in docs:
            by_node.setdefault(d.get("node_id"), []).append(d)
        return [self._node_view(r, labels.get(r.get("node_id")), i, by_node.get(r.get("node_id"), []), full)
                for i, r in enumerate(rows, 1)]

    # --- level 1: list ------------------------------------------------------
    def find_submissions(self, source: str = "", status: str = "", search: str = "",
                         days: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        sources = [source] if source else list(SOURCES)
        for s in sources:
            if s not in SOURCES:
                raise ValueError(f"source must be one of {', '.join(SOURCES)} (or empty for all)")
        limit = max(1, min(int(limit), 200))
        rows: list[dict[str, Any]] = []
        for src in sources:
            cfg = SOURCES[src]
            flt: dict[str, Any] = {}
            if status:
                flt["status"] = status
            if search:
                rx = {"$regex": re.escape(search), "$options": "i"}
                flt["$or"] = [{f: rx} for f in cfg["search"]]
            if days and int(days) > 0:
                since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(days))
                flt[cfg["received"]] = {"$gte": since}
            for d in self.db[cfg["collection"]].find(
                    flt, {cfg["title"]: 1, cfg["sender"]: 1, cfg["received"]: 1, "status": 1},
                    sort=[(cfg["received"], -1)], limit=limit):
                rows.append({"submission_id": d["_id"], "source": src, "title": _get(d, cfg["title"]),
                             "from": _get(d, cfg["sender"]), "received_at": _get(d, cfg["received"]),
                             "status": d.get("status")})
        far_past = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        rows.sort(key=lambda r: r["received_at"] or far_past, reverse=True)
        rows = rows[:limit]

        # File and run counts for the listed submissions, one query per source.
        for src in {r["source"] for r in rows}:
            cfg = SOURCES[src]
            ids = [r["submission_id"] for r in rows if r["source"] == src]
            files = {g["_id"]: g["n"] for g in self.db.files.aggregate([
                {"$match": {cfg["file_fk"]: {"$in": ids}}},
                {"$group": {"_id": f"${cfg['file_fk']}", "n": {"$sum": 1}}}])}
            runs: dict[Any, list[str]] = {}
            for g in self.db.extraction_results.aggregate([
                    {"$match": {cfg["run_fk"]: {"$in": ids}}},
                    {"$group": {"_id": f"${cfg['run_fk']}", "statuses": {"$push": "$status"}}}]):
                runs[g["_id"]] = g["statuses"]
            for r in rows:
                if r["source"] == src:
                    st = runs.get(r["submission_id"], [])
                    r["files"] = files.get(r["submission_id"], 0)
                    r["runs"] = len(st)
                    r["run_status"] = rollup(st)
        return _s(rows)

    # --- level 2: one submission ---------------------------------------------
    def get_submission(self, submission_id: str, include_nodes: bool = False) -> dict[str, Any]:
        source, sub, note = self._resolve(_oid(submission_id, "submission_id"))
        cfg = SOURCES[source]
        sid = sub["_id"]

        files = list(self.db.files.find({cfg["file_fk"]: sid}, FILE_FIELDS, limit=MAX_FILES))
        runs = list(self.db.extraction_results.find({cfg["run_fk"]: sid}, RUN_FIELDS,
                                                    sort=[("created_at", 1)], limit=MAX_RUNS))
        # A run can point at a file that isn't linked to the submission directly.
        known = {f["_id"] for f in files}
        extra = [r["file_id"] for r in runs if r.get("file_id") and r["file_id"] not in known]
        if extra:
            files += list(self.db.files.find({"_id": {"$in": extra}}, FILE_FIELDS))

        run_ids = [r["_id"] for r in runs]
        procs = self._process_maps([r["proccess_id"] for r in runs if r.get("proccess_id")])
        node_rows: dict[Any, list[dict[str, Any]]] = {}
        for row in self._node_rows(run_ids):
            node_rows.setdefault(row["extraction_result_id"], []).append(row)
        fetched = self._fetched_docs(run_ids)

        runs_by_file: dict[Any, list[dict[str, Any]]] = {}
        for r in runs:
            rows = node_rows.get(r["_id"], [])
            proc = procs.get(str(r.get("proccess_id")))
            counts: dict[str, int] = {}
            for row in rows:
                counts[row.get("status") or "unknown"] = counts.get(row.get("status") or "unknown", 0) + 1
            nodes = self._nodes_for_run(str(r["_id"]), rows, proc, fetched.get(str(r["_id"]), []), False)
            run_view: dict[str, Any] = {
                "run_id": r["_id"],
                "process": (proc or {}).get("name"),
                "process_id": r.get("proccess_id"),
                "status": r.get("status"),
                "started_at": r.get("created_at"),
                "completed_at": r.get("completed_at"),
                "duration_s": _duration_s(r.get("created_at"), r.get("completed_at")),
                "confidence_score": r.get("confidence_score"),
                "error_message": _clip(r.get("error_message"), 300),
                "node_progress": f"{counts.get('completed', 0)}/{len(rows)} completed",
                "node_status_counts": counts,
                "needs_attention": [{"step": n["step"], "name": n["name"], "status": n["status"],
                                     **({"error": n["error"]} if n.get("error") else {})}
                                    for n in nodes if n["status"] in ATTENTION],
                "current_step": next(({"step": n["step"], "name": n["name"], "status": n["status"]}
                                      for n in nodes if n["status"] in ACTIVE), None),
                "fetched_documents": len(fetched.get(str(r["_id"]), [])),
            }
            if include_nodes:
                run_view["nodes"] = nodes
            runs_by_file.setdefault(r.get("file_id"), []).append(run_view)

        file_views = []
        for f in files:
            f_runs = runs_by_file.get(f["_id"], [])
            file_views.append({
                "file_id": f["_id"], "filename": f.get("filename") or f.get("original_filename"),
                "file_type": f.get("file_type"), "file_size": f.get("file_size"), "pages": f.get("pages"),
                "status": f.get("status"), "uploaded_at": f.get("uploaded_at"),
                "origin": _get(f, "metadata.source") or "submission",
                "run_status": rollup([r["status"] for r in f_runs]),
                "runs": f_runs,
            })

        header = {k: v for k, v in sub.items() if k != "_id"}
        result = {
            "submission_id": sid,
            "source": source,
            "collection": cfg["collection"],
            "details": header,
            "totals": {
                "files": len(file_views),
                "runs": len(runs),
                "run_status": rollup([r.get("status") for r in runs]),
                "runs_by_status": {s: sum(1 for r in runs if r.get("status") == s)
                                   for s in sorted({r.get("status") or "unknown" for r in runs})},
            },
            "files": file_views,
            "next": "Call get_run_details(run_id) to expand every node of a run, "
                    "or get_submission(..., include_nodes=True) to expand all runs at once.",
        }
        if note:
            result["note"] = note
        return _s(result)

    # --- level 3: one run ---------------------------------------------------
    def get_run_details(self, run_id: str, include_extracted_data: bool = False,
                        include_node_outputs: bool = False) -> dict[str, Any]:
        rid = _oid(run_id, "run_id")
        proj = dict(RUN_FIELDS, validations=1, dispatched_nodes=1)
        if include_extracted_data:
            proj["extracted_data"] = 1
        run = self.db.extraction_results.find_one({"_id": rid}, proj)
        if not run:
            # Accept a node-step id too and go to its run.
            step = self.db.file_process_tracker.find_one({"_id": rid}, {"extraction_result_id": 1})
            if not step or not step.get("extraction_result_id"):
                raise ValueError(f"no run (extraction_results) found with id {run_id}")
            return self.get_run_details(str(step["extraction_result_id"]), include_extracted_data,
                                        include_node_outputs)

        proc = self._process_maps([run["proccess_id"]]).get(str(run.get("proccess_id"))) \
            if run.get("proccess_id") else None
        rows = self._node_rows([rid])
        docs = self._fetched_docs([rid]).get(str(rid), [])
        nodes = self._nodes_for_run(str(rid), rows, proc, docs, include_node_outputs)
        file = self.db.files.find_one({"_id": run.get("file_id")}, FILE_FIELDS) if run.get("file_id") else None
        submission = next(({"source": s, "submission_id": run.get(c["run_fk"])}
                           for s, c in SOURCES.items() if run.get(c["run_fk"])), None)

        result: dict[str, Any] = {
            "run_id": rid,
            "submission": submission,
            "file": {"file_id": file["_id"], "filename": file.get("filename"), "file_type": file.get("file_type")}
            if file else None,
            "process": (proc or {}).get("name"),
            "status": run.get("status"),
            "started_at": run.get("created_at"),
            "completed_at": run.get("completed_at"),
            "duration_s": _duration_s(run.get("created_at"), run.get("completed_at")),
            "confidence_score": run.get("confidence_score"),
            "is_validated": run.get("is_validated"),
            "error_message": run.get("error_message"),
            "node_status": rollup([n["status"] for n in nodes]),
            "nodes": nodes,
            "fetched_documents": docs,
        }
        if include_extracted_data:
            result["extracted_data"] = run.get("extracted_data")
        return _s(result)
