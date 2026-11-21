# Configuration

DAGonService reads its configuration from environment variables when the
application is created. Invalid values stop the service at start-up with an
explicit message rather than producing surprising behaviour later.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DAGONSERVICE_MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string. May include credentials, a replica set, and TLS options. |
| `MONGO_DB` | — | Legacy: a MongoDB host name, used as `mongodb://<MONGO_DB>:27017` when `DAGONSERVICE_MONGO_URI` is not set. |
| `DAGONSERVICE_DB_NAME` | `dagon` | Database name. `dagon` is the database used by the prototype. |
| `DAGONSERVICE_DUPLICATE_POLICY` | `replace` | `replace`, `reject` or `keep`; see [Data model](data_model.md#duplicate-names). |
| `DAGONSERVICE_API_TOKEN` | unset | Enables the token check for mutating requests; DAGonStar clients after 3.0.0 send it from `[dagon_service] token`. See [Security](security.md). |
| `DAGONSERVICE_PROTECT_READS` | `false` | With a token, also require it for reads (except `/check` and `/api/v1/health`). |
| `DAGONSERVICE_WEBHOOK_URLS` | unset | Comma-separated `http(s)` URLs that receive every event. |
| `DAGONSERVICE_WEBHOOK_TIMEOUT` | `2.0` | Seconds before a webhook delivery is abandoned. |
| `DAGONSERVICE_MAX_HISTORY` | `1000` | Maximum history entries kept per task (≥ 1). |
| `DAGONSERVICE_DASHBOARD` | `true` | Serve the dashboard at `/`. |
| `DAGONSERVICE_DASHBOARD_REFRESH_MS` | `3000` | Dashboard polling interval (≥ 500). |
| `DAGONSERVICE_LOG_LEVEL` | `INFO` | Python logging level. |

The container image adds:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `57000` | Port Gunicorn listens on inside the container. |
| `GUNICORN_WORKERS` | `2` | Worker processes. |
| `GUNICORN_THREADS` | `8` | Threads per worker. |

The Compose file reads `DAGONSERVICE_PORT` (default `57000`) for the published
host port, and passes `DAGONSERVICE_DUPLICATE_POLICY`, `DAGONSERVICE_API_TOKEN`
and `DAGONSERVICE_WEBHOOK_URLS` through from the shell or an `.env` file.

`GET /api/v1/info` reports the effective non-secret settings; it never reveals
the MongoDB URI or the token.

## Sizing

A status report is one indexed update and one insert, so the service is limited
by MongoDB rather than by Python. The default of 2 workers × 8 threads serves
hundreds of concurrent reporting tasks. Increase `GUNICORN_THREADS` for
workflows with very wide parallel stages, and `GUNICORN_WORKERS` when one CPU is
saturated.
