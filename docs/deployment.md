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

- The old Compose file passed `MONGO_DB=dagon_mongodb`; it is still honoured.
  The new Compose file uses `DAGONSERVICE_MONGO_URI` and a renamed volume,
  `dagon_mongodb_data`. To keep the data of the old `data-volume`, either
  rename the volume in `docker-compose.yml` or dump and restore the `dagon`
  database.
- The container now listens on 57000 rather than 5000. Update any custom
  port mapping (`57000:5000` becomes `57000:57000`).
- MongoDB moves from 4.0 to 7.0. A data directory cannot skip major versions;
  migrate with `mongodump` from the old container and `mongorestore` into the
  new one rather than reusing the volume.
- Existing documents remain readable (see
  [Data model](data_model.md#documents-written-by-the-prototype)); new
  registrations use schema version 2.
- The Socket.IO "Centinel" notifier is removed; use
  `DAGONSERVICE_WEBHOOK_URLS` or the events endpoint.
- Behaviour that changed intentionally: unknown tasks and invalid statuses are
  rejected instead of being stored, and deleting an unknown workflow returns
  404. The [Assessment report](assessment.md) lists every change.
