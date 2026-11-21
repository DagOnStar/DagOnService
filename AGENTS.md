# AGENTS.md

Guidance for AI agents and maintainers working in this repository.

## Project
DAGonService is a Flask + MongoDB service that registers DAGonStar workflows and monitors them remotely. DAGonStar's built-in client (`dagon/api/__init__.py`, enabled with `[dagon_service] use = True` in `dagon.ini`) registers a workflow, adds tasks and dependencies, reports every task status, and resolves transversal `workflow://<other workflow>/<task>/...` references through it. Monitors (the built-in dashboard, DAGonWeb, scripts) use the versioned `/api/v1`.

## Goals
- Keep the service a **registry and monitor**: it never executes tasks, moves data, or makes scheduling decisions.
- Target **DAGonStar 3.0.0** — the revision DAGonWeb pins, installed by `requirements-dev.txt` — and stay consistent with DAGonWeb's conventions.
- **Never change a legacy route** (`/check`, `/create`, `/add_task/<id>`, `/changestatus/<id>/<task>/<status>`, `/update/<id>/<task>/<attr>?value=`, `/<id>/<task>/dependency/<dep>`, `/getworkflow/<name>` (plain-text id), `/<id>/<task>`, `/<id>`, `/list`, `/subscribe/...`, `/delete/<id>`): path, verb, success status and response shape are frozen by every deployed DAGonStar. Add features to `/api/v1`.
- **No read-modify-write of workflow documents.** DAGonStar reports from concurrent threads; express each mutation as one atomic MongoDB update on a dotted path built with `model.encode_key()`, filtered on the task's existence. `tests/test_legacy_api.py::test_concurrent_status_updates_are_not_lost` guards this.
- Task states are exactly `dagon.Status`: `READY`, `WAITING`, `RUNNING`, `FINISHED`, `FAILED` (`model.STATUSES`). Do not enforce a transition graph (resume re-enters earlier states).
- Preserve the DAGonStar task-map document: tasks keyed by name, unknown task fields and additive top-level extensions (e.g. DAGonWeb's `dagonweb`) kept verbatim, so `/api/v1/workflows/<id>/document` reloads with `dagon.Workflow(jsonload=...)` and imports into DAGonWeb. Service bookkeeping (`history`, `updated_at`) is stripped from that export.
- The aggregate workflow status is derived on read (`model.aggregate_status`), never stored.
- Keep `dagonservice/model.py` free of I/O; all MongoDB access lives in `dagonservice/storage.py`.

## Important paths
- `dagonservice/__init__.py`: `create_app(settings, database)` factory, version, dashboard route, security headers.
- `dagonservice/config.py`: `Settings.from_env()` (`DAGONSERVICE_*`, legacy `MONGO_DB`).
- `dagonservice/model.py`: statuses, validation, key encoding, aggregate status.
- `dagonservice/storage.py`: `WorkflowStore`, serialisers (`workflow_to_json`, `workflow_to_document`, `workflow_graph`, `event_to_json`).
- `dagonservice/api.py`: `legacy` and `v1` blueprints, error handlers, optional token check.
- `dagonservice/notifier.py`: best-effort webhooks.
- `dagonservice/templates/dashboard.html`, `dagonservice/static/`: the dashboard.
- `tests/`: pytest; `conftest.make_app(**settings)` builds an app on mongomock.
- `docs/`: user, operator and developer documentation.

## Commands
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
flask --app wsgi run --port 57000            # needs MongoDB (DAGONSERVICE_MONGO_URI)
docker compose up --build                    # service + MongoDB 7 on :57000
```

## Verification
- `pytest` must pass, including `tests/test_dagonstar_alignment.py`, which runs unmodified DAGonStar against a live server. Do not skip it by uninstalling DAGonStar.
- `python -m compileall -q dagonservice tests wsgi.py` and `node --check dagonservice/static/dashboard.js`.
- For storage changes, also run a workflow against the Compose stack (real MongoDB): mongomock does not catch every server behaviour.
- Check dashboard changes in a browser: light and dark themes, and phone width (375 px) with no horizontal page scroll.

## Style
- Python: type hints, small functions, no hidden global mutable state; configuration flows through `Settings`, never `os.environ` at import time.
- Errors: raise `model.ValidationError` (400), `storage.NotFound` (404) or `storage.Conflict` (409); never return HTTP 200 with an error body.
- Front end: plain browser JavaScript and CSS, no build step, no third-party assets (the CSP is `default-src 'self'`); insert server data with `textContent` only; label every control.
- Security: never enable the Flask debugger; never call URLs supplied in requests; never log or expose `DAGONSERVICE_MONGO_URI` or the token (`Settings.public()` is the only settings view).

## Documentation
- Keep all documentation updated: `README.md`, `docs/`, `CHANGELOG.md`, and this file.
- Behaviour visible to DAGonStar users belongs in `docs/dagonstar_integration.md` and `docs/api.md`; DAGonWeb interplay in `docs/dagonweb_integration.md`.
- Write in the narrative, precise style of the DAGonStar and DAGonWeb documentation; state limits honestly (e.g. that the DAGonStar 3.0 client cannot send a token).

## Review checklist
- Are the legacy routes byte-for-byte compatible (paths, verbs, codes, shapes)?
- Is every mutation a single atomic update, and does it fail with 404 instead of creating a missing task or workflow?
- Do unknown task fields and extensions survive registration and `/document`?
- Are new inputs validated, and are task names encoded before use in update paths?
- Is a new or changed behaviour covered by a test and documented?
