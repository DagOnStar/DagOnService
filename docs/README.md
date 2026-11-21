# DAGonService documentation

DAGonService is the registration and remote-monitoring companion of the
[DAGonStar](https://github.com/DagOnStar/dagonstar) workflow engine. A DAGonStar
workflow configured with `[dagon_service] use = True` registers itself with the
service when it is created, reports every task transition while it runs, and
can resolve `workflow://` references to tasks that belong to *other* workflows
registered with the same service. [DAGonWeb](https://github.com/DagOnStar/DAGonWeb)
and any other monitor read the same information through a versioned JSON API
or through the built-in dashboard.

The documents below are written to be read in order by a newcomer, and
individually by an operator or a developer who needs one specific answer.

| Document | Purpose |
| --- | --- |
| [Introduction](introduction.md) | Why a workflow engine needs an external registry, and the concepts the service is built on. |
| [Getting started](getting_started.md) | Run the service and register a first DAGonStar workflow in five minutes. |
| [Architecture](architecture.md) | Components, request flow, concurrency model and design decisions. |
| [Data model](data_model.md) | The stored document, task states, the aggregate status, events, and field-name encoding. |
| [API reference](api.md) | Every route of the legacy DAGonStar contract and of the `/api/v1` interface. |
| [DAGonStar integration](dagonstar_integration.md) | `dagon.ini`, the client life cycle, transversal workflows, and the alignment tests. |
| [DAGonWeb integration](dagonweb_integration.md) | Using the service with DAGonWeb, and moving workflow documents between the two. |
| [Dashboard](dashboard.md) | The read-only monitoring page served at `/`. |
| [Configuration](configuration.md) | All `DAGONSERVICE_*` environment variables. |
| [Deployment](deployment.md) | Docker Compose, production hardening, backups, and upgrades from the 2018 prototype. |
| [Security](security.md) | Threat model, the optional API token, and operational recommendations. |
| [Developer guide](developer_guide.md) | Repository layout, tests, and how to extend the service safely. |
| [Assessment report](assessment.md) | The 2026 audit of the original prototype: defects found, their impact, and how each was resolved. |
