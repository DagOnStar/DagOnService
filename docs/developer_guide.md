# Developer guide

## Repository layout

```
dagonservice/            the application package
  __init__.py            create_app() and the version
  config.py              Settings (environment variables)
  model.py               states, validation, encoding, aggregate status (no I/O)
  storage.py             WorkflowStore (MongoDB) and serialisers
  api.py                 legacy and /api/v1 blueprints, errors, token check
  notifier.py            webhooks
  migrate.py             upgrade of prototype documents (flask upgrade-documents)
  templates/, static/    dashboard
scripts/                 migrate-legacy-deployment.sh (1.x → 2.x data migration)
.github/                 CI, image publishing, releases, Dependabot
tests/                   pytest suite (mongomock; DAGonStar for alignment tests)
docs/                    this documentation
wsgi.py                  WSGI entry point
Dockerfile, docker-compose.yml
```

## Setting up

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

`requirements-dev.txt` installs `mongomock`, so the tests need no MongoDB
server, and DAGonStar at the revision DAGonWeb pins, so the alignment tests run
the real client against a real HTTP server. To work against a local DAGonStar
checkout instead, run `pip install -e ../dagonstar`.

## Tests

| File | What it guarantees |
| --- | --- |
| `tests/test_legacy_api.py` | The DAGonStar contract: paths, verbs, status codes and shapes; validation; no phantom tasks; idempotent dependencies; dotted and `$` task names; concurrent status reports are not lost. |
| `tests/test_api_v1.py` | The versioned API, events, graph, document export, history cap, token rules, dashboard and security headers, settings parsing. |
| `tests/test_dagonstar_alignment.py` | Unmodified DAGonStar registers, runs and reports against a live server; failures propagate; exported documents reload in DAGonStar; a token-capable client authenticates (skipped for 3.0.0). |
| `tests/test_migrate.py` | Prototype documents are upgraded to schema 2 idempotently and remain usable. |

## Continuous integration and delivery

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `.github/workflows/ci.yml` | Push to `main` or `development`, pull requests, manual, and called by the publish workflow | Byte-compiles, checks the dashboard script with `node --check`, runs `pytest` on Python 3.12 and 3.13, builds the image and smoke-tests it with MongoDB, and runs the 1.x → 2.x migration against a seeded MongoDB 4.0 volume. |
| `.github/workflows/docker-publish.yml` | Push to `main`, `v*` tags, manual | Re-runs CI, then publishes a `linux/amd64` + `linux/arm64` image to `ghcr.io/<owner>/dagonservice`, tagged with the branch, the version (`2.0.0`, `2.0`) and the commit (`sha-…`). |
| `.github/workflows/release.yml` | `v*` tags | Checks that the tag equals `dagonservice.__version__`, then creates a GitHub release whose notes are the matching `CHANGELOG.md` section. |
| `.github/dependabot.yml` | Weekly | Update pull requests for pip, GitHub Actions and the Docker base image. DAGonStar is excluded: it is pinned to DAGonWeb's revision and is bumped together with it. |

To release: set `__version__` in `dagonservice/__init__.py`, add the
`## X.Y.Z — date` section to `CHANGELOG.md`, merge to `main`, then
`git tag vX.Y.Z && git push origin vX.Y.Z`.

## Rules for changes

- **Never change a legacy route's path, verb, success code or response shape.**
  They are called by every deployed DAGonStar. Add behaviour to `/api/v1`
  instead.
- **Never read-modify-write a workflow document.** Express each mutation as one
  atomic update on a dotted path built with `encode_key()`; see
  [Architecture](architecture.md#concurrency-and-consistency).
- **Keep `model.py` free of I/O** so that the domain rules can be tested in
  isolation.
- **Preserve unknown task fields**: new DAGonStar task types must round-trip
  through `/document` without code changes here.
- When DAGonStar's `Status` enum or the `dagon.api.API` client changes, update
  `model.STATUSES`, the alignment tests, `docs/dagonstar_integration.md` and
  `docs/api.md` together.
- Every change to behaviour needs a test and an update to the affected
  documents, the README and `CHANGELOG.md`.

## Running against real MongoDB

```bash
docker compose up --build -d
curl http://localhost:57000/api/v1/health
```

then point a DAGonStar program at `http://localhost:57000` as in
[Getting started](getting_started.md). `docker compose down -v` removes the
containers and the data volume.
