"""HTTP interface.

Two route families share one implementation:

* the **legacy routes** (``/create``, ``/changestatus/...``, ``/<id>/<task>``,
  ...) are the exact contract of ``dagon.api.API`` in DAGonStar 3.0, and must
  keep their paths, methods, status codes and response shapes;
* the **versioned API** under ``/api/v1`` is resource-oriented and is what the
  dashboard, DAGonWeb and other monitors should use.
"""

from __future__ import annotations

import hmac
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Response, current_app, jsonify, request

from . import __version__, model
from .storage import (Conflict, NotFound, WorkflowStore, event_to_json, task_to_json, workflow_graph,
                      workflow_to_document, workflow_to_json)

legacy = Blueprint("legacy", __name__)
v1 = Blueprint("v1", __name__, url_prefix="/api/v1")

JsonResponse = Tuple[Response, int]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def store() -> WorkflowStore:
    return current_app.extensions["dagonservice.store"]


def settings():
    return current_app.extensions["dagonservice.settings"]


def error(message: str, code: int) -> JsonResponse:
    return jsonify({"status": "error", "message": message}), code


def json_body() -> Any:
    body = request.get_json(silent=True)
    if body is None:
        raise model.ValidationError("expected a JSON request body")
    return body


def _authorised() -> bool:
    token = settings().api_token
    if token is None:
        return True
    if request.method in ("GET", "HEAD", "OPTIONS") and not settings().protect_reads:
        return True
    header = request.headers.get("Authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else request.headers.get("X-API-Key", "")
    return bool(supplied) and hmac.compare_digest(supplied.encode(), token.encode())


def register_error_handlers(app) -> None:
    @app.before_request
    def _check_token() -> Optional[JsonResponse]:
        if request.endpoint in (None, "static", "legacy.check", "v1.health"):
            return None
        if not _authorised():
            response, code = error("authentication required", 401)
            response.headers["WWW-Authenticate"] = 'Bearer realm="DAGonService"'
            return response, code
        return None

    @app.errorhandler(NotFound)
    def _not_found(exc: NotFound) -> JsonResponse:
        return error(exc.message, 404)

    @app.errorhandler(model.ValidationError)
    def _invalid(exc: model.ValidationError) -> JsonResponse:
        return error(str(exc), 400)

    @app.errorhandler(Conflict)
    def _conflict(exc: Conflict) -> JsonResponse:
        return error(str(exc), 409)

    @app.errorhandler(404)
    def _route_not_found(_exc) -> JsonResponse:
        return error("Not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc) -> JsonResponse:
        return error("Method not allowed", 405)

    @app.errorhandler(500)
    def _internal(_exc) -> JsonResponse:
        return error("Internal server error", 500)


# --------------------------------------------------------------------------- #
# Legacy routes: the DAGonStar 3.0 ``dagon.api.API`` contract
# --------------------------------------------------------------------------- #

@legacy.route("/check", methods=["GET"])
def check() -> Response:
    """Liveness probe. DAGonStar calls ``HEAD /check`` when a workflow starts."""
    return jsonify({"status": "ok"})


@legacy.route("/create", methods=["POST"])
def create() -> JsonResponse:
    """Register ``Workflow.as_json()``; returns ``201 {"id": ...}``."""
    document, _replaced = store().create(json_body(), settings().duplicate_policy)
    return jsonify({"id": str(document["_id"])}), 201


@legacy.route("/add_task/<workflow_id>", methods=["POST"])
def add_task(workflow_id: str) -> JsonResponse:
    _task, created = store().add_task(workflow_id, json_body())
    return jsonify({"status": "ok", "message": "ok"}), (201 if created else 200)


@legacy.route("/changestatus/<workflow_id>/<task>/<status_code>", methods=["PUT"])
def change_status(workflow_id: str, task: str, status_code: str) -> Response:
    store().set_status(workflow_id, task, status_code)
    return jsonify({"status": "ok"})


@legacy.route("/update/<workflow_id>/<task>/<parameter>", methods=["PUT"])
def update_task(workflow_id: str, task: str, parameter: str) -> Response:
    if "value" not in request.args:
        raise model.ValidationError("missing 'value' query parameter")
    store().set_attribute(workflow_id, task, parameter, request.args.get("value"))
    return jsonify({"status": "ok"})


@legacy.route("/<workflow_id>/<task>/dependency/<dependency>", methods=["PUT"])
def add_dependency(workflow_id: str, task: str, dependency: str) -> Response:
    transversal = store().add_dependency(workflow_id, task, dependency)
    return jsonify({"status": "ok", "transversal": transversal})


@legacy.route("/getworkflow/<workflow_name>", methods=["GET"])
def get_workflow_by_name(workflow_name: str) -> Response:
    """Return the id of the most recent workflow with this name, as plain text."""
    document = store().find_latest_by_name(workflow_name)
    return Response(str(document["_id"]), mimetype="text/plain")


@legacy.route("/subscribe/<subscriber_id>/<to_id>/<task>", methods=["GET", "PUT", "POST"])
def subscribe(subscriber_id: str, to_id: str, task: str) -> Response:
    store().subscribe(subscriber_id, to_id)
    return jsonify({"status": "ok", "message": "ok"})


@legacy.route("/list", methods=["GET"])
def list_workflows() -> Response:
    return jsonify([workflow_to_json(document) for document in store().list()])


@legacy.route("/delete/<workflow_id>", methods=["GET", "DELETE"])
def delete(workflow_id: str) -> Response:
    store().delete(workflow_id)
    return jsonify({"status": "ok"})


@legacy.route("/<workflow_id>/<task>", methods=["GET"])
def get_task(workflow_id: str, task: str) -> Response:
    """Used by DAGonStar to resolve transversal ``workflow://`` references."""
    document, stored = store().get_task(workflow_id, task)
    return jsonify({"status": "ok", "task": task_to_json(stored), "host": document.get("host")})


@legacy.route("/<workflow_id>", methods=["GET"])
def get_workflow(workflow_id: str) -> Response:
    return jsonify(workflow_to_json(store().get(workflow_id)))


# --------------------------------------------------------------------------- #
# Versioned API
# --------------------------------------------------------------------------- #

def _bounded_int(name: str, default: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise model.ValidationError("%s must be an integer" % name)
    if value < 0 or value > maximum:
        raise model.ValidationError("%s must be between 0 and %d" % (name, maximum))
    return value


@v1.route("/health", methods=["GET"])
def health() -> JsonResponse:
    database = store().ping()
    body: Dict[str, Any] = {"status": "ok" if database else "degraded", "version": __version__,
                            "database": "ok" if database else "unreachable"}
    return jsonify(body), (200 if database else 503)


@v1.route("/info", methods=["GET"])
def info() -> Response:
    return jsonify({"service": "DAGonService", "version": __version__, "statuses": list(model.STATUSES),
                    "settings": settings().public()})


@v1.route("/workflows", methods=["GET"])
def v1_list() -> Response:
    name = request.args.get("name") or None
    wanted = request.args.get("status")
    status = model.normalise_status(wanted) if wanted else None
    limit = _bounded_int("limit", 50, 500)
    offset = _bounded_int("offset", 0, 10 ** 6)
    items = [workflow_to_json(document, include_tasks=False) for document in store().list(name)]
    if status:
        items = [item for item in items if item["status"] == status]
    return jsonify({"total": len(items), "limit": limit, "offset": offset, "items": items[offset:offset + limit]})


@v1.route("/workflows", methods=["POST"])
def v1_create() -> JsonResponse:
    document, replaced = store().create(json_body(), settings().duplicate_policy)
    body = workflow_to_json(document)
    body["replaced"] = replaced
    return jsonify(body), 201


@v1.route("/workflows/<workflow_id>", methods=["GET"])
def v1_get(workflow_id: str) -> Response:
    history = request.args.get("history", "true").lower() not in {"0", "false", "no"}
    return jsonify(workflow_to_json(store().get(workflow_id), include_history=history))


@v1.route("/workflows/<workflow_id>", methods=["DELETE"])
def v1_delete(workflow_id: str) -> JsonResponse:
    store().delete(workflow_id)
    return jsonify({"status": "ok"}), 200


@v1.route("/workflows/<workflow_id>/document", methods=["GET"])
def v1_document(workflow_id: str) -> Response:
    """DAGonStar task-map JSON, loadable by ``dagon.Workflow`` and DAGonWeb."""
    response = jsonify(workflow_to_document(store().get(workflow_id)))
    if request.args.get("download"):
        name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in store().get(workflow_id)["name"])
        response.headers["Content-Disposition"] = 'attachment; filename="%s.json"' % (name or "workflow")
    return response


@v1.route("/workflows/<workflow_id>/graph", methods=["GET"])
def v1_graph(workflow_id: str) -> Response:
    return jsonify(workflow_graph(store().get(workflow_id)))


@v1.route("/workflows/<workflow_id>/events", methods=["GET"])
def v1_events(workflow_id: str) -> Response:
    after = request.args.get("after") or None
    limit = _bounded_int("limit", 200, 1000)
    events = [event_to_json(event) for event in store().list_events(workflow_id, after=after, limit=limit)]
    return jsonify({"items": events, "last": events[-1]["id"] if events else after})


@v1.route("/workflows/<workflow_id>/tasks", methods=["POST"])
def v1_add_task(workflow_id: str) -> JsonResponse:
    task, created = store().add_task(workflow_id, json_body())
    return jsonify(task_to_json(task)), (201 if created else 200)


@v1.route("/workflows/<workflow_id>/tasks/<task>", methods=["GET"])
def v1_get_task(workflow_id: str, task: str) -> Response:
    document, stored = store().get_task(workflow_id, task)
    return jsonify({"task": task_to_json(stored), "host": document.get("host"), "workflow": document.get("name")})


@v1.route("/workflows/<workflow_id>/tasks/<task>/status", methods=["PUT", "POST"])
def v1_set_status(workflow_id: str, task: str) -> Response:
    body = json_body()
    if not isinstance(body, dict) or "status" not in body:
        raise model.ValidationError("expected {\"status\": ...}")
    store().set_status(workflow_id, task, body["status"])
    _document, stored = store().get_task(workflow_id, task)
    return jsonify(task_to_json(stored))


@v1.route("/workflows/<workflow_id>/tasks/<task>", methods=["PATCH"])
def v1_patch_task(workflow_id: str, task: str) -> Response:
    body = json_body()
    if not isinstance(body, dict) or not body:
        raise model.ValidationError("expected a JSON object of task attributes")
    for parameter in body:
        model.check_parameter(parameter)
    for parameter, value in body.items():
        store().set_attribute(workflow_id, task, parameter, value)
    _document, stored = store().get_task(workflow_id, task)
    return jsonify(task_to_json(stored))


@v1.route("/workflows/<workflow_id>/tasks/<task>/dependencies/<dependency>", methods=["PUT"])
def v1_add_dependency(workflow_id: str, task: str, dependency: str) -> Response:
    transversal = store().add_dependency(workflow_id, task, dependency)
    return jsonify({"status": "ok", "transversal": transversal})


@v1.route("/workflows/by-name/<workflow_name>", methods=["GET"])
def v1_by_name(workflow_name: str) -> Response:
    return jsonify(workflow_to_json(store().find_latest_by_name(workflow_name), include_history=False))
