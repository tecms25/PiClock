#!/bin/bash
# Generate the self-signed certificate the control panel serves HTTPS with.
#
#   bash web/make_cert.sh
#
# Self-signed means your browser will warn once and then remember it. That is
# still worth having: without TLS the panel password crosses your LAN in clear
# text, where anything else on the network can read it.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CERT="$REPO_DIR/conf/web-cert.pem"
KEY="$REPO_DIR/conf/web-key.pem"
DAYS=3650

if ! command -v openssl >/dev/null 2>&1; then
  echo "ERROR: openssl was not found. Install it and run this again."
  exit 1
fi

mkdir -p "$REPO_DIR/conf"

if [ -f "$CERT" ] || [ -f "$KEY" ]; then
  read -r -p "A certificate already exists. Replace it? [y/N] " REPLY
  if [ "$REPLY" != "y" ] && [ "$REPLY" != "Y" ]; then
    echo "Keeping the existing certificate."
    exit 0
  fi
fi

HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname)"

# Every name and address the Pi might be reached by goes in the SAN list, since
# browsers ignore the old CN field entirely. Without a matching entry you get a
# name-mismatch error on top of the self-signed one.
ALT="DNS:${HOSTNAME_SHORT},DNS:${HOSTNAME_SHORT}.local,DNS:localhost,IP:127.0.0.1"
while read -r ip; do
  [ -n "$ip" ] && ALT="$ALT,IP:$ip"
done <<EOF
$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' || true)
EOF

echo "Creating a $DAYS day self-signed certificate for:"
echo "  $ALT"
echo ""

# The key is created with a restrictive umask: a private key that is briefly
# world readable has been world readable.
OLD_UMASK="$(umask)"
umask 077
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$KEY" -out "$CERT" -days "$DAYS" \
  -subj "/CN=${HOSTNAME_SHORT}" \
  -addext "subjectAltName=${ALT}" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" 2>/dev/null
umask "$OLD_UMASK"

chmod 600 "$KEY"
chmod 644 "$CERT"

echo "Wrote:"
echo "  $CERT"
echo "  $KEY"
echo ""
echo "Your browser will warn the first time; accept it once and it is remembered."
