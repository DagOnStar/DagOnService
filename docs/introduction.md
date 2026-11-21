# Introduction

## The problem: workflows that outlive the process that runs them

A DAGonStar workflow is, by design, an ordinary Python program. Tasks are
objects, dependencies are discovered from `workflow:///<task>/<path>`
references, and `Workflow.run()` executes the directed acyclic graph with a
pool of threads. This choice keeps the engine small and lets scientists express
a computational experiment in the language they already use, but it has a
consequence that becomes visible as soon as experiments grow: everything the
engine knows about a run lives in the memory of one Python process.

Three recurring needs in computational science cannot be met from inside that
process alone.

1. **Observation from elsewhere.** An operational chain — for example a
   numerical weather or ocean forecast that runs every six hours on an HPC
   allocation — is started by a scheduler, not by a person at a terminal.
   Operators and collaborators need to know which step is running, which one
   failed, and where its scratch directory is, without logging in to the
   submission host and reading log files.
2. **Composition across workflows.** Real pipelines are seldom a single DAG.
   A post-processing workflow written by one group consumes the products of a
   simulation workflow written by another, possibly started at a different
   time and on a different machine. DAGonStar calls such a cross-workflow edge
   a *transversal* dependency: a `workflow://` reference whose first component
   names another workflow. To honour it, the consumer must be able to find the
   producer, learn where its outputs are, and wait until it has finished.
3. **A durable record.** Provenance and reproducibility require that the
   structure of a run — its tasks, their types and commands, and the sequence
   of states each task went through — survives the process that produced it.

DAGonService addresses these needs with a deliberately narrow abstraction: a
small HTTP service that holds, for every registered workflow, the DAGonStar
task-map document together with the observed history of every task.

## What the service is, and what it is not

DAGonService is a **registry and monitor**. It records what DAGonStar tells it
and answers questions about that record. It never schedules or executes a task,
never moves data, and never makes a decision on behalf of the engine. This
separation of concerns is intentional:

- the execution semantics remain entirely in DAGonStar, so a workflow behaves
  identically whether or not the service is enabled (`use = False` is the
  default in `dagon.ini`);
- the service can be restarted, upgraded, or temporarily unavailable without
  corrupting a run; DAGonStar logs a failed report and continues;
- the state the service exposes is *observational*: it is exactly as accurate
  as the reports it has received, and its event log makes that explicit.

The service is equally not a replacement for
[DAGonWeb](https://github.com/DagOnStar/DAGonWeb), which is a complete
multi-user platform for designing and executing workflows. The two are
complementary: DAGonWeb executes workflows it owns and monitors them through its
own database, while DAGonService observes *any* DAGonStar program — including
those launched from a batch script, a notebook, or a DAGonWeb headless export —
and is the rendezvous point for transversal workflows. The
[DAGonWeb integration](dagonweb_integration.md) document describes how they
work together.

## Core concepts

**Workflow document.** The JSON object produced by `dagon.Workflow.as_json()`:
a `name`, a `host`, and a `tasks` object keyed by task name. Each task carries
at least its `type`, `command`, `working_dir`, `status`, and the dependency
lists `prevs`, `nexts` and `explicit_prevs`. Task types contribute further
fields (`function` for Native tasks, `agentic` for Agentic tasks, `volume` for
Volume tasks, …); the service stores them verbatim.

**Task state.** One of the five values of `dagon.Status`: `READY`, `WAITING`,
`RUNNING`, `FINISHED`, `FAILED`. The service validates every report against
this set and appends it, with a timestamp, to the task's history.

**Aggregate status.** The state of a workflow as a whole, derived on every read
from its tasks' states (see [Data model](data_model.md#aggregate-status)).

**Event.** An immutable, time-ordered record of one observation — a
registration, a status change, a new dependency, an attribute update. Events
let a monitor follow a run incrementally and are the payload of the optional
webhooks.

**Transversal point.** A dependency of a task on a task of another registered
workflow. The service resolves the workflow by name (the most recent
registration wins) and returns the producer task with the host it ran on, which
is what DAGonStar needs to stage the data and to wait for completion.

## History

The service was first written in 2018 as a Flask prototype alongside the
DAGonStar engine, with a MongoDB back end and an experimental Socket.IO
notifier. It was containerised and gained transversal-workflow support in 2023.
Version 2.0 (2026) is a revision that preserves the HTTP contract the
DAGonStar 3.0 client depends on while replacing the implementation: atomic
updates instead of whole-document rewrites, strict validation, a task history
that is actually recorded, an event log, a versioned API, a dashboard, an
optional access token, and automated tests that run the real DAGonStar client
against the service. The [Assessment report](assessment.md) documents the
defects of the prototype and how each one was addressed.
