#!/bin/sh
set -eu

# Idempotent placeholder-cert bootstrap for nginx (chicken-egg for ACME HTTP-01).
# Идемпотентная инициализация временного (заглушечного) сертификата для nginx (решение проблемы взаимной зависимости «курицы и яйца» для ACME HTTP-01 validation challenge).

# Invariant: NEVER overwrite a parseable existing pair -- the same volume is
# shared with the real certificate produced by the ACME client.
# Инвариант: Строго запрещено перезаписывать существующую валидную пару (ключ/сертификат), так как этот же Docker volume совместно используется (shared) с реальным TLS-сертификатом, эмитируемым ACME-клиентом (например, Certbot).

CERT_DIR="${CERT_DIR:-/etc/nginx/ssl}"
CERT="${CERT_DIR}/fullchain.pem"
KEY="${CERT_DIR}/privkey.pem"

log() { printf '[cert-init] %s\n' "$*"; }

mkdir -p "$CERT_DIR"

if [ -s "$CERT" ] && [ -s "$KEY" ] \
   && openssl x509 -noout -in "$CERT" >/dev/null 2>&1 \
   && openssl pkey -noout -in "$KEY" >/dev/null 2>&1; then
  # nginx dies with 'key values mismatch' on an inconsistent pair
  CERT_PUB=$(openssl x509 -pubkey -noout -in "$CERT" 2>/dev/null \
             | openssl pkey -pubin -outform DER 2>/dev/null | openssl sha256)
  KEY_PUB=$(openssl pkey -pubout -in "$KEY" -outform DER 2>/dev/null | openssl sha256)
  if [ -n "$CERT_PUB" ] && [ "$CERT_PUB" = "$KEY_PUB" ]; then
    log "consistent pair already present in $CERT_DIR, leaving untouched"
    exit 0
  fi
  log "cert/key mismatch or unparsable pair in $CERT_DIR, regenerating"
fi

log "no usable pair in $CERT_DIR, generating self-signed placeholder"

# rename() атомарен только в пределах одной ФС: mktemp в /tmp (tmpfs) даёт
# cross-device mv = copy+unlock, не атомарно. Temp держим в том же bind.
TMP="$(mktemp -d "$CERT_DIR/.tmp.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT INT TERM

# 30 дней: если certbot-контур не заработает, staleness заглушки проявится быстро, а не спустя годы молчащего самоподписанного сертификата.
openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 30 \
  -keyout "$TMP/privkey.pem" \
  -out    "$TMP/fullchain.pem" \
  -subj "/CN=uralsfish.ru" \
  -addext "subjectAltName=DNS:uralsfish.ru,DNS:www.uralsfish.ru" >/dev/null 2>&1

chmod 600 "$TMP/privkey.pem"
chmod 644 "$TMP/fullchain.pem"

# atomic publish: rename() внутри bind — атомарно; mv из tmpfs был copy+unlink
mv -f "$TMP/fullchain.pem" "$CERT"
mv -f "$TMP/privkey.pem"   "$KEY"

log "placeholder installed: $CERT"
log "replace with real certificate + 'nginx -s reload' before exposing 443"

