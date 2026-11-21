# Changelog

## 2.0.0 — 2026-11-21

A revision of the 2018 prototype that keeps the HTTP contract of the DAGonStar
3.0 client and replaces the implementation. See
[docs/assessment.md](docs/assessment.md) for the audit behind each change.

### Added
- Versioned API under `/api/v1`: workflow listing with filters and pagination,
  task operations, `/graph`, `/events` (incremental), `/document` (DAGonStar
  task-map export), `/health`, `/info`.
- Per-task status history (bounded by `DAGONSERVICE_MAX_HISTORY`) and an event log.
- Aggregate workflow status and per-state counts.
- Read-only dashboard at `/` (light/dark, phone width, strict CSP).
- Duplicate-name policy: `replace` (default), `reject`, `keep`.
- Optional API token for mutations (and optionally reads).
- Optional webhooks for every event.
- Test suite, including end-to-end tests with the real DAGonStar client.
- CI/CD: reusable CI (tests on Python 3.12/3.13, image smoke test, 1.x
  migration test), multi-architecture image publishing to GHCR, tagged
  releases with notes from this changelog, Dependabot.
- `scripts/migrate-legacy-deployment.sh` and `flask --app wsgi upgrade-documents`
  (`python -m dagonservice.migrate`) to migrate 1.x deployments.
- Apache-2.0 `LICENSE` and `NOTICE`.
- Documentation of the DAGonStar client's token support (`[dagon_service] token`,
  `DAGON_SERVICE_TOKEN`), added to DAGonStar after 3.0.0 together with URL
  encoding, request timeouts and shell-safe scratch directory names.
- Documentation in `docs/`, `AGENTS.md`, this changelog.

### Changed
- Atomic MongoDB updates for every mutation; concurrent status reports are no
  longer lost.
- Task names are percent-encoded in storage; names with `.`, `$` and `%` work.
- Unknown tasks and invalid statuses yield 404/400 instead of being stored;
  `GET /<id>/<task>` for an unknown task now returns 404; deleting an unknown
  workflow returns 404.
- Flask 3.0, pymongo 4, Gunicorn, Python 3.12, unprivileged container,
  MongoDB 7.0 with a health-checked start order; the container listens on 57000.
- Package renamed from `app/` to `dagonservice/`; entry point `wsgi:app`.
- Default branch renamed from `master` to `main`.

### Removed
- The Socket.IO "Centinel" notifier, `Flask-API`, `Flask-Login`,
  `Flask-Session`, `Flask-SocketIO` and `socketIO-client`.
- Debug mode in production, committed `*.pyc` and log files.

## 1.x — 2018–2023

Flask prototype with MongoDB storage (2018); transversal-workflow support and
containerisation (2023).
