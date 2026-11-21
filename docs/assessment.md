# Assessment report (November 2026)

This report records the audit of DAGonService as it stood on the `master`
branch at commit `4e71838` (the 2018 prototype plus the 2023 transversal and
container work), the evaluation of its fitness against DAGonStar 3.0 and
DAGonWeb, and the resolution of each finding in version 2.0.

## Method

The prototype's source (`app/main.py`, `app/workflow.py`,
`app/centinel_api.py`, `app/make_serialization.py`), container files and
dependency list were reviewed line by line against the HTTP client that
DAGonStar 3.0 ships (`dagon/api/__init__.py`) and the call sites in
`dagon/__init__.py` and `dagon/task.py`. Each finding was classified by impact
on a DAGonStar user. Version 2.0 was then validated three ways: a unit and
contract test suite, end-to-end runs of unmodified DAGonStar against a live
server backed by mongomock, and a run of a four-task diamond workflow against
the Docker Compose stack with MongoDB 7.0.

## Findings

### Critical — wrong or lost data

| # | Finding | Consequence | Resolution |
| --- | --- | --- | --- |
| C1 | `add_task`, `add_dependency` and `subscribe` read the whole workflow, modified it in Python and wrote it back with `replace_one`. | Under DAGonStar's concurrent reporting, updates overwrote each other; a status report arriving between the read and the write was silently reverted. | Every mutation is one atomic update on a dotted path; covered by a 20-task concurrency test. |
| C2 | `changestatus` and `update` used `$set` with `upsert=True` and no check that the task existed. | A report for a misspelt or unknown task created a phantom task; an unknown id could create an empty workflow. | Updates are filtered on the task's existence and return 404 otherwise. |
| C3 | `Workflow.__init__` ignored its `subscribers` argument and had a mutable default. | Each subscription replaced the list instead of extending it. | `$addToSet` on `subscribers`. |
| C4 | Task names were used unencoded as MongoDB path components. | A task named `step.1` was written to `tasks.step.1.status`, corrupting the document structure; names starting with `$` failed. | Reversible percent-encoding of task-name keys. |
| C5 | Status history was never recorded: the code that appended to `history` was commented out. | No record of the sequence of states — the main purpose of a monitor. | Every accepted report is appended, with a bounded history. |

### High — failures and unsafe defaults

| # | Finding | Consequence | Resolution |
| --- | --- | --- | --- |
| H1 | `app.debug = True` and `app.run(debug=True)` in the container. | The Werkzeug debugger allows arbitrary code execution to anyone who can reach the port; the development server is single-process. | Gunicorn with workers and threads; the debugger is never enabled. |
| H2 | In debug mode a re-registration deleted the previous workflow; outside debug mode it returned 409, which makes `dagon.Workflow(...)` raise. Behaviour depended on a debugging flag. | Unpredictable semantics for repeated runs. | Explicit `DAGONSERVICE_DUPLICATE_POLICY` (`replace`, `reject`, `keep`), default `replace` (the behaviour deployments actually had). |
| H3 | The `/update` and dependency routes passed exception objects to `jsonify` (`{"message": e}`). | Their `KeyError` paths produced HTTP 500 instead of a JSON error. | Typed exceptions mapped to 400/404/409 by central handlers. |
| H4 | `GET /<id>/<task>` for an unknown task returned HTTP 200 with an error body. | DAGonStar treated the error as a task and failed later with a `KeyError` on `['task']`. | 404. |
| H5 | No input validation of statuses, names or attribute names; `/update` accepted any attribute, including `status` and dotted or `$` names. | Arbitrary document fields could be overwritten; invalid states stored. | Validation in `model.py`; protected attributes. |
| H6 | `MONGO_DB` was read with `os.environ[...]` at import time. | The module could not be imported, or tested, without the variable. | `Settings.from_env()` with defaults; the application factory takes an injected database for tests. |

### Medium — maintainability and operations

| # | Finding | Resolution |
| --- | --- | --- |
| M1 | The Centinel notifier used the unmaintained `socketIO-client` (Python 2 era), connected to `None:5000` when `CENTINEL` was unset, closed the socket right after opening it, and could never report `status == True`. | Removed; replaced by best-effort webhooks and an event log with incremental polling. |
| M2 | Dependencies pinned to 2022 releases of Flask/Werkzeug, `Flask-API` (unmaintained), unused `Flask-Login`, `Flask-Session`, `Flask-SocketIO`, and a nonexistent `flask-restful[Dolphin]` extra; file named `requeriments.txt`. | Four runtime dependencies (Flask, Werkzeug, pymongo 4, Gunicorn), aligned with DAGonWeb's Flask 3.0.3. |
| M3 | Python 3.8 on Debian buster (both end-of-life); container ran as root; relative `WORKDIR`. | Python 3.12 slim, unprivileged user, health check. |
| M4 | Compose made MongoDB depend on the service (inverted), used MongoDB 4.0 (end-of-life), and set a meaningless `data-volume` environment variable. | Service depends on a healthy MongoDB 7.0; named volume. |
| M5 | Deprecated `Collection.update` (removed in pymongo 4). | `update_one` / `find_one_and_update`. |
| M6 | Compiled files (`*.pyc`), a supervisord log and a KDE `.directory` file were committed. | Removed; `.gitignore` added. |
| M7 | Monkey-patching of `json.JSONEncoder` to serialise `Workflow` objects. | Explicit serialisers in `storage.py`. |
| M8 | Destructive `GET /delete/<id>` returned success for unknown ids. | Kept for compatibility, returns 404 for unknown ids; `DELETE /api/v1/workflows/<id>` added. |
| M9 | The README announced a dashboard that did not exist; no tests, no CI, no documentation. | Dashboard, test suite, CI, and this documentation set. |

## Alignment with DAGonStar 3.0 and DAGonWeb

| Requirement | Status in 2.0 |
| --- | --- |
| Every route and response used by `dagon.api.API` | Preserved and tested with the real client. |
| The five `dagon.Status` values | Enforced; case-insensitive. |
| Task fields of all 16 task types, `explicit_prevs`, `pre_stage` | Stored verbatim and returned by `/document`. |
| Transversal references (`get_workflow_by_name`, `get_task` with `host`) | Preserved; newest registration wins; transversal edges flagged. |
| DAGonWeb's default route `http://localhost:57000` | Unchanged host port; the container now also listens on 57000. |
| DAGonWeb's additive `dagonweb` extension | Preserved through registration and export. |
| DAGonWeb's front-end conventions (no build step, `textContent`, light/dark, phone width) | Followed by the dashboard. |
| DAGonWeb's Flask line | Flask 3.0.3 / Werkzeug 3.0.3, as pinned by DAGonWeb. |

## Residual issues outside this repository

The following were observed during end-to-end testing and belong to the
DAGonStar client; they are documented in
[DAGonStar integration](dagonstar_integration.md#known-client-side-limitations):

1. the client cannot send an access token, which limits the optional token to
   reads or to non-DAGonStar clients;
2. `update_task` does not URL-encode the value it places in the query string;
3. a `$` in a task name is expanded by the shell in DAGonStar's generated
   launcher (`cd` into a truncated path), so the task fails although the
   service records it correctly.
