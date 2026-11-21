# Security

## Threat model

DAGonService stores descriptions of scientific workflows: task names, shell
commands, host names and scratch paths. Commands can reveal how a site is
organised, and occasionally embed secrets that a careless author placed on a
command line. Anyone who can call the mutating routes can falsify the recorded
state of a run, delete registrations, or — through a forged transversal task —
point a consumer workflow at a different working directory or host.

The service never executes commands and never reads or writes files, so it
cannot be used to run code on the server. Its assets are the **confidentiality**
of the registry and the **integrity** of the recorded state.

## Built-in protections

- **Input validation.** Task states are restricted to the five DAGonStar values;
  task and workflow names are length-bounded and may not contain `/` or NUL;
  attribute names in `/update` and `PATCH` must be identifiers and cannot
  overwrite `name`, `status`, `history` or dependency lists. MongoDB operator
  injection through names is impossible because task names are percent-encoded
  before being used in update paths and attribute names cannot contain `.` or
  `$`.
- **No implicit creation.** Updates for unknown tasks fail instead of
  creating them.
- **Bounded growth.** Task histories are capped (`DAGONSERVICE_MAX_HISTORY`),
  and list endpoints are paginated with hard maxima.
- **Uniform errors.** Error responses never include stack traces; the Flask
  debugger is never enabled.
- **Browser hardening.** The dashboard is served with a strict Content Security
  Policy (`default-src 'self'`, no inline script), `X-Content-Type-Options:
  nosniff`, `Referrer-Policy: no-referrer` and `frame-ancestors 'none'`, and it
  inserts all data with `textContent`.
- **Least privilege.** The container runs as an unprivileged user, and MongoDB is
  not published outside the Compose network.

## The optional API token

Setting `DAGONSERVICE_API_TOKEN` requires `Authorization: Bearer <token>` (or
`X-API-Key: <token>`) on every mutating request. With
`DAGONSERVICE_PROTECT_READS=true` the token is also required for reads. The
liveness routes `/check` and `/api/v1/health` are always open so that health
checks keep working. Tokens are compared in constant time.

### The DAGonStar client and the token

The DAGonStar 3.0 client sends no authentication header. With a token
configured, its registration and status reports are rejected with 401;
DAGonStar then raises at `Workflow(...)`. Today the token is therefore suitable
for deployments where the service is fed by clients you control (scripts,
DAGonWeb integrations, a future DAGonStar release) and for protecting reads of
a registry that is populated on a trusted network. For DAGonStar 3.0, protect
the service at the network level instead:

- bind the published port to a private interface, or allow only the subnets of
  the submission and compute hosts in a firewall;
- put a reverse proxy in front that restricts mutating methods (`POST`, `PUT`,
  `PATCH`, `DELETE`) to those subnets and, if needed, requires authentication
  for the dashboard and `GET` routes.

Adding an optional token to `[dagon_service]` in the DAGonStar client is a
small, backwards-compatible change and the recommended long-term solution.

## Operational recommendations

- Terminate TLS in a reverse proxy; status reports contain paths and commands.
- Enable MongoDB authentication and keep port 27017 private.
- Do not put secrets in task commands; use DAGonStar's configuration and
  credential mechanisms instead, which are never sent to the service.
- Webhook URLs are configured by the operator only; the service never calls a
  URL supplied in a request.
- Review registrations before exporting them for publication: a workflow
  document contains the commands as registered.
