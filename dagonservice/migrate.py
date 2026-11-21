"""Upgrade workflow documents written by the 2018 prototype to schema version 2.

Run it once after restoring a prototype database::

    flask --app wsgi upgrade-documents            # or
    python -m dagonservice.migrate

The upgrade is idempotent: documents that already carry ``schema_version``
are left untouched, so it is safe to run repeatedly.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Optional

from . import model
from .model import encode_key


def _parse_legacy_time(value: Any) -> Optional[_dt.datetime]:
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if isinstance(value, str):
        try:
            return _dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            return None
    return None


def _status(value: Any) -> str:
    try:
        return model.normalise_status(value)
    except model.ValidationError:
        return "READY"


def _strings(value: Any) -> list:
    out: list = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str) and item not in out:
            out.append(item)
    return out


def upgrade_document(document: Dict[str, Any], now: _dt.datetime) -> Dict[str, Any]:
    """Return the schema-2 form of a prototype document (``_id`` preserved)."""
    created = _parse_legacy_time(document.get("creation_at")) or now
    tasks: Dict[str, Any] = {}
    for key, raw in (document.get("tasks") or {}).items():
        if not isinstance(raw, dict):
            continue
        task = dict(raw)
        name = task.get("name") if isinstance(task.get("name"), str) and task.get("name") else key
        task["name"] = name
        task.setdefault("type", "batch")
        task.setdefault("command", None)
        task.setdefault("working_dir", None)
        task["status"] = _status(task.get("status", "READY"))
        for field in ("prevs", "nexts", "explicit_prevs"):
            task[field] = _strings(task.get(field))
        history = []
        for entry in task.get("history") or []:
            if isinstance(entry, dict):
                history.append({"status": _status(entry.get("status")),
                                "at": _parse_legacy_time(entry.get("at", entry.get("datetime"))) or created})
        task["history"] = history or [{"status": task["status"], "at": created}]
        task["updated_at"] = task["history"][-1]["at"]
        tasks[encode_key(name)] = task
    upgraded: Dict[str, Any] = {
        "_id": document["_id"],
        "schema_version": model.SCHEMA_VERSION,
        "name": document.get("name"),
        "host": document.get("host"),
        "tasks": tasks,
        "subscribers": _strings(document.get("subscribers")),
        "created_at": created,
        "updated_at": max([created] + [task["updated_at"] for task in tasks.values()]),
        "migrated_from": "prototype",
    }
    if "pre_stage" in document:
        upgraded["pre_stage"] = document["pre_stage"]
    return upgraded


def upgrade_all(database: Any) -> int:
    """Upgrade every prototype document in ``database.workflows``; return the count."""
    collection = database["workflows"]
    now = model.utcnow()
    count = 0
    # An offline, one-off conversion: run it before DAGonStar clients report to
    # the restored database. The filter makes a concurrent second run harmless.
    for document in collection.find({"schema_version": {"$exists": False}}):
        collection.replace_one({"_id": document["_id"], "schema_version": {"$exists": False}},
                               upgrade_document(document, now))
        count += 1
    return count


def main() -> None:  # pragma: no cover - thin wrapper over upgrade_all
    from pymongo import MongoClient

    from .config import Settings

    settings = Settings.from_env()
    client: Any = MongoClient(settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=10000)
    count = upgrade_all(client[settings.db_name])
    print("Upgraded %d workflow document(s) to schema version %d." % (count, model.SCHEMA_VERSION))


if __name__ == "__main__":
    main()
