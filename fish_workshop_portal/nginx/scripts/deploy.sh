#!/usr/bin/env bash
# deploy.sh — release deployment.
# Invariants (ADR-009/ADR-010):
#   - APP_IMAGE_TAG must be immutable (git SHA / semver), `latest` rejected.
#   - Migrations follow Expand/Contract: rollback of web/worker does NOT roll back schema.
#   - web rolled out start-first (docker-rollout); fallback `up -d` accepted with 5-15s window.
#   - worker recreated independently via SIGTERM; at-least-once via BackgroundTask.locked_until.
#   - Ingress firewall (DOCKER-USER, CF-only) MUST be verified before nginx publishes 80/443.
# Changes vs previous revision:
#   - LE issuance/publication step restored from v1 (stub -> real cert, idempotent).
#   - smoke_test via curl --resolve (SNI-correct; IP-literal SNI hit ssl_reject_handshake).
#   - set -Eeuo pipefail: ERR trap propagates into functions.
#   - .env cascade sourced (root + .env.${APP_ENV}), like config/env.py.
#   - docker-rollout detected as PATH binary or docker cli-plugin.
#   - iptables/DOCKER-USER unverifiable -> FATAL (ADR-010 invariant, not WARN).
#   - Tag format validated: ^(v?\d+\.\d+\.\d+|\d{7,40}|sha-[0-9a-f]{7,40})$.
set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
CANONICAL_HOST="${CANONICAL_HOST:-uralsfish.ru}"
COMPOSE=(docker compose -f "$COMPOSE_FILE")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] FATAL: %s\n' "$*" >&2; exit 1; }

on_err() {
  local ec=$?
  printf '[deploy] FAILED (exit %d) at %s:%s. Current state:\n' "$ec" "$0" "$1" >&2
  "${COMPOSE[@]}" ps >&2 || true
  printf '[deploy] Recovery: ./scripts/rollback.sh <previous-immutable-tag>\n' >&2
  exit "$ec"
}
trap 'on_err "$LINENO"' ERR

# Compose auto-loads root .env for interpolation; load cascade into shell for our own checks.
# Shell-compatible files only (KEY=VALUE, no multiline), same contract as config/env.py.
if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi
if [[ -f ".env.${APP_ENV:-}" ]]; then
  set -a; . ".env.${APP_ENV}"; set +a
fi

# ---------- preflight ----------
preflight() {
  [[ -n "${APP_ENV:-}" ]] || die "APP_ENV is required"
  [[ -n "${APP_IMAGE_TAG:-}" ]] || die "APP_IMAGE_TAG is required (git SHA or semver)"
  case "$APP_IMAGE_TAG" in
    latest|""|*:latest)
      die "APP_IMAGE_TAG=$APP_IMAGE_TAG is mutable; ADR-009 requires immutable tag (git SHA or semver)" ;;
  esac
  [[ "$APP_IMAGE_TAG" =~ ^(v?[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$|[0-9a-f]{7,40}$|sha-[0-9a-f]{7,40}$) ]] \
    || die "APP_IMAGE_TAG=$APP_IMAGE_TAG is not a semver or git SHA"

  [[ -f ".env.${APP_ENV}" ]] || die ".env.${APP_ENV} not found"
  [[ -f nginx/nginx.conf ]] || die "nginx/nginx.conf missing"

  # ADR-010: bootstrap runtime directory and seed cloudflare-ips.conf if absent.
  mkdir -p data/nginx-dynamic
  if [[ ! -f data/nginx-dynamic/cloudflare-ips.conf ]]; then
    [[ -f nginx/cloudflare-ips.seed.conf ]] \
      || die "data/nginx-dynamic/cloudflare-ips.conf missing and nginx/cloudflare-ips.seed.conf not found"
    install -m 0644 nginx/cloudflare-ips.seed.conf data/nginx-dynamic/cloudflare-ips.conf
  fi

  [[ -f data/nginx-dynamic/.htpasswd ]] || die "data/nginx-dynamic/.htpasswd must be a regular file"

  local cf_count
  cf_count="$(grep -cE '^[[:space:]]*set_real_ip_from[[:space:]]' data/nginx-dynamic/cloudflare-ips.conf || true)"
  [[ "$cf_count" -ge 15 ]] \
    || die "cloudflare-ips.conf has $cf_count set_real_ip_from entries (< ADR-010 floor of 15)"

  [[ -d data/ssl ]] || die "data/ssl directory missing (cert-init bind mount)"

  docker info >/dev/null 2>&1 || die "docker daemon unreachable"
  docker compose version >/dev/null 2>&1 || die "docker compose plugin missing"

  docker volume inspect pgdata >/dev/null 2>&1 \
    || die "external volume pgdata missing; create once: docker volume create pgdata"

  # ADR-010: DOCKER-USER must be populated BEFORE nginx publishes 80/443.
  # Unverifiable invariant is FATAL, not WARN: unverifiable != absent invariant.
  if ! command -v iptables >/dev/null 2>&1; then
    die "iptables unavailable; cannot verify DOCKER-USER ingress firewall (ADR-010)"
  fi
  iptables -S DOCKER-USER >/dev/null 2>&1 \
    || die "iptables chain DOCKER-USER missing; ingress firewall (ADR-010) not applied"
  local duser_count
  duser_count="$(iptables -S DOCKER-USER | grep -cE '^-A ' || true)"
  [[ "$duser_count" -ge 1 ]] \
    || die "DOCKER-USER is empty; origin reachable in bypass of Cloudflare (ADR-010)"

  log "preflight OK (APP_ENV=$APP_ENV, APP_IMAGE_TAG=$APP_IMAGE_TAG)"
}

# ---------- helpers ----------
container_id() { "${COMPOSE[@]}" ps -q "$1" | head -1; }

wait_healthy() {
  local service="$1" timeout="${2:-120}" elapsed=0 cid status
  log "waiting $service healthy (<=${timeout}s)"
  while :; do
    cid="$(container_id "$service" || true)"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo none)"
      if [[ "$status" == "healthy" ]]; then
        log "$service healthy"
        return 0
      fi
    else
      status="not-running"
    fi
    [[ "$elapsed" -ge "$timeout" ]] && die "$service not healthy in ${timeout}s (last=$status)"
    sleep 2; elapsed=$((elapsed+2))
  done
}

image_present() { docker image inspect "$1" >/dev/null 2>&1; }

ensure_image() {
  local image_ref="${APP_IMAGE_REPO:-fish-workshop}:${APP_IMAGE_TAG}"
  if image_present "$image_ref"; then
    log "image present: $image_ref"
    return
  fi
  if [[ "${BUILD_LOCAL:-0}" == "1" ]]; then
    log "building image: $image_ref"
    "${COMPOSE[@]}" build web
  else
    log "pulling image: $image_ref"
    "${COMPOSE[@]}" pull web \
      || die "pull failed for $image_ref; set BUILD_LOCAL=1 to build locally"
  fi
  image_present "$image_ref" || die "image $image_ref still missing after ensure"
}

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

# LE issuance + publication into ./data/ssl (flat paths for nginx.conf).
# Idempotent: skipped when a cert for $CANONICAL_HOST already exists.
issue_le_cert() {
  log "ensuring LE certificate for $CANONICAL_HOST (webroot)"
  "${COMPOSE[@]}" --profile tls run --rm --entrypoint sh certbot -c "
    [ -f /etc/letsencrypt/live/${CANONICAL_HOST}/fullchain.pem ] || \
    certbot certonly --webroot -w /var/www/certbot -d ${CANONICAL_HOST} \
      --email ${LE_EMAIL:?LE_EMAIL required for ACME registration} --agree-tos --non-interactive"

  log "publishing certificate into data/ssl"
  "${COMPOSE[@]}" --profile tls run --rm --entrypoint sh certbot -c "
    cp -L /etc/letsencrypt/live/${CANONICAL_HOST}/fullchain.pem /ssl-out/fullchain.pem && \
    cp -L /etc/letsencrypt/live/${CANONICAL_HOST}/privkey.pem   /ssl-out/privkey.pem"

  log "reloading nginx with new certificate"
  "${COMPOSE[@]}" exec -T nginx nginx -t
  "${COMPOSE[@]}" exec -T nginx nginx -s reload
}

smoke_test() {
  local code
  log "smoke: nginx health"
  wait_healthy nginx 60

  # SNI-correct probes: -H 'Host: ...' does NOT set SNI; an IP literal would hit
  # the 443 default_server (ssl_reject_handshake) and every check would return 000.
  log "smoke: /healthz/ must be 404 externally"
  code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/healthz/" || true)"
  [[ "$code" == "404" ]] || die "/healthz/ returned $code (expected 404)"

  log "smoke: /exchange/ must be 404 externally"
  code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/exchange/" || true)"
  [[ "$code" == "404" ]] || die "/exchange/ returned $code (expected 404)"

  log "smoke: canonical / reachable"
  code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/" || true)"
  [[ "$code" =~ ^(200|301|302)$ ]] || die "canonical / returned $code"

  log "smoke OK"
}

# ---------- deploy ----------
main() {
  preflight
  ensure_image

  log "starting postgres, redis"
  "${COMPOSE[@]}" up -d --no-deps postgres redis
  wait_healthy postgres 90
  wait_healthy redis 30

  # Expand/Contract: this release may only ADD backward-compatible changes.
  # DROP/RENAME belong to a follow-up release after the old code is gone.
  log "migrations (expand/contract; no destructive DDL in same release)"
  "${COMPOSE[@]}" run --rm migrate-job

  # Copy hashed static from image to static_volume. Previous release's hashes are preserved.
  log "publishing static assets"
  "${COMPOSE[@]}" run --rm static-publish-job

  # Idempotent placeholder cert (never overwrites a valid pair).
  log "ensuring placeholder TLS (cert-init)"
  "${COMPOSE[@]}" run --rm cert-init

  # web: start-first. New replicas become healthy before old ones exit; nginx picks them
  # up via upstream `resolve` + Docker DNS (no reload needed).
  rollout_service web
  wait_healthy web 120

  # worker: SIGTERM -> finish current task -> exit. Queue survives (locked_until lease).
  log "recreating worker"
  "${COMPOSE[@]}" up -d --no-deps worker
  wait_healthy worker 90

  # nginx: image is pinned; config-only change -> test + reload (zero downtime).
  if "${COMPOSE[@]}" ps --status running --services | grep -qx nginx; then
    log "nginx -t + reload"
    "${COMPOSE[@]}" exec -T nginx nginx -t
    "${COMPOSE[@]}" exec -T nginx nginx -s reload
  else
    log "starting nginx"
    "${COMPOSE[@]}" up -d --no-deps nginx
  fi

  # Stub -> real certificate, idempotent; no-op when LE cert already published.
  issue_le_cert

  smoke_test
  log "deploy complete: APP_IMAGE_TAG=$APP_IMAGE_TAG"
  log "record this tag as the previous-release pointer for the next deploy/rollback"
}

main "$@"