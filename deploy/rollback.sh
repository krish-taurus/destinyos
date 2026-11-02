#!/usr/bin/env bash
# Put back the site and API saved by deploy.sh.
#   bash rollback.sh 20261102-221500     (no argument = the most recent backup)
set -euo pipefail
B=/var/backups/destinyos; APP=/var/www/destinyos
TS="${1:-$(ls -1t $B/code-*.tgz | head -1 | sed -E 's/.*code-(.*)\.tgz/\1/')}"
[ -f "$B/code-$TS.tgz" ] || { echo "No backup called $TS. Available:"; ls -1 $B; exit 1; }
rm -rf "$APP/frontend" "$APP/backend"
tar xzf "$B/code-$TS.tgz" -C "$APP"
if [ -f "$B/db-$TS.sqlite" ]; then
  echo "Database left as it is (accounts created since are kept). Its backup is $B/db-$TS.sqlite."
fi
systemctl restart destinyos-api
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8100/api/health >/dev/null 2>&1 && { echo "Restored $TS. API healthy."; exit 0; }; sleep 1; done
echo "Restored $TS but the API isn't answering yet. Check: journalctl -u destinyos-api -n 50"; exit 1
