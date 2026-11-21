# API reference

All request and response bodies are JSON (`Content-Type: application/json`)
unless stated otherwise. Every error has the form

```json
{"status": "error", "message": "Task Z does not exist in workflow 6b01…"}
```

with HTTP 400 (invalid input), 401 (token required), 404 (unknown workflow,
task, route, or malformed id), 405 (method), 409 (duplicate rejected) or 500.
When an API token is configured, requests that need it carry
`Authorization: Bearer <token>` or `X-API-Key: <token>` (see
[Security](security.md)).

## Legacy routes — the DAGonStar contract

These routes are called by `dagon.api.API` in DAGonStar 3.0. Their paths,
methods and success codes are frozen; the table lists the DAGonStar method
that calls each one.

| Method and path | Caller | Success response |
| --- | --- | --- |
| `GET`/`HEAD /check` | `API.checkConnection` | `200 {"status": "ok"}` |
| `POST /create` | `API.create_workflow` | `201 {"id": "<id>"}`; `409` under the `reject` policy |
| `POST /add_task/<id>` | `API.add_task` | `201` (new task) or `200` (replaced) `{"status": "ok", "message": "ok"}` |
| `PUT /changestatus/<id>/<task>/<status>` | `API.update_task_status` | `200 {"status": "ok"}` |
| `PUT /update/<id>/<task>/<attribute>?value=<v>` | `API.update_task` | `200 {"status": "ok"}` |
| `PUT /<id>/<task>/dependency/<dependency>` | `API.add_dependency` | `200 {"status": "ok", "transversal": false}` |
| `GET /getworkflow/<name>` | `API.get_workflow_by_name` | `200` id of the newest workflow with that name, **as `text/plain`** |
| `GET /<id>/<task>` | `API.get_task` | `200 {"status": "ok", "task": {…}, "host": "<host>"}` |
| `GET /<id>` | — | `200` workflow (see *Workflow representation*) |
| `GET /list` | — | `200` array of workflows |
| `GET /subscribe/<subscriber>/<target>/<task>` | — | `200 {"status": "ok"}`; also accepts `PUT` and `POST` |
| `GET`/`DELETE /delete/<id>` | — | `200 {"status": "ok"}` |

Notes:

- `/update` refuses the attributes `name`, `status`, `history`, `prevs`,
  `nexts` and `explicit_prevs` (use the dedicated operations) and any name that
  is not an identifier (`[A-Za-z_][A-Za-z0-9_]*`, at most 64 characters). The
  value is stored as a string. DAGonStar uses it for `working_dir`.
- Unlike the prototype, an unknown task now yields 404 everywhere instead of
  being created implicitly, and `/delete` of an unknown id yields 404.

## Versioned API — `/api/v1`

### Service

| Method and path | Description |
| --- | --- |
| `GET /api/v1/health` | `200 {"status": "ok", "version", "database": "ok"}`, or `503` with `"database": "unreachable"`. Never requires a token. |
| `GET /api/v1/info` | Version, accepted statuses, and non-secret settings. |

### Workflows

| Method and path | Description |
| --- | --- |
| `GET /api/v1/workflows` | Summaries, newest first. Query: `name` (exact), `status`, `limit` (≤ 500, default 50), `offset`. Returns `{"total", "limit", "offset", "items"}`. |
| `POST /api/v1/workflows` | Register a workflow (same body as `/create`). Returns `201` with the full workflow and `replaced` (ids removed by the `replace` policy). |
| `GET /api/v1/workflows/<id>` | Full workflow. `?history=false` omits task histories. |
| `DELETE /api/v1/workflows/<id>` | Delete the workflow and its events. |
| `GET /api/v1/workflows/by-name/<name>` | Newest workflow with that name. |
| `GET /api/v1/workflows/<id>/document` | The DAGonStar task-map document, without service bookkeeping; `?download=1` adds `Content-Disposition`. Loadable by `dagon.Workflow(jsonload=…)` and importable into DAGonWeb. |
| `GET /api/v1/workflows/<id>/graph` | `{"nodes": [{id, type, status}], "edges": [{source, target, kind, transversal}]}`. |
| `GET /api/v1/workflows/<id>/events` | Events in order. Query: `after` (an event id), `limit` (≤ 1000, default 200). Returns `{"items", "last"}`; pass `last` as `after` on the next poll. |

### Tasks

| Method and path | Description |
| --- | --- |
| `POST /api/v1/workflows/<id>/tasks` | Add or replace a task (body: a DAGonStar task object). |
| `GET /api/v1/workflows/<id>/tasks/<task>` | `{"task", "host", "workflow"}`. |
| `PUT /api/v1/workflows/<id>/tasks/<task>/status` | Body `{"status": "RUNNING"}`. Returns the task. |
| `PATCH /api/v1/workflows/<id>/tasks/<task>` | Body: an object of attributes to set (same rules as `/update`; values keep their JSON type). Returns the task. |
| `PUT /api/v1/workflows/<id>/tasks/<task>/dependencies/<dependency>` | Add an edge; returns `{"status": "ok", "transversal"}`. |

## Workflow representation

```json
{
  "id": "6b018f82ad62972b110f38ba",
  "name": "Ocean-forecast",
  "host": "hpc-login",
  "status": "RUNNING",
  "counts": {"READY": 2, "WAITING": 0, "RUNNING": 1, "FINISHED": 1, "FAILED": 0},
  "task_count": 4,
  "created_at": "2026-11-21T12:33:06.123000Z",
  "updated_at": "2026-11-21T12:34:10.002000Z",
  "creation_at": "2026-11-21 12:33:06",
  "subscribers": [],
  "pre_stage": true,
  "tasks": {
    "wrf.run": {
      "name": "wrf.run", "type": "slurm", "command": "…", "working_dir": "/scratch/run_42/wrf.run",
      "status": "RUNNING", "prevs": ["fetch"], "nexts": ["post"], "explicit_prevs": [],
      "updated_at": "…", "history": [{"status": "READY", "at": "…"}, {"status": "RUNNING", "at": "…"}]
    }
  }
}
```

`creation_at` (UTC, `YYYY-MM-DD HH:MM:SS` without a zone designator) is kept for clients of the
prototype; new clients should use `created_at` (UTC, ISO 8601). Summaries in
`GET /api/v1/workflows` omit `tasks`.

## Webhook payload

When `DAGONSERVICE_WEBHOOK_URLS` is set, every event is POSTed to each URL:

```json
{"id": "6b01…", "workflow_id": "6b01…", "kind": "task.status", "at": "2026-11-21T12:34:10Z",
 "task": "wrf.run", "status": "FAILED"}
```

Delivery is at most once, best-effort, with a short timeout and no retry; use
the events endpoint when completeness matters.

## Examples

```bash
S=http://localhost:57000
ID=$(curl -s -X POST $S/create -H 'Content-Type: application/json' \
  -d '{"name": "demo", "host": "localhost", "tasks": {"A": {"name": "A", "type": "batch", "command": "true"}}}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -X PUT $S/changestatus/$ID/A/RUNNING
curl -s "$S/api/v1/workflows/$ID/events"
curl -s -X PUT $S/api/v1/workflows/$ID/tasks/A/status -H 'Content-Type: application/json' -d '{"status": "FINISHED"}'
curl -s "$S/api/v1/workflows?status=FINISHED"
```
