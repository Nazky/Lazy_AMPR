#!/bin/sh
# Run as PUID:PGID (Unraid default 99:100 = nobody:users) so created files
# on the array belong to the usual share owner.
set -e

umask "${UMASK:-000}"
mkdir -p /config

if [ "$(id -u)" = "0" ] && [ "${PUID:-0}" != "0" ]; then
    chown "${PUID}:${PGID:-100}" /config 2>/dev/null || true
    # Only fix ownership of our own files, never of mounted game data.
    [ -d /config/lazy_ampr ] && chown -R "${PUID}:${PGID:-100}" /config/lazy_ampr 2>/dev/null || true
    exec setpriv --reuid="${PUID}" --regid="${PGID:-100}" --clear-groups "$@"
fi

exec "$@"
