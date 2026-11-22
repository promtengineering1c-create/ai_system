#!/usr/bin/env bash
# deploy.sh — release deployment.
# Invariants (ADR-009/ADR-010/ADR-011):
#   - APP_IMAGE_TAG must be immutable (git SHA / semver), `latest` rejected.
#   - CLI-passed APP_ENV / APP_IMAGE_TAG take precedence over .env files.
#   - DB credentials / POSTGRES_* are forbidden in .env.<APP_ENV> (L1) and compose config validated (L2).
#   - Migrations follow Expand/Contract: rollback of web/worker does NOT roll back schema.
#   - web rolled out start-first (docker-rollout); fallback `up -d` accepted with 5-15s window.
#   - worker controlled via ENABLE_WORKER=1 (enabled from Stage 7 when cli/run_worker is active).
#   - Ingress firewall (DOCKER-USER, CF-only) MUST be verified in production before nginx publishes 80/443.
#   - LE certificate issuance (canonical + www) runs only in production; publication into data/ssl is atomic.
set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
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

# Preserve CLI overrides before sourcing .env cascade so base .env cannot shadow them.
_CLI_APP_ENV="${APP_ENV:-}"
_CLI_APP_IMAGE_TAG="${APP_IMAGE_TAG:-}"
_CLI_ENABLE_WORKER="${ENABLE_WORKER:-}"
_CLI_BUILD_LOCAL="${BUILD_LOCAL:-}"
_CLI_CANONICAL_HOST="${CANONICAL_HOST:-}"
_CLI_LE_EMAIL="${LE_EMAIL:-}"
_CLI_REQUIRE_FIREWALL="${REQUIRE_FIREWALL:-}"

# Shell-compatible files only (KEY=VALUE, no multiline), same contract as config/env.py.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

[[ -n "$_CLI_APP_ENV" ]] && APP_ENV="$_CLI_APP_ENV"
[[ -n "$_CLI_APP_IMAGE_TAG" ]] && APP_IMAGE_TAG="$_CLI_APP_IMAGE_TAG"

if [[ -n "${APP_ENV:-}" && -f ".env.${APP_ENV}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . ".env.${APP_ENV}"
  set +a
fi

# Re-apply CLI overrides so explicit invocation arguments always win.
[[ -n "$_CLI_APP_ENV" ]] && APP_ENV="$_CLI_APP_ENV"
[[ -n "$_CLI_APP_IMAGE_TAG" ]] && APP_IMAGE_TAG="$_CLI_APP_IMAGE_TAG"
[[ -n "$_CLI_ENABLE_WORKER" ]] && ENABLE_WORKER="$_CLI_ENABLE_WORKER"
[[ -n "$_CLI_BUILD_LOCAL" ]] && BUILD_LOCAL="$_CLI_BUILD_LOCAL"
[[ -n "$_CLI_CANONICAL_HOST" ]] && CANONICAL_HOST="$_CLI_CANONICAL_HOST"
[[ -n "$_CLI_LE_EMAIL" ]] && LE_EMAIL="$_CLI_LE_EMAIL"
[[ -n "$_CLI_REQUIRE_FIREWALL" ]] && REQUIRE_FIREWALL="$_CLI_REQUIRE_FIREWALL"

CANONICAL_HOST="${CANONICAL_HOST:-uralsfish.ru}"
ENABLE_WORKER="${ENABLE_WORKER:-0}"
export APP_ENV="${APP_ENV:-}"
export APP_IMAGE_TAG="${APP_IMAGE_TAG:-}"

# ---------- preflight ----------
verify_firewall() {
  local iptables_bin=""
  if command -v iptables >/dev/null 2>&1; then
    iptables_bin="$(command -v iptables)"
  elif [[ -x /usr/sbin/iptables ]]; then
    iptables_bin="/usr/sbin/iptables"
  elif [[ -x /sbin/iptables ]]; then
    iptables_bin="/sbin/iptables"
  else
    die "iptables unavailable; cannot verify DOCKER-USER ingress firewall (ADR-010)"
  fi

  local -a ipt_cmd=("$iptables_bin")
  if [[ "${EUID}" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 \
      || die "root privileges or sudo required to inspect iptables DOCKER-USER (ADR-010)"
    ipt_cmd=(sudo -n "$iptables_bin")
  fi

  local rules
  if ! rules="$("${ipt_cmd[@]}" -S DOCKER-USER 2>&1)"; then
    if [[ "$rules" == *"password is required"* || "$rules" == *"Permission denied"* || "$rules" == *"Operation not permitted"* ]]; then
      die "cannot inspect DOCKER-USER without root/NOPASSWD sudo: $rules"
    fi
    die "iptables chain DOCKER-USER missing; ingress firewall (ADR-010) not applied"
  fi

  local duser_count
  duser_count="$(printf '%s\n' "$rules" | grep -cE '^-A ' || true)"
  [[ "$duser_count" -ge 1 ]] \
    || die "DOCKER-USER is empty; origin reachable in bypass of Cloudflare (ADR-010)"
}

preflight() {
  [[ -n "${APP_ENV:-}" ]] || die "APP_ENV is required"
  [[ -n "${APP_IMAGE_TAG:-}" ]] || die "APP_IMAGE_TAG is required (git SHA or semver)"
  case "$APP_IMAGE_TAG" in
    latest|""|*:latest)
      die "APP_IMAGE_TAG=$APP_IMAGE_TAG is mutable; ADR-009 requires immutable tag (git SHA or semver)" ;;
  esac
  [[ "$APP_IMAGE_TAG" =~ ^(v?[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?|[0-9a-f]{7,40}|sha-[0-9a-f]{7,40})$ ]] \
    || die "APP_IMAGE_TAG=$APP_IMAGE_TAG is not a semver or git SHA"

  [[ -f ".env.${APP_ENV}" ]] || die ".env.${APP_ENV} not found"
  [[ -f nginx/nginx.conf ]] || die "nginx/nginx.conf missing"

  # L1 (ADR-011): DB credentials must reside strictly in base .env, never in .env.<APP_ENV>.
  if grep -qE '^[[:space:]]*(DB_(HOST|PORT|NAME|USER|PASSWORD)|POSTGRES_[A-Z0-9_]+)=' ".env.${APP_ENV}"; then
    die "DB credentials or POSTGRES_* leaked into .env.${APP_ENV}; keep them only in base .env (ADR-011)"
  fi

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

  # L2: validate resolved Compose configuration before touching running containers.
  "${COMPOSE[@]}" config --quiet || die "docker compose config validation failed (L2)"

  docker volume inspect pgdata >/dev/null 2>&1 \
    || die "external volume pgdata missing; create once: docker volume create pgdata"

  # ADR-010: DOCKER-USER invariant is mandatory in production (or when REQUIRE_FIREWALL=1).
  local require_fw="${REQUIRE_FIREWALL:-}"
  if [[ -z "$require_fw" ]]; then
    [[ "$APP_ENV" == "production" ]] && require_fw="1" || require_fw="0"
  fi
  if [[ "$require_fw" == "1" ]]; then
    verify_firewall
  else
    log "skipping DOCKER-USER check (APP_ENV=$APP_ENV, REQUIRE_FIREWALL=$require_fw)"
  fi

  log "preflight OK (APP_ENV=$APP_ENV, APP_IMAGE_TAG=$APP_IMAGE_TAG, ENABLE_WORKER=$ENABLE_WORKER)"
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

# LE issuance + atomic publication into ./data/ssl (flat paths for nginx.conf).
# Runs only in production; idempotent when cert for $CANONICAL_HOST already exists.
issue_le_cert() {
  if [[ "$APP_ENV" != "production" ]]; then
    log "skipping LE certificate issuance (APP_ENV=$APP_ENV != production)"
    return 0
  fi

  log "ensuring LE certificate for $CANONICAL_HOST and www.$CANONICAL_HOST (webroot)"
  "${COMPOSE[@]}" --profile tls run --rm \
    -e CANONICAL_HOST="$CANONICAL_HOST" \
    -e LE_EMAIL="${LE_EMAIL:-}" \
    --entrypoint sh certbot -c '
      set -eu
      if [ ! -f "/etc/letsencrypt/live/${CANONICAL_HOST}/fullchain.pem" ]; then
        : "${LE_EMAIL:?LE_EMAIL is required for initial ACME registration}"
        certbot certonly --webroot -w /var/www/certbot \
          -d "${CANONICAL_HOST}" -d "www.${CANONICAL_HOST}" \
          --email "${LE_EMAIL}" --agree-tos --non-interactive
      fi
    '

  log "publishing certificate atomically into data/ssl"
  "${COMPOSE[@]}" --profile tls run --rm \
    -e CANONICAL_HOST="$CANONICAL_HOST" \
    --entrypoint sh certbot -c '
      set -eu
      cp -L "/etc/letsencrypt/live/${CANONICAL_HOST}/fullchain.pem" /ssl-out/fullchain.pem.tmp
      cp -L "/etc/letsencrypt/live/${CANONICAL_HOST}/privkey.pem"   /ssl-out/privkey.pem.tmp
      chmod 0644 /ssl-out/fullchain.pem.tmp
      chmod 0600 /ssl-out/privkey.pem.tmp
      mv -f /ssl-out/fullchain.pem.tmp /ssl-out/fullchain.pem
      mv -f /ssl-out/privkey.pem.tmp   /ssl-out/privkey.pem
    '

  log "reloading nginx with published certificate"
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

  log "smoke: /admin/ must require HTTP Basic Auth (401)"
  code="$(curl -ksS --resolve "${CANONICAL_HOST}:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
    "https://${CANONICAL_HOST}/admin/" || true)"
  [[ "$code" == "401" ]] || die "/admin/ returned $code (expected 401)"

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

  if [[ "$ENABLE_WORKER" == "1" ]]; then
    # worker: SIGTERM -> finish current task -> exit. Queue survives (locked_until lease).
    log "recreating worker"
    "${COMPOSE[@]}" up -d --no-deps worker
    wait_healthy worker 90
  else
    log "skipping worker (ENABLE_WORKER=$ENABLE_WORKER; enable from Stage 7)"
  fi

  # nginx: image is pinned; config-only change -> test + reload (zero downtime).
  if "${COMPOSE[@]}" ps --status running --services | grep -qx nginx; then
    log "nginx -t + reload"
    "${COMPOSE[@]}" exec -T nginx nginx -t
    "${COMPOSE[@]}" exec -T nginx nginx -s reload
  else
    log "starting nginx"
    "${COMPOSE[@]}" up -d --no-deps nginx
  fi

  # Stub -> real certificate in production, idempotent; skipped in dev/staging.
  issue_le_cert

  smoke_test
  log "deploy complete: APP_IMAGE_TAG=$APP_IMAGE_TAG"
  log "record this tag as the previous-release pointer for the next deploy/rollback"
}

main "$@"