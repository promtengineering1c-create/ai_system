#!/bin/sh
# certbot --deploy-hook: publish the renewed certkey from $RENEWED_LINEAGE
# (/etc/letsencrypt/live/<domain>/, bind ./data/letsencrypt) to /ssl-out
# (bind ./data/ssl), where nginx reads them.
#
# Contract: runs inside the certbot container. No docker socket, no path to
# the nginx process. Writes files only; `nginx -s reload` is the caller's job
# (host cron, AFTER certbot exits 0).
#
# Invariant: /ssl-out always holds a CONSISTENT cert+key pair.
# - the new pair is staged in a temp dir inside $DST and verified (SPKI
#   pubkey match) BEFORE anything in $DST is touched;
# - the swap is two renames; if the second fails, the previous pair is
#   restored from backup. Any midway failure leaves the OLD pair, never a
#   mixed one (mixed pair detonates on the next nginx reload/restart).
set -eu

: "${RENEWED_LINEAGE:?RENEWED_LINEAGE not set — must be invoked via certbot deploy-hook}"

SRC="$RENEWED_LINEAGE"
DST=/ssl-out

[ -s "$SRC/fullchain.pem" ] || { echo "[deploy-hook] missing $SRC/fullchain.pem" >&2; exit 1; }
[ -s "$SRC/privkey.pem" ]   || { echo "[deploy-hook] missing $SRC/privkey.pem" >&2; exit 1; }
[ -d "$DST" ]               || { echo "[deploy-hook] $DST not mounted" >&2; exit 1; }

STAGE="$(mktemp -d "$DST/.incoming.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT INT TERM

# 1. stage the new pair; DST untouched on any failure here
cp "$SRC/fullchain.pem" "$STAGE/fullchain.pem"
cp "$SRC/privkey.pem"   "$STAGE/privkey.pem"
chmod 0644 "$STAGE/fullchain.pem"
chmod 0600 "$STAGE/privkey.pem"

# 2. verify the staged pair BEFORE touching DST: SPKI pubkey byte-compare
# (RSA, ECDSA, Ed25519). pythoncryptography are hard deps of the certbot
# image; the openssl CLI is not guaranteed there.
python3 - "$STAGE" <<'EOF'
import sys

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

d = sys.argv[1]
with open(d + "/fullchain.pem", "rb") as f:
    cert = x509.load_pem_x509_certificate(f.read())
with open(d + "/privkey.pem", "rb") as f:
    key = serialization.load_pem_private_key(f.read(), password=None)

cert_spki = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
key_spki = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
sys.exit(0 if cert_spki == key_spki else 1)
EOF

# 3. backup the current pair for rollback
cp "$DST/fullchain.pem" "$STAGE/old-fullchain.pem" 2>/dev/null || true
cp "$DST/privkey.pem"   "$STAGE/old-privkey.pem"   2>/dev/null || true

# 4. swap: two renames; if the second fails, restore the previous pair
mv -f "$STAGE/fullchain.pem" "$DST/fullchain.pem"
if ! mv -f "$STAGE/privkey.pem" "$DST/privkey.pem"; then
    if [ -f "$STAGE/old-fullchain.pem" ]; then
        mv -f "$STAGE/old-fullchain.pem" "$DST/fullchain.pem" || \
            echo "[deploy-hook] FATAL: rollback failed — $DST may hold a mixed pair" >&2
    fi
    echo "[deploy-hook] FATAL: swap failed; previous pair restored" >&2
    exit 1
fi

echo "[deploy-hook] published new pair to $DST; host cron must run: scripts/cc.sh reload-nginx"
