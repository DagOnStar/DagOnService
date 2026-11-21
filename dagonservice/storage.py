"""MongoDB persistence for registered workflows and their event log.

All task mutations are single atomic MongoDB updates on dotted paths
(``tasks.<encoded name>.<field>``). DAGonStar runs tasks as concurrent threads
and each thread reports its own status, so read-modify-write cycles over the
whole workflow document -- as used by the 2018 prototype -- would silently
lose updates. Status changes, attribute updates and dependency edges therefore
never replace the document.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

from . import model
from .model import ValidationError, decode_key, encode_key, isoformat, legacy_timestamp, utcnow

LOG = logging.getLogger(__name__)


class NotFound(LookupError):
    """A workflow or task does not exist (or an identifier is malformed)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Conflict(RuntimeError):
    """A workflow with the same name exists and the duplicate policy rejects it."""


def parse_id(workflow_id: str) -> ObjectId:
    try:
        return ObjectId(workflow_id)
    except (InvalidId, TypeError):
        raise NotFound("Invalid ID %s" % workflow_id)


class WorkflowStore:
    """Repository over the ``workflows`` and ``events`` collections."""

    def __init__(self, database: Database, max_history: int = 1000) -> None:
        self.db = database
        self.workflows: Collection = database["workflows"]
        self.events: Collection = database["events"]
        self.max_history = max_history
        #: Called with the public JSON form of every recorded event.
        self.on_event: Optional[Callable[[Dict[str, Any]], None]] = None

    # ------------------------------------------------------------------ setup
    def ensure_indexes(self) -> None:
        self.workflows.create_index([("name", ASCENDING), ("created_at", DESCENDING)])
        self.events.create_index([("workflow_id", ASCENDING), ("_id", ASCENDING)])

    def ping(self) -> bool:
        try:
            self.db.command("ping")
            return True
        except Exception as exc:  # pragma: no cover - depends on the server
            LOG.warning("MongoDB ping failed: %s", exc)
            return False

    # ------------------------------------------------------------ workflows
    def create(self, raw: Any, policy: str) -> Tuple[Dict[str, Any], List[str]]:
        """Register a workflow. Returns the stored document and replaced ids."""
        now = utcnow()
        document = model.normalise_workflow(raw, now)
        replaced: List[str] = []
        existing = list(self.workflows.find({"name": document["name"]}, {"_id": 1}))
        if existing and policy == "reject":
            raise Conflict("Workflow with name %s already exists" % document["name"])
        if existing and policy == "replace":
            for item in existing:
                self.delete(str(item["_id"]))
                replaced.append(str(item["_id"]))
        result = self.workflows.insert_one(document)
        document["_id"] = result.inserted_id
        self.record_event(str(result.inserted_id), "workflow.created", data={
            "name": document["name"], "tasks": len(document["tasks"]), "replaced": replaced})
        return document, replaced

    def get(self, workflow_id: str) -> Dict[str, Any]:
        document = self.workflows.find_one({"_id": parse_id(workflow_id)})
        if document is None:
            raise NotFound("Workflow %s does not exist" % workflow_id)
        return document

    def find_latest_by_name(self, name: str) -> Dict[str, Any]:
        cursor = self.workflows.find({"name": name}).sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(1)
        for document in cursor:
            return document
        raise NotFound("Workflow %s does not exist" % name)

    def list(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if name:
            query["name"] = name
        return list(self.workflows.find(query).sort([("created_at", DESCENDING), ("_id", DESCENDING)]))

    def delete(self, workflow_id: str) -> None:
        oid = parse_id(workflow_id)
        result = self.workflows.delete_one({"_id": oid})
        if result.deleted_count == 0:
            raise NotFound("Workflow %s does not exist" % workflow_id)
        self.events.delete_many({"workflow_id": workflow_id})
        self.workflows.update_many({"subscribers": workflow_id}, {"$pull": {"subscribers": workflow_id}})

    # ---------------------------------------------------------------- tasks
    def _task_path(self, task: str) -> str:
        model.check_name(task, "task name")
        return "tasks." + encode_key(task)

    def _update_task(self, workflow_id: str, task: str, update: Dict[str, Any]) -> Dict[str, Any]:
        """Apply *update* atomically when both the workflow and the task exist."""
        oid = parse_id(workflow_id)
        path = self._task_path(task)
        document = self.workflows.find_one_and_update(
            {"_id": oid, path: {"$exists": True}}, update, return_document=ReturnDocument.AFTER)
        if document is None:
            if self.workflows.count_documents({"_id": oid}, limit=1) == 0:
                raise NotFound("Workflow %s does not exist" % workflow_id)
            raise NotFound("Task %s does not exist in workflow %s" % (task, workflow_id))
        return document

    def get_task(self, workflow_id: str, task: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        document = self.get(workflow_id)
        stored = document.get("tasks", {}).get(encode_key(model.check_name(task, "task name")))
        if stored is None:
            raise NotFound("Task %s does not exist in workflow %s" % (task, workflow_id))
        return document, stored

    def add_task(self, workflow_id: str, raw: Any) -> Tuple[Dict[str, Any], bool]:
        now = utcnow()
        task = model.normalise_task(raw, now)
        oid = parse_id(workflow_id)
        path = "tasks." + encode_key(task["name"])
        before = self.workflows.find_one_and_update(
            {"_id": oid}, {"$set": {path: task, "updated_at": now}},
            projection={path: 1}, return_document=ReturnDocument.BEFORE)
        if before is None:
            raise NotFound("Workflow %s does not exist" % workflow_id)
        created = encode_key(task["name"]) not in before.get("tasks", {})
        self.record_event(workflow_id, "task.added", task=task["name"], status=task["status"],
                          data={"type": task["type"], "replaced": not created})
        return task, created

    def set_status(self, workflow_id: str, task: str, status: Any) -> Dict[str, Any]:
        value = model.normalise_status(status)
        now = utcnow()
        path = self._task_path(task)
        document = self._update_task(workflow_id, task, {
            "$set": {path + ".status": value, path + ".updated_at": now, "updated_at": now},
            "$push": {path + ".history": {"$each": [{"status": value, "at": now}], "$slice": -self.max_history}},
        })
        self.record_event(workflow_id, "task.status", task=task, status=value)
        return document

    def set_attribute(self, workflow_id: str, task: str, parameter: str, value: Any) -> Dict[str, Any]:
        model.check_parameter(parameter)
        now = utcnow()
        path = self._task_path(task)
        document = self._update_task(workflow_id, task, {
            "$set": {path + "." + parameter: value, path + ".updated_at": now, "updated_at": now}})
        self.record_event(workflow_id, "task.updated", task=task, data={"attribute": parameter, "value": value})
        return document

    def add_dependency(self, workflow_id: str, task: str, dependency: str) -> bool:
        """Add the edge ``dependency -> task``.

        When *dependency* is not a task of this workflow it is a *transversal
        point* (a task of another registered workflow): only ``prevs`` is
        updated, exactly as DAGonStar does for ``add_transversal_point``.
        Returns ``True`` for a transversal edge.
        """
        model.check_name(dependency, "dependency name")
        if dependency == task:
            raise ValidationError("a task cannot depend on itself")
        now = utcnow()
        path = self._task_path(task)
        document = self._update_task(workflow_id, task, {
            "$addToSet": {path + ".prevs": dependency}, "$set": {"updated_at": now}})
        dependency_key = encode_key(dependency)
        transversal = dependency_key not in document.get("tasks", {})
        if not transversal:
            self.workflows.update_one({"_id": document["_id"]},
                                      {"$addToSet": {"tasks." + dependency_key + ".nexts": task}})
        self.record_event(workflow_id, "task.dependency", task=task,
                          data={"dependency": dependency, "transversal": transversal})
        return transversal

    def subscribe(self, subscriber_id: str, target_id: str) -> None:
        self.get(subscriber_id)  # must exist
        result = self.workflows.update_one({"_id": parse_id(target_id)},
                                           {"$addToSet": {"subscribers": subscriber_id}})
        if result.matched_count == 0:
            raise NotFound("Workflow %s does not exist" % target_id)
        self.record_event(target_id, "workflow.subscribed", data={"subscriber": subscriber_id})

    # --------------------------------------------------------------- events
    def record_event(self, workflow_id: str, kind: str, task: Optional[str] = None,
                     status: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        event: Dict[str, Any] = {"workflow_id": workflow_id, "kind": kind, "at": utcnow()}
        if task is not None:
            event["task"] = task
        if status is not None:
            event["status"] = status
        if data:
            event["data"] = data
        result = self.events.insert_one(event)
        event["_id"] = result.inserted_id
        if self.on_event is not None:
            try:
                self.on_event(event_to_json(event))
            except Exception as exc:  # notifications never break the request
                LOG.warning("Event listener failed: %s", exc)
        return event

    def list_events(self, workflow_id: str, after: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        self.get(workflow_id)
        query: Dict[str, Any] = {"workflow_id": workflow_id}
        if after:
            query["_id"] = {"$gt": parse_id(after)}
        return list(self.events.find(query).sort("_id", ASCENDING).limit(limit))


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _created_at(document: Dict[str, Any]) -> Optional[_dt.datetime]:
    created = document.get("created_at")
    if isinstance(created, _dt.datetime):
        return created
    legacy = document.get("creation_at")  # schema 1 (2018 prototype)
    if isinstance(legacy, str):
        try:
            return _dt.datetime.strptime(legacy, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None


def _time(value: Any) -> Any:
    return isoformat(value) if isinstance(value, _dt.datetime) else value


def task_to_json(task: Dict[str, Any], include_history: bool = True) -> Dict[str, Any]:
    out = {key: _time(value) for key, value in task.items() if key != "history"}
    if include_history:
        out["history"] = [{"status": item.get("status"), "at": _time(item.get("at", item.get("datetime")))}
                          for item in task.get("history", [])]
    return out


def tasks_of(document: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {decode_key(key): value for key, value in document.get("tasks", {}).items()}


def workflow_to_json(document: Dict[str, Any], include_tasks: bool = True,
                     include_history: bool = True) -> Dict[str, Any]:
    """Public JSON form. Keeps every key of the 2018 response for compatibility."""
    tasks = tasks_of(document)
    statuses = [task.get("status", "READY") for task in tasks.values()]
    created = _created_at(document)
    out: Dict[str, Any] = {
        "id": str(document["_id"]),
        "name": document.get("name"),
        "host": document.get("host"),
        "status": model.aggregate_status(statuses),
        "counts": model.status_counts(statuses),
        "task_count": len(tasks),
        "created_at": isoformat(created) if created else None,
        "updated_at": _time(document.get("updated_at")) or (isoformat(created) if created else None),
        "creation_at": legacy_timestamp(created) if created else document.get("creation_at"),
        "subscribers": list(document.get("subscribers", [])),
    }
    if "pre_stage" in document:
        out["pre_stage"] = document["pre_stage"]
    if include_tasks:
        out["tasks"] = {name: task_to_json(task, include_history) for name, task in tasks.items()}
    return out


def workflow_to_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return the DAGonStar task-map document, as ``Workflow.as_json()`` wrote it.

    Service bookkeeping is removed and any additive extension is restored, so
    the result can be loaded with ``dagon.Workflow(..., jsonload=...)`` or
    imported into DAGonWeb.
    """
    out: Dict[str, Any] = dict(document.get("extra", {}))
    out.update({"name": document.get("name"), "id": str(document["_id"]), "host": document.get("host")})
    if "pre_stage" in document:
        out["pre_stage"] = document["pre_stage"]
    out["tasks"] = {name: {key: value for key, value in task.items() if key not in model.SERVICE_TASK_FIELDS}
                    for name, task in tasks_of(document).items()}
    return out


def workflow_graph(document: Dict[str, Any]) -> Dict[str, Any]:
    """Nodes and edges of the workflow, with transversal edges marked."""
    tasks = tasks_of(document)
    nodes = [{"id": name, "type": task.get("type"), "status": task.get("status", "READY")}
             for name, task in tasks.items()]
    edges = []
    for name, task in tasks.items():
        explicit = set(task.get("explicit_prevs", []))
        for previous in task.get("prevs", []):
            edges.append({"source": previous, "target": name,
                          "kind": "explicit" if previous in explicit else "dependency",
                          "transversal": previous not in tasks})
    return {"nodes": nodes, "edges": edges}


def event_to_json(event: Dict[str, Any]) -> Dict[str, Any]:
    out = {"id": str(event["_id"]), "workflow_id": event.get("workflow_id"), "kind": event.get("kind"),
           "at": _time(event.get("at"))}
    for key in ("task", "status", "data"):
        if key in event:
            out[key] = event[key]
    return out
