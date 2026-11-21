# DAGonStar integration

This document describes how the DAGonStar engine uses the service, so that
workflow authors know what to expect and maintainers know which behaviour must
not change. It refers to DAGonStar 3.0.0, the version DAGonWeb pins.

## Enabling the service

The `[dagon_service]` section of `dagon.ini` controls the client:

```ini
[dagon_service]
route = http://localhost:57000
use = True
```

Releases after 3.0.0 also read two optional keys: `token`, the access token of
a service that sets `DAGONSERVICE_API_TOKEN` (the `DAGON_SERVICE_TOKEN`
environment variable is used when the key is absent), and `timeout`, the
seconds after which a request is abandoned (default 10). See
[Client versions](#client-versions).

`use` must be the exact string `True`; any other value disables the client. The
`route` is the base URL, without a trailing slash. If the route is unreachable
when `Workflow(...)` is constructed, DAGonStar logs the connection error and
continues **without** the service; if the service is reachable but rejects the
registration (for example with HTTP 409 under the `reject` policy), the
constructor raises.

`[ftp_pub] ip` is registered as the workflow `host`. Set it to an address that
other machines can reach when you intend to use transversal references across
hosts.

## Client life cycle

| Moment in the DAGonStar program | Request | Notes |
| --- | --- | --- |
| `Workflow(name, config)` | `HEAD /check`, then `POST /create` | The returned id becomes `workflow.workflow_id`. The body contains the tasks known at that moment, usually none. |
| `workflow.add_task(task)` | `POST /add_task/<id>` | Body: `task.as_json()` with `status` `READY`. |
| `task.add_dependency_to(other)` and dependency discovery in `make_dependencies()` | `PUT /<id>/<task>/dependency/<other>` | Repeated on every discovery; the service deduplicates. |
| Every status change (`task.set_status`) | `PUT /changestatus/<id>/<task>/<STATUS>` | Sent from the task's own thread; reports of different tasks arrive concurrently. |
| Scratch directory created | `PUT /update/<id>/<task>/working_dir?value=<path>` | Errors are logged by DAGonStar and do not fail the task. |
| Resolving `workflow://<other workflow>/<task>/<path>` | `GET /getworkflow/<name>`, then `GET /<id>/<task>` | See *Transversal workflows*. |
| Waiting for a transversal predecessor | `GET /<id>/<task>` once per second | Until the task's status is `FINISHED` or `FAILED`. |

A failing status report raises inside the reporting task, so the service must
answer status reports quickly and must accept every state of `dagon.Status`.
These two properties are covered by the tests.

## Transversal workflows

A transversal reference names a task of another workflow:

```python
# Workflow "Simulation", registered earlier (possibly on another machine)
run = DagonTask(TaskType.BATCH, "Run", "./model > out.nc")

# Workflow "Analysis"
plot = DagonTask(TaskType.BATCH, "Plot", "python plot.py workflow://Simulation/Run/out.nc")
```

When DAGonStar cannot find `Simulation` among the workflows of the current
process it asks the service:

1. `GET /getworkflow/Simulation` returns the id of the most recent
   registration with that name;
2. `GET /<id>/Run` returns the task — its `type`, `command`, `working_dir` and
   `status` — and the `host` of the producer;
3. if `host` equals the consumer's own `[ftp_pub] ip`, the producer's
   `working_dir` is used directly; otherwise DAGonStar downloads the task folder
   from the producer's FTP publisher;
4. before running `Plot`, DAGonStar polls `GET /<id>/Run` until its status is
   terminal.

Two consequences follow for operators. First, the producer must report its
`working_dir`, which DAGonStar does automatically when the scratch directory is
created. Second, name resolution depends on the duplicate policy: with
`replace` or `keep`, the newest run of `Simulation` is used, which is normally
what an operational chain wants; with `reject`, a second run of the producer
fails at registration until the first is deleted.

## Client versions

Three client-side defects observed while validating the service were fixed in
DAGonStar after the 3.0.0 release (`dagon/api/__init__.py`, `dagon/task.py`,
`dagon/prestage.py`, `dagon/native.py`, with tests in `tests/test_service_api.py`).
The table states what each client version does.

| Behaviour | DAGonStar 3.0.0 | Later releases |
| --- | --- | --- |
| Access token | Not supported; see [Security](security.md#the-dagonstar-client-and-the-token). | `[dagon_service] token` or `DAGON_SERVICE_TOKEN`, sent as a Bearer token. |
| `working_dir` reports | Value placed unencoded in the query string; `&`, `#` and `+` are altered in transit. | URL-encoded; path segments (task and workflow names) are percent-encoded too. |
| Task names with shell metacharacters (`$`, spaces, quotes) | The scratch directory is named after the task and interpolated unquoted into the launcher, so such a task fails (`cd` into a truncated path). | The scratch directory name keeps only `[A-Za-z0-9._-]` (other characters become `_`), and the launcher's `cd` is quoted. |
| Request timeouts | None: a hung service blocks the reporting task. | `[dagon_service] timeout` seconds (default 10). |

The service handles every case correctly with either client. With 3.0.0, keep
task names to letters, digits, `_`, `-` and `.`.

## Alignment tests

`tests/test_dagonstar_alignment.py` starts a real HTTP server on a free port
and runs unmodified DAGonStar code against it:

- a three-task workflow with a data dependency (`workflow:///Producer/…`), an
  explicit dependency, and a dotted task name, checking that every task ends
  `FINISHED` with its history and working directory recorded, that the edges
  are present, and that the aggregate status is `FINISHED`;
- a failing task, checking that the failure reaches the service and the
  workflow aggregates to `FAILED`;
- the `/document` export, loaded back with `dagon.Workflow(jsonload=…)`.

The tests are skipped when DAGonStar is not installed; `requirements-dev.txt`
installs the same DAGonStar revision that DAGonWeb pins.
