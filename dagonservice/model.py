"""Domain model: task states, field-name encoding, and document validation.

DAGonService stores the DAGonStar *task-map* document that
``dagon.Workflow.as_json()`` produces: a JSON object whose ``tasks`` member maps
task names to task objects. This module validates that document, encodes task
names so that they are safe MongoDB field names, and derives the aggregate
status of a workflow from the status of its tasks.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

#: Task states defined by ``dagon.Status`` (DAGonStar 3.0).
STATUSES: Tuple[str, ...] = ("READY", "WAITING", "RUNNING", "FINISHED", "FAILED")
TERMINAL_STATUSES = frozenset({"FINISHED", "FAILED"})

#: Document schema written by this version of the service.
SCHEMA_VERSION = 2

#: Task fields that only the service may change through dedicated operations.
PROTECTED_TASK_FIELDS = frozenset({"name", "status", "history", "prevs", "nexts", "explicit_prevs"})

#: Service-only task fields removed when a DAGonStar document is exported.
SERVICE_TASK_FIELDS = frozenset({"history", "updated_at"})

_PARAMETER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MAX_NAME_LENGTH = 256
_LEGACY_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ValidationError(ValueError):
    """Raised when a request body or path parameter is not acceptable."""


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def isoformat(moment: _dt.datetime) -> str:
    if moment.tzinfo is None:  # pymongo returns naive UTC datetimes by default
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def legacy_timestamp(moment: _dt.datetime) -> str:
    """Timestamp in the format of the 2018 prototype's ``creation_at`` field."""
    return moment.strftime(_LEGACY_TIME_FORMAT)


# --------------------------------------------------------------------------- #
# Field-name encoding
# --------------------------------------------------------------------------- #
# MongoDB update paths use "." as a separator and reserve a leading "$" for
# operators. DAGonStar task names are free text, so they are percent-encoded
# before being used as keys of the ``tasks`` sub-document. The encoding is
# reversible and the identity for ordinary names such as "Task_A".

def encode_key(name: str) -> str:
    return name.replace("%", "%25").replace(".", "%2E").replace("$", "%24")


def decode_key(key: str) -> str:
    return key.replace("%24", "$").replace("%2E", ".").replace("%25", "%")


def check_name(value: Any, what: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValidationError("%s must be a non-empty string" % what)
    if len(value) > _MAX_NAME_LENGTH:
        raise ValidationError("%s is longer than %d characters" % (what, _MAX_NAME_LENGTH))
    if "\x00" in value or "/" in value:
        raise ValidationError("%s must not contain '/' or NUL characters" % what)
    return value


def normalise_status(value: Any) -> str:
    """Return the canonical upper-case status or raise :class:`ValidationError`."""
    if not isinstance(value, str):
        raise ValidationError("status must be a string")
    status = value.strip().upper()
    # DAGonStar clients send ``Status.name``; accept ``Status.<NAME>`` too.
    if status.startswith("STATUS."):
        status = status[len("STATUS."):]
    if status not in STATUSES:
        raise ValidationError("unknown status %r; expected one of %s" % (value, ", ".join(STATUSES)))
    return status


def check_parameter(parameter: str) -> str:
    if not _PARAMETER_RE.match(parameter or ""):
        raise ValidationError("invalid task attribute name %r" % parameter)
    if parameter in PROTECTED_TASK_FIELDS:
        raise ValidationError(
            "task attribute %r cannot be set directly; use the status or dependency operations" % parameter)
    return parameter


def _string_list(value: Any, what: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError("%s must be a list of task names" % what)
    seen: List[str] = []
    for item in value:  # keep order, drop duplicates
        if item not in seen:
            seen.append(item)
    return seen


def normalise_task(raw: Any, now: _dt.datetime, name: Optional[str] = None) -> Dict[str, Any]:
    """Validate one DAGonStar task object and add the service bookkeeping.

    Unknown keys are kept verbatim: DAGonStar task subclasses add their own
    fields (``function``, ``agentic``, ``volume``, ...), and the exported
    document must give them back unchanged.
    """
    if not isinstance(raw, Mapping):
        raise ValidationError("a task must be a JSON object")
    task = dict(raw)
    task_name = check_name(task.get("name", name), "task name")
    if name is not None and task_name != name:
        raise ValidationError("task key %r does not match its name %r" % (name, task_name))
    task["name"] = task_name
    task_type = task.get("type", "batch")
    if not isinstance(task_type, str) or not task_type.strip():
        raise ValidationError("task %r: type must be a non-empty string" % task_name)
    task["type"] = task_type
    task.setdefault("command", None)
    task.setdefault("working_dir", None)
    task["status"] = normalise_status(task.get("status", "READY"))
    for key in ("prevs", "nexts", "explicit_prevs"):
        task[key] = _string_list(task.get(key), "task %r: %s" % (task_name, key))
    task["history"] = [{"status": task["status"], "at": now}]
    task["updated_at"] = now
    return task


def normalise_workflow(raw: Any, now: _dt.datetime) -> Dict[str, Any]:
    """Validate the body of a registration request (``Workflow.as_json()``)."""
    if not isinstance(raw, Mapping):
        raise ValidationError("the request body must be a JSON object")
    name = check_name(raw.get("name"), "workflow name")
    tasks_raw = raw.get("tasks", {})
    if tasks_raw is None:
        tasks_raw = {}
    if isinstance(tasks_raw, list):  # tolerate a list of task objects
        tasks_raw = {item.get("name") if isinstance(item, Mapping) else None: item for item in tasks_raw}
    if not isinstance(tasks_raw, Mapping):
        raise ValidationError("tasks must be an object keyed by task name")
    tasks: Dict[str, Any] = {}
    for key, value in tasks_raw.items():
        task = normalise_task(value, now, name=key if isinstance(key, str) else None)
        tasks[encode_key(task["name"])] = task
    host = raw.get("host")
    if host is not None and not isinstance(host, str):
        raise ValidationError("host must be a string")
    document: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "host": host,
        "tasks": tasks,
        "subscribers": [],
        "created_at": now,
        "updated_at": now,
    }
    if "pre_stage" in raw:
        document["pre_stage"] = raw["pre_stage"]
    # Keep any additive extension (for example DAGonWeb's ``dagonweb`` member).
    extra = {key: value for key, value in raw.items()
             if key not in {"name", "host", "tasks", "id", "pre_stage", "_id"} and not key.startswith("$")}
    if extra:
        document["extra"] = extra
    return document


def aggregate_status(statuses: Iterable[str]) -> str:
    """Derive the status of a workflow from the status of its tasks.

    The rule mirrors how DAGonStar reports a run: any failure fails the
    workflow; it is finished only when every task finished; it is running as
    soon as one task has started; otherwise it is waiting (or ready when no
    task has left the initial state).
    """
    values = list(statuses)
    if not values:
        return "READY"
    if "FAILED" in values:
        return "FAILED"
    if all(value == "FINISHED" for value in values):
        return "FINISHED"
    if "RUNNING" in values or "FINISHED" in values:
        return "RUNNING"
    if "WAITING" in values:
        return "WAITING"
    return "READY"


def status_counts(statuses: Iterable[str]) -> Dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for value in statuses:
        counts[value] = counts.get(value, 0) + 1
    return counts
