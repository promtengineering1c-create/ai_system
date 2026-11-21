#!/usr/bin/env bash
# rollback.sh — independent rollback of web/worker to a previous immutable tag.
# DB schema is NOT rolled back (ADR-009 Expand/Contract; old code runs on new schema).
# nginx, postgres, redis, volumes: untouched.
# Static volume: previous manifest restored; already-published new hashes remain (harmless union).
# Changes vs previous revision:
#   - Blocker 1: bare tag vs full ref. current_ref -> bare current_tag; IMAGE_REF built
#     from the SAME repo as the running image; image_present/pull check $IMAGE_REF.
#   - Blocker 2: canonical interpolation name IMAGE_TAG everywhere (compose/deploy/rollback/.env),
#     plus post-rollout image assertion -> interpolation mismatch is a hard fail, not silent no-op.
#   - die(): prints compose ps on every fatal path (incl. wait_healthy timeouts).
#   - COMPOSE_FILE resolved after cd; relative path anchored to repo root.
#   - Tag charset validated; dead "" case pattern removed.
#   - smoke_test via curl --resolve (SNI-correct), host configurable via CANONICAL_HOST.
set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
CANONICAL_HOST="${CANONICAL_HOST:-uralsfish.ru}"
COMPOSE=(docker compose -f "$COMPOSE_FILE")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"
[[ "$COMPOSE_FILE" = /* ]] || COMPOSE_FILE="$ROOT_DIR/$COMPOSE_FILE"
COMPOSE=(docker compose -f "$COMPOSE_FILE")

log() { printf '[rollback] %s\n' "$*"; }

PRE_ROLLBACK_TAG=""
on_err() {
  local ec=$?
  printf '[rollback] FAILED (exit %d) at %s:%s. Current state:\n' "$ec" "$0" "$1" >&2
  "${COMPOSE[@]}" ps >&2 || true
  if [[ -n "$PRE_ROLLBACK_TAG" ]]; then
    printf '[rollback] Roll forward to previous state:\n  APP_IMAGE_TAG=%s ./scripts/deploy.sh\n' \
      "$PRE_ROLLBACK_TAG" >&2
  fi
  exit "$ec"
}
trap 'on_err "$LINENO"' ERR

die() {
  printf '[rollback] FATAL: %s\n' "$*" >&2
  "${COMPOSE[@]}" ps >&2 || true
  exit 1
}

if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi
if [[ -f ".env.${APP_ENV:-}" ]]; then
  set -a; . ".env.${APP_ENV}"; set +a
fi

TARGET_TAG="${1:-${ROLLBACK_TAG:-}}"
[[ -n "$TARGET_TAG" ]] || die "usage: $0 <previous-immutable-tag>  (or ROLLBACK_TAG=...)"
case "$TARGET_TAG" in
  latest|*:latest) die "target tag must be immutable, got $TARGET_TAG" ;;
  *[!A-Za-z0-9._-]*) die "invalid tag charset: $TARGET_TAG" ;;
esac

# ---------- preflight (same surface as deploy, minus mutation-time checks) ----------
preflight() {
  [[ -n "${APP_ENV:-}" ]] || die "APP_ENV is required"
  [[ -f ".env.${APP_ENV}" ]] || die ".env.${APP_ENV} not found"
  [[ -f nginx/nginx.conf ]] || die "nginx/nginx.conf missing"
  [[ -d data/nginx-dynamic ]] || die "data/nginx-dynamic directory missing"
  [[ -f data/nginx-dynamic/.htpasswd ]] || die "data/nginx-dynamic/.htpasswd must be a regular file"
  [[ -f data/nginx-dynamic/cloudflare-ips.conf ]] || die "data/nginx-dynamic/cloudflare-ips.conf missing"
  [[ -d data/ssl ]] || die "data/ssl directory missing"
  docker info >/dev/null 2>&1 || die "docker daemon unreachable"
  docker compose version >/dev/null 2>&1 || die "docker compose plugin missing"
  docker volume inspect pgdata >/dev/null 2>&1 \
    || die "external volume pgdata missing; create once: docker volume create pgdata"
  log "preflight OK (APP_ENV=$APP_ENV, target=$TARGET_TAG)"
}

container_id() { "${COMPOSE[@]}" ps -q "$1" | head -1; }

wait_healthy() {
  local service="$1" timeout="${2:-120}" elapsed=0 cid status
  log "waiting $service healthy (<=${timeout}s)"
  while :; do
    cid="$(container_id "$service" || true)"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo none)"
      [[ "$status" == "healthy" ]] && { log "$service healthy"; return 0; }
    else
      status="not-running"
    fi
    [[ "$elapsed" -ge "$timeout" ]] && die "$service not healthy in ${timeout}s (last=$status)"
    sleep 2; elapsed=$((elapsed+2))
  done
}

image_present() { docker image inspect "$1" >/dev/null 2>&1; }

rollout_service() {
  local service="$1"
  if command -v docker-rollout >/dev/null 2>&1 || docker rollout --help >/dev/null 2>&1; then
    log "start-first rollout: $service (docker-rollout)"
    if command -v docker-rollout >/dev/null 2>&1; then
      docker-rollout -f "$COMPOSE_FILE" -t 120 "$service"
    else
      docker rollout -f "$COMPOSE_FILE" -t 120 "$service"
    fi
  else
    log "WARN: docker-rollout absent; base-mode recreate for $service (~5-15s window)"
    "${COMPOSE[@]}" up -d --no-deps "$service"
  fi
}

smoke_test() {
  local code
  wait_healthy nginx 30
  # SNI-correct probes: -H 'Host: ...' does NOT set SNI; an IP literal would hit
  # the 443 default_server (ssl_reject_handshake) and every check would return 000.
  log "smoke: /healthz/ must be 404 externally"
  code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/healthz/" || true)"
  [[ "$code" == "404" ]] || die "/healthz/ returned $code (expected 404)"
  log "smoke: canonical / reachable"
  code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/" || true)"
  [[ "$code" =~ ^(200|301|302)$ ]] || die "canonical / returned $code"
  log "smoke OK"
}

# ---------- rollback ----------
main() {
  preflight

  local current_cid current_ref current_tag
  current_cid="$(container_id web || true)"
  [[ -n "$current_cid" ]] || die "web is not running; nothing to roll back (use deploy.sh)"
  current_ref="$(docker inspect --format '{{.Config.Image}}' "$current_cid")"  # repo:tag
  current_tag="${current_ref##*:}"                                            # bare tag
  PRE_ROLLBACK_TAG="$current_tag"                                             # bare tag (deploy.sh format)

  [[ "$TARGET_TAG" != "$current_tag" ]] \
    || die "target == current ($TARGET_TAG); nothing to roll back"

  # Same repo as the RUNNING image; compose interpolation gets the bare tag.
  local image_ref="${current_ref%:*}:${TARGET_TAG}"
  export APP_IMAGE_REPO="${current_ref%:*}"
  export APP_IMAGE_TAG="$TARGET_TAG"

  if ! image_present "$image_ref"; then
    log "image $image_ref not local; pulling"
    "${COMPOSE[@]}" pull web \
      || die "previous image $image_ref unavailable locally and in registry; cannot roll back"
    image_present "$image_ref" || die "image $image_ref missing after pull"
  fi

  log "WARN: DB schema is at the LATEST state. Safe ONLY if the release followed Expand/Contract."
  log "WARN: if a destructive (Contract) migration already ran, manual DB restore is required."
  log "current=$current_ref -> target=$image_ref"

  # Restore staticfiles.json manifest from the old image.
  # Hashed filenames published by the newer release remain on the volume (union, harmless).
  log "restoring staticfiles.json from $TARGET_TAG"
  "${COMPOSE[@]}" run --rm static-publish-job

  rollout_service web
  wait_healthy web 120

  # Interpolation-mismatch guard: wrong/silently-ignored APP_IMAGE_TAG would recreate web
  # on the CURRENT tag — a rollback that changes nothing must fail loudly.
  [[ "$(docker inspect --format '{{.Config.Image}}' "$(container_id web)")" == "$image_ref" ]] \
    || die "web runs wrong image; expected $image_ref"

  log "recreating worker on $TARGET_TAG"
  "${COMPOSE[@]}" up -d --no-deps worker
  wait_healthy worker 90
  [[ "$(docker inspect --format '{{.Config.Image}}' "$(container_id worker)")" == "$image_ref" ]] \
    || die "worker runs wrong image; expected $image_ref"

  # nginx / postgres / redis / volumes: untouched by design (ADR-009).
  smoke_test

  log "rollback complete: web/worker on $TARGET_TAG (was $current_tag)"
  log "next deploy must set APP_IMAGE_TAG to a NEW immutable tag"
}

main "$@"