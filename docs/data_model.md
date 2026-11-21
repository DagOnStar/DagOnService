# Data model

## Collections

The service uses two MongoDB collections in the database named by
`DAGONSERVICE_DB_NAME` (default `dagon`, the name used by the prototype).

| Collection | Content | Indexes |
| --- | --- | --- |
| `workflows` | One document per registration. | `(name, created_at desc)` |
| `events` | One document per observation, in insertion order. | `(workflow_id, _id)` |

## The workflow document

A registration stores the body of `POST /create` — the output of
`dagon.Workflow.as_json()` — after validation, with service bookkeeping added:

```json
{
  "_id": ObjectId("6b018f82ad62972b110f38ba"),
  "schema_version": 2,
  "name": "Ocean-forecast",
  "host": "hpc-login",
  "pre_stage": true,
  "tasks": {
    "fetch":       { "name": "fetch", "type": "slurm", "command": "…", "working_dir": "/scratch/…",
                     "status": "FINISHED", "prevs": [], "nexts": ["wrf%2Erun"], "explicit_prevs": [],
                     "history": [{"status": "READY", "at": ISODate(…)}, …], "updated_at": ISODate(…) },
    "wrf%2Erun":   { "name": "wrf.run", … }
  },
  "subscribers": ["6b01…"],
  "extra": { "dagonweb": { … } },
  "created_at": ISODate(…),
  "updated_at": ISODate(…)
}
```

- `name` is not unique by itself; how a second registration with the same name
  is handled is governed by the duplicate policy (see below).
- `host` is the address DAGonStar takes from `[ftp_pub] ip`; a consumer of a
  transversal reference compares it with its own to decide whether the
  producer's working directory is local or must be fetched.
- `pre_stage` is present only when the workflow enabled scheduler-aware
  pre-staging, exactly as in DAGonStar's own document.
- `extra` keeps any additional top-level member of the registered document —
  notably DAGonWeb's additive `dagonweb` extension — so that it can be
  returned unchanged by the `/document` export.
- Every task keeps all the fields it was registered with. The service adds only
  `history` and `updated_at`, and normalises `status` (upper case) and the three
  dependency lists (lists of unique strings, original order).

### Field-name encoding

MongoDB uses `.` as the separator of update paths and reserves a leading `$`
for operators, while DAGonStar task names are free text. Keys of the `tasks`
sub-document are therefore percent-encoded: `%` → `%25`, `.` → `%2E`,
`$` → `%24`. The encoding is reversible, is the identity for ordinary names,
and is invisible to clients: every response decodes the keys, and the task
object itself always carries the original `name`. Task names must be non-empty,
at most 256 characters, and may not contain `/` (which cannot appear in a URL
path segment) or NUL.

## Task states and history

The service accepts exactly the five states of `dagon.Status`:

| State | Meaning in DAGonStar |
| --- | --- |
| `READY` | Created and not yet scheduled. |
| `WAITING` | Waiting for its predecessors to finish. |
| `RUNNING` | Staging inputs, executing, or staging outputs. |
| `FINISHED` | Completed successfully. Terminal. |
| `FAILED` | Completed with an error, or a predecessor failed. Terminal. |

Reports are case-insensitive and `Status.RUNNING` is accepted as a synonym of
`RUNNING`; anything else is rejected with HTTP 400. Each accepted report sets
`status` and appends `{"status", "at"}` to `history`. History is bounded by
`DAGONSERVICE_MAX_HISTORY` (default 1000 entries per task, oldest discarded),
which protects the 16 MB document limit from long-lived workflows that are
re-run in place.

The service does not enforce a transition graph. DAGonStar legitimately
re-enters earlier states — a checkpoint resume moves a `FAILED` task back to
`READY` — and the purpose of the history is to record what was observed, not to
judge it.

## Aggregate status

The status of a workflow is computed on every read from the states of its
tasks, in this order of precedence:

1. no tasks → `READY`;
2. any task `FAILED` → `FAILED`;
3. every task `FINISHED` → `FINISHED`;
4. any task `RUNNING`, or some but not all `FINISHED` → `RUNNING`;
5. any task `WAITING` → `WAITING`;
6. otherwise → `READY`.

Rule 2 precedes rule 4 deliberately: DAGonStar marks the downstream tasks of a
failure as failed, and an operator needs to see the failure even while
independent branches are still running. Responses also include `counts`, the
number of tasks in each state.

## Dependencies and transversal points

`PUT /<id>/<task>/dependency/<dependency>` adds `dependency` to the task's
`prevs` and, when `dependency` is a task of the same workflow, adds `task` to
its `nexts`. Both use `$addToSet`, so DAGonStar may report the same edge every
time `make_dependencies()` runs. When `dependency` is not a task of the
workflow it is a *transversal point*: only `prevs` is updated and the response
says `"transversal": true`. The `/graph` endpoint marks each edge as
`explicit` (present in `explicit_prevs`) or `dependency`, and flags
transversal edges.

## Duplicate names

Re-running a DAGonStar program creates a new `Workflow` object with the same
name, which registers again. `DAGONSERVICE_DUPLICATE_POLICY` decides what
happens:

| Policy | Behaviour | Use when |
| --- | --- | --- |
| `replace` (default) | Older registrations with that name, and their events, are deleted. | Development, and operational chains where only the latest run matters. Matches the prototype, which always ran in debug mode. |
| `reject` | The registration fails with HTTP 409, and DAGonStar raises at `Workflow(...)`. | Names must be unique, for example when other workflows hold transversal references by name. |
| `keep` | All registrations are kept; name lookups return the most recent. | A full run history is wanted. |

## Events

Every mutation appends an event:

| `kind` | Recorded when | Extra members |
| --- | --- | --- |
| `workflow.created` | A workflow is registered. | `data.name`, `data.tasks`, `data.replaced` |
| `task.added` | `add_task` is called. | `task`, `status`, `data.type`, `data.replaced` |
| `task.status` | A status report is accepted. | `task`, `status` |
| `task.updated` | A task attribute is set. | `task`, `data.attribute`, `data.value` |
| `task.dependency` | An edge is added. | `task`, `data.dependency`, `data.transversal` |
| `workflow.subscribed` | A subscriber is added. | `data.subscriber` |

Event identifiers are MongoDB ObjectIds and increase monotonically, so a
monitor polls `/api/v1/workflows/<id>/events?after=<last id>` to receive only
new events. Events are deleted with their workflow.

## Documents written by the prototype

Documents created before version 2 (no `schema_version`) remain readable: the
legacy `creation_at` string is used when `created_at` is absent, missing
`history` reads as empty, and the legacy `datetime` member of old history
entries is returned as `at`. Task names in those documents were stored
unencoded; names without `.`, `$` or `%` — the only ones the prototype could
update — are unaffected. `flask --app wsgi upgrade-documents` converts such
documents to schema version 2 in place; see
[Deployment](deployment.md#migrating-the-data).
