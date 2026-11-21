# Deployment

## Docker Compose

The repository's `docker-compose.yml` runs two containers on a private network:

- `dagon_service` — the service under Gunicorn, as an unprivileged user,
  published on host port 57000 (override with `DAGONSERVICE_PORT`);
- `dagon_mongodb` — MongoDB 7.0 with a named volume, `dagon_mongodb_data`,
  not published on the host.

The service starts only after MongoDB reports healthy, and both containers
have health checks and restart automatically.

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f dagon_service
```

## Production checklist

1. **Network exposure.** The DAGonStar client cannot authenticate, so the
   mutating routes must only be reachable from the machines that run
   workflows. Publish the port on a private interface
   (`"10.0.0.5:57000:57000"`) or behind a firewall, and read
   [Security](security.md).
2. **TLS.** Terminate TLS in a reverse proxy (nginx, Traefik, Caddy) in front of
   the service, and point `[dagon_service] route` at the `https://` URL.
3. **Database.** Use authentication on MongoDB in shared environments and pass
   it in `DAGONSERVICE_MONGO_URI`
   (`mongodb://user:password@host:27017/?authSource=admin`). Do not publish
   port 27017.
4. **Duplicate policy.** Choose `replace`, `reject` or `keep` deliberately; see
   [Data model](data_model.md#duplicate-names).
5. **Backups.** `docker compose exec dagon_mongodb mongodump --archive --db dagon > dagon.archive`
   writes a consistent dump; restore with `mongorestore --archive`.
6. **Retention.** Registrations are kept until deleted. Under the `keep`
   policy, remove old runs periodically with `DELETE /api/v1/workflows/<id>`.

### Reverse proxy example (nginx)

```nginx
location / {
    proxy_pass http://127.0.0.1:57000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 30s;
}
```

## Without containers

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DAGONSERVICE_MONGO_URI=mongodb://localhost:27017
gunicorn --bind 0.0.0.0:57000 --workers 2 --threads 8 wsgi:app
```

`flask --app wsgi run` and `python wsgi.py` start the development server, for
local experiments only.

## Upgrading from the 2018 prototype

Version 2.0 keeps the database name (`dagon`), the collection (`workflows`),
the port (57000 on the host) and every route the DAGonStar client calls, so
DAGonStar installations need no change.

### Migrating the data

MongoDB moves from 4.0 to 7.0, and a MongoDB data directory cannot skip major
versions, so the old volume cannot simply be mounted by the new database. The
Compose volume is also renamed, from `<project>_data-volume` to
`<project>_dagon_mongodb_data`. One script performs the whole migration:

```bash
docker compose -p <old project name> down              # stop 1.x; keeps its volume
git pull && git checkout main                          # obtain 2.x
scripts/migrate-legacy-deployment.sh                   # or: ... <old volume name>
docker compose up -d
```

The script

1. finds the single volume whose name ends in `_data-volume` (or uses the name
   you pass), starts a temporary `mongo:4.0` container on it, and writes a
   `mongodump` archive of the `dagon` database to `./dagon-legacy.archive`,
   which you should keep as a backup;
2. starts the MongoDB 7.0 service of the new Compose file and restores the
   archive into it;
3. runs `flask --app wsgi upgrade-documents`, which converts each prototype
   document to schema version 2 — canonical states, deduplicated dependency
   lists and subscribers, a history built from any recorded entries, UTC
   timestamps, encoded task keys — and marks it `migrated_from: prototype`.
   The command is idempotent and can be run again at any time.

The workflow data in the old volume is only read — the temporary MongoDB 4.0
is started on it and stopped cleanly — so you can repeat the migration or go
back to 1.x; remove the volume with `docker volume rm` once you have checked the
result. Stop the 1.x stack with `docker compose down` (not `docker kill`) before
migrating, so that MongoDB 4.0 flushes its last writes. Set `COMPOSE="docker compose -p <name>"` when the new
deployment uses an explicit project name, and `LEGACY_MONGO_PLATFORM` if your
platform cannot run the `linux/amd64` image of MongoDB 4.0 (Docker Desktop on
Apple silicon emulates it). CI exercises exactly this procedure against a
seeded MongoDB 4.0 volume.

For a database outside Compose, run `mongodump --db dagon --archive` against
the old server, `mongorestore --archive` against the new one, and
`DAGONSERVICE_MONGO_URI=... python -m dagonservice.migrate`.

### Other changes

- The old Compose file passed `MONGO_DB=dagon_mongodb`; it is still honoured.
- The container now listens on 57000 rather than 5000. Update any custom
  port mapping (`57000:5000` becomes `57000:57000`).
- Documents that were not upgraded remain readable (see
  [Data model](data_model.md#documents-written-by-the-prototype)), but running
  the upgrade is recommended; new registrations use schema version 2.
- The Socket.IO "Centinel" notifier is removed; use
  `DAGONSERVICE_WEBHOOK_URLS` or the events endpoint.
- Behaviour that changed intentionally: unknown tasks and invalid statuses are
  rejected instead of being stored, and deleting an unknown workflow returns
  404. The [Assessment report](assessment.md) lists every change.
