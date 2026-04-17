#!/usr/bin/env bash
set -euo pipefail

# Sync FreePBX RTP/SIP advertised address to current host LAN IP.
# Useful when moving between Wi-Fi networks where host IP changes often.

FREEPBX_CONTAINER="${FREEPBX_CONTAINER:-freepbx}"
ENDPOINTS="${ENDPOINTS:-6000 7000}"
TMP_OVERRIDES=""

cleanup() {
  if [[ -n "${TMP_OVERRIDES:-}" && -f "${TMP_OVERRIDES:-}" ]]; then
    rm -f "$TMP_OVERRIDES"
  fi
}

detect_host_ip() {
  local ip=""

  # macOS: detect default interface then fetch its IPv4
  if command -v route >/dev/null 2>&1 && command -v ipconfig >/dev/null 2>&1; then
    local iface
    iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' | head -n1 || true)"
    if [[ -n "${iface:-}" ]]; then
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    fi
  fi

  # Linux fallback
  if [[ -z "${ip:-}" ]] && command -v ip >/dev/null 2>&1; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || true)"
  fi

  # Generic fallback
  if [[ -z "${ip:-}" ]] && command -v ifconfig >/dev/null 2>&1; then
    ip="$(ifconfig 2>/dev/null | awk '/inet / && $2 != "127.0.0.1" {print $2; exit}' || true)"
  fi

  if [[ -z "${ip:-}" ]]; then
    echo "ERROR: Could not detect host IPv4 address." >&2
    exit 1
  fi

  echo "$ip"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker command not found." >&2
    exit 1
  fi
}

build_endpoint_overrides() {
  local host_ip="$1"
  local tmp_file="$2"
  : >"$tmp_file"

  for ext in $ENDPOINTS; do
    cat >>"$tmp_file" <<EOF
[${ext}](+)
direct_media=no
media_address=${host_ip}
rtp_symmetric=yes
rewrite_contact=yes
force_rport=yes
rtp_timeout=0
rtp_timeout_hold=0

EOF
  done
}

main() {
  require_docker

  local host_ip
  host_ip="$(detect_host_ip)"
  echo "Detected host IP: ${host_ip}"

  TMP_OVERRIDES="$(mktemp)"
  trap cleanup EXIT
  build_endpoint_overrides "$host_ip" "$TMP_OVERRIDES"

  echo "Updating FreePBX container: ${FREEPBX_CONTAINER}"

  # Update newer FreePBX versions (kvstore_Sipsettings)
  docker exec "$FREEPBX_CONTAINER" bash -lc "mysql -u root -e 'USE asterisk;
UPDATE kvstore_Sipsettings SET val=\"${host_ip}\" WHERE \`key\`=\"externip\";
UPDATE kvstore_Sipsettings SET val=\"${host_ip}\" WHERE \`key\`=\"externip.val\";' 2>/dev/null || true"

  # Update older FreePBX versions (sipsettings), ignore if table doesn't exist
  docker exec "$FREEPBX_CONTAINER" bash -lc "mysql -u root -e 'USE asterisk;
UPDATE sipsettings SET data=\"${host_ip}\" WHERE keyword=\"externip_val\";' 2>/dev/null || true"

  docker cp "$TMP_OVERRIDES" "${FREEPBX_CONTAINER}:/etc/asterisk/pjsip.endpoint_custom.conf"

  docker exec "$FREEPBX_CONTAINER" bash -lc "fwconsole reload"

  echo "Verification:"
  docker exec "$FREEPBX_CONTAINER" bash -lc "asterisk -rx 'pjsip show transport 0.0.0.0-udp' | grep -i 'external_\\|local_net' || true"

  # Show first endpoint only for a quick sanity check.
  local first_ext
  first_ext="$(echo "$ENDPOINTS" | awk '{print $1}')"
  if [[ -n "${first_ext:-}" ]]; then
    docker exec "$FREEPBX_CONTAINER" bash -lc \
      "asterisk -rx 'pjsip show endpoint ${first_ext}' | egrep 'direct_media|media_address|rtp_symmetric|rewrite_contact|force_rport' || true"
  fi

  echo "Done. Re-register Zoiper and test *44 / *43."
}

main "$@"
