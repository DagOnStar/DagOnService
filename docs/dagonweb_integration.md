# DAGonWeb integration

[DAGonWeb](https://github.com/DagOnStar/DAGonWeb) and DAGonService are both
built on DAGonStar 3.0 and exchange information in the DAGonStar task-map JSON
document. This document describes the three ways they meet.

## Roles

DAGonWeb is a multi-user platform: it stores workflows in a relational database,
executes them with DAGonStar on its own workers or on an HPC cluster, and shows
live runs from its own run records. DAGonService is a lightweight registry that
observes any DAGonStar program, regardless of who started it, and resolves
references between workflows. Neither depends on the other; together they cover
three scenarios.

| Scenario | What to use |
| --- | --- |
| Design and run workflows interactively, with accounts and permissions. | DAGonWeb alone. |
| Run DAGonWeb's headless export (`run.sh`) from cron or a Slurm job and watch it remotely. | The exported program with `[dagon_service] use = True`, monitored in DAGonService. |
| A workflow run by DAGonWeb consumes the products of a workflow run elsewhere (or vice versa). | Both, with the same DAGonService route in both `dagon.ini` files. |

## 1. Enabling the service from DAGonWeb

DAGonWeb's workflow settings (and the administrator's site-wide `dagon.ini`
page) have a *DAGon service route* field and a *Use DAGon service* switch; DAGonWeb's default route is
`http://localhost:57000`, the port DAGonService publishes. When the switch is
on, the runtime workflow that DAGonWeb builds registers with the service like
any other DAGonStar program, and the run appears in the DAGonService dashboard
in addition to DAGonWeb's own run page. Inside a container, `localhost` is the
container itself: use the service name on a shared Compose network (for
example `http://dagon_service:57000`) or the host's address.

The headless application ZIP that DAGonWeb exports contains a sanitised
`dagon.ini`; set the same two keys there before deploying it.

## 2. Moving documents between the two

`GET /api/v1/workflows/<id>/document` returns the registered workflow as a
DAGonStar task-map document: the members DAGonStar wrote, task fields
unchanged, service bookkeeping (`history`, `updated_at`) removed, and any
additive extension — including DAGonWeb's `dagonweb` member with layout and
runtime options — restored at the top level. The dashboard's **DAGonStar JSON**
button downloads the same file.

DAGonWeb imports this file with **Workflows → Import**, which accepts DAGonStar
JSON documents. Data links are
re-derived from `workflow:///` references in the commands and explicit
dependencies from `explicit_prevs`, following DAGonWeb's rule; the `prevs` and
`nexts` lists in the document are informational. Conversely, any document that
DAGonWeb exports in DAGonStar format can be registered directly with
`POST /api/v1/workflows`, which is useful to publish a workflow's structure to
the registry before it runs.

Note that a document registered by the DAGonStar client contains only what
`Task.as_json()` emits for each task type. For Batch tasks this is the full
definition; for task types that carry their configuration in constructor
arguments not serialised by `as_json()`, the export is a faithful record of the
registration but may not be a complete, runnable definition. DAGonWeb's own
export remains the authoritative design document.

## 3. Transversal references between platforms

Because name resolution happens in the service, a workflow run by DAGonWeb can
reference `workflow://Simulation/Run/out.nc` produced by a program started on a
cluster, as long as both registered with the same service and the producer's
`host` (its `[ftp_pub] ip`) is reachable from the consumer. See
[DAGonStar integration](dagonstar_integration.md#transversal-workflows).

## Consistency of conventions

The service follows the conventions DAGonWeb documents in its `AGENTS.md`:
the task-map document is preserved with tasks keyed by name, additive
extensions are kept verbatim, the five `dagon.Status` values are the only
states, and edges are classified as `explicit` when they appear in
`explicit_prevs`. Front-end code follows the same rules as DAGonWeb's: no build
step, server data inserted with `textContent`, light and dark themes, and
layouts that work at phone width.
