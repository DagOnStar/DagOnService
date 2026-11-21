#!/usr/bin/env bash
# Move the data of a DAGonService 1.x (2018 prototype) deployment into 2.x.
#
# The prototype stored MongoDB 4.0 data in the Compose volume "<project>_data-volume".
# MongoDB 7.0 cannot open a 4.0 data directory, so this script:
#   1. starts a temporary mongo:4.0 container on the old volume (read only) and dumps
#      the "dagon" database;
#   2. starts the new MongoDB 7.0 service and restores the dump into it;
#   3. converts the documents to schema version 2 (flask upgrade-documents).
# Workflow data in the old volume is only read (mongod is started and stopped cleanly on it);
# delete the volume yourself once you have checked the result.
#
# Usage: scripts/migrate-legacy-deployment.sh [OLD_VOLUME]
#   OLD_VOLUME  default: the single existing volume whose name ends in "_data-volume"
# Environment:
#   LEGACY_MONGO_IMAGE     default mongo:4.0
#   LEGACY_MONGO_PLATFORM  default linux/amd64 (mongo:4.0 has no arm64 image)
#   DUMP_FILE              default ./dagon-legacy.archive (kept as a backup)
#   COMPOSE                default "docker compose"
set -euo pipefail

cd "$(dirname "$0")/.."
compose=(${COMPOSE:-docker compose})
image="${LEGACY_MONGO_IMAGE:-mongo:4.0}"
platform="${LEGACY_MONGO_PLATFORM:-linux/amd64}"
dump="${DUMP_FILE:-./dagon-legacy.archive}"

old_volume="${1:-}"
if [ -z "$old_volume" ]; then
  candidates=$(docker volume ls --format '{{.Name}}' | grep -E '_data-volume$' || true)
  if [ "$(printf '%s\n' "$candidates" | grep -c .)" -ne 1 ]; then
    echo "Give the old volume name explicitly; candidates:" >&2
    printf '  %s\n' $candidates >&2
    exit 2
  fi
  old_volume="$candidates"
fi
docker volume inspect "$old_volume" >/dev/null

legacy="dagonservice-legacy-$$"
# Stop mongod cleanly (SIGTERM, then wait) so the old data files stay consistent.
cleanup() {
  docker stop -t 60 "$legacy" >/dev/null 2>&1 || true
  docker rm -f "$legacy" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Dumping database 'dagon' from $old_volume with $image"
docker run -d --name "$legacy" --platform "$platform" -v "$old_volume":/data/db "$image" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$legacy" mongo --quiet --eval 'db.adminCommand("ping").ok' >/dev/null 2>&1 && break
  sleep 2
done
count=$(docker exec "$legacy" mongo --quiet dagon --eval 'db.workflows.count()')
docker exec "$legacy" mongodump --quiet --archive --db dagon > "$dump"
cleanup
echo "    $count workflow document(s); wrote $dump ($(wc -c < "$dump" | tr -d ' ') bytes)"
if [ "$count" = "0" ]; then
  echo "    warning: the old database holds no workflows; is $old_volume the right volume?" >&2
fi

echo "==> Restoring into the MongoDB 7.0 service"
"${compose[@]}" up -d --wait dagon_mongodb
"${compose[@]}" exec -T dagon_mongodb mongorestore --quiet --archive --nsInclude 'dagon.*' < "$dump"

echo "==> Converting documents to schema version 2"
"${compose[@]}" build --quiet dagon_service
"${compose[@]}" run --rm --no-deps dagon_service flask --app wsgi upgrade-documents

echo "==> Done. Start the service with: ${compose[*]} up -d"
echo "    The data in $old_volume was only read; remove the volume when satisfied:"
echo "    docker volume rm $old_volume"
