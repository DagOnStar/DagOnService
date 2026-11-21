# Architecture

## Overview

DAGonService is a Flask application with three layers and one storage back end.

```
 DAGonStar workflows            Monitors (dashboard, DAGonWeb, scripts)
        │  legacy routes                     │  /api/v1
        ▼                                    ▼
 ┌───────────────────────────── api.py ─────────────────────────────┐
 │ request parsing, token check, error mapping, response shaping    │
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────── storage.py ──────────────────────────┐
 │ WorkflowStore: atomic task updates, event log, serialisation     │──► notifier.py ──► webhooks
 └──────────────────────────────┬───────────────────────────────────┘
                                ▼
 ┌──────────────────────────── model.py ────────────────────────────┐
 │ statuses, validation, field-name encoding, aggregate status      │
 └──────────────────────────────────────────────────────────────────┘
                                ▼
                    MongoDB: workflows, events
```

| Module | Responsibility |
| --- | --- |
| `dagonservice/__init__.py` | `create_app()` factory: settings, database, store, notifier, blueprints, security headers, dashboard route. |
| `dagonservice/config.py` | `Settings`, read from `DAGONSERVICE_*` variables (and the legacy `MONGO_DB`). |
| `dagonservice/model.py` | Domain rules with no I/O: the five task states, document validation, task-name encoding, aggregate status. |
| `dagonservice/storage.py` | `WorkflowStore`, the only code that talks to MongoDB, plus the JSON serialisers. |
| `dagonservice/api.py` | The legacy blueprint (DAGonStar contract) and the `v1` blueprint; error handlers; the optional token check. |
| `dagonservice/notifier.py` | Best-effort webhook delivery on a background pool. |
| `dagonservice/templates`, `static` | The dashboard: one HTML page, one stylesheet, one build-free script. |
| `wsgi.py` | Entry point for Gunicorn and `flask run`. |

## Two interfaces over one implementation

The service has two kinds of client with different stability requirements.
The DAGonStar engine embeds an HTTP client (`dagon/api/__init__.py`) whose
paths, verbs and status-code checks were fixed in 2018 and are shipped in
every DAGonStar release. Changing them would break every installed engine. The
**legacy routes** therefore reproduce that contract exactly, including its
idiosyncrasies (a plain-text id from `/getworkflow`, a catch-all
`/<workflow_id>/<task>` path). Monitors, on the other hand, benefit from a
resource-oriented design with pagination, filtering and incremental events;
this is the **`/api/v1`** interface. Both are thin adapters over the same
`WorkflowStore` methods, so they cannot drift apart semantically. The legacy
blueprint is registered last so that its catch-all patterns never shadow
`/api/v1`, `/static` or the dashboard.

## Concurrency and consistency

DAGonStar executes each task in its own thread and every thread reports its own
transitions, so a workflow with *n* parallel tasks produces bursts of up to
*n* concurrent `PUT /changestatus` requests against the same document. The
service is deployed with several Gunicorn worker processes and threads, so
these requests are processed truly concurrently.

A design that reads the workflow, modifies it in Python and writes it back —
the approach the prototype used for adding tasks, dependencies and
subscribers — loses updates under this load: two requests read the same
version, and the second write silently discards the first. Version 2 avoids
read-modify-write entirely. Every mutation is a single MongoDB update on a
dotted path such as `tasks.<encoded name>.status`, combined with operators that
are atomic at document level (`$set`, `$push` with `$slice`, `$addToSet`,
`$pull`). The filter of each update also requires the task to exist
(`{"tasks.<name>": {"$exists": true}}`), so an update for an unknown task fails
instead of creating a phantom task. The test
`test_concurrent_status_updates_are_not_lost` exercises this with twenty
concurrent tasks.

The aggregate workflow status is never stored: it is derived on each read from
the task states. Storing it would require a second write that could interleave
with concurrent reports and leave a stale value; computing it costs a pass over
a few dozen tasks.

## Request life cycle

1. `before_request` applies the optional token check (see [Security](security.md)).
2. The view function parses path parameters and the JSON body, and calls one
   `WorkflowStore` method.
3. `model` validates the input; violations raise `ValidationError` (HTTP 400).
4. The store performs one atomic update, records an event, and returns the
   updated document; missing workflows or tasks raise `NotFound` (404); a
   rejected duplicate raises `Conflict` (409).
5. The event is passed to the notifier, which queues webhook deliveries without
   blocking the request.
6. The view serialises the result. Every error, including unknown routes and
   unhandled exceptions, is returned as `{"status": "error", "message": …}`.

## Design decisions

- **MongoDB is kept.** The workflow document is a nested, schema-flexible JSON
  object whose task fields vary with the task type. A document database stores
  it natively, and the prototype's deployments already hold data in MongoDB.
- **Unknown task fields are preserved.** New DAGonStar task types add fields;
  the service stores and returns them verbatim, which is what allows the
  `/document` export to be reloaded by DAGonStar and DAGonWeb.
- **No execution, no data movement.** The service never stages files or runs
  commands; see [Introduction](introduction.md#what-the-service-is-and-what-it-is-not).
- **Best-effort notifications.** A webhook receiver that is slow or down must
  not slow down a scientific workflow, so delivery happens off the request path
  and failures are only logged.
- **No build step for the dashboard.** As in DAGonWeb, the front end is plain
  browser JavaScript that inserts server data with `textContent` only.
