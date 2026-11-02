#!/usr/bin/env bash
# Deploy Destiny OS (site + API) from GitHub onto this droplet. Run as root:
#   bash /opt/destinyos-src/deploy/deploy.sh             # deploy main
#   BRANCH=build-platform bash deploy.sh                  # deploy a branch
# Every run backs up the current site, API and database first (/var/backups/destinyos), runs the test
# suite, and aborts without touching anything if a test fails. Roll back with deploy/rollback.sh.
set -euo pipefail
BRANCH="${BRANCH:-main}"
REPO=/opt/destinyos-src
APP=/var/www/destinyos
DATA=/var/lib/destinyos
ENVF=/etc/destinyos.env
export GIT_SSH_COMMAND="ssh -i /root/.ssh/destinyos_deploy -o StrictHostKeyChecking=accept-new"
command -v rsync >/dev/null || apt-get install -y -qq rsync >/dev/null

echo "== 1/7 fetch $BRANCH"
[ -d "$REPO/.git" ] || git clone -q git@github.com:krish-taurus/destinyos.git "$REPO"
git -C "$REPO" fetch -q origin "$BRANCH"
git -C "$REPO" checkout -q -B deploy "origin/$BRANCH"
echo "   at $(git -C "$REPO" log -1 --format='%h %s')"

echo "== 2/7 test"
"$APP/venv/bin/pip" install -q pytest >/dev/null
(cd "$REPO/server/backend" && "$APP/venv/bin/python" -m pytest -q -p no:cacheprovider tests) || { echo "TESTS FAILED: nothing deployed."; exit 1; }

echo "== 3/7 backup"
TS=$(date +%Y%m%d-%H%M%S); mkdir -p /var/backups/destinyos; chmod 700 /var/backups/destinyos
tar czf "/var/backups/destinyos/code-$TS.tgz" -C "$APP" frontend backend
if [ -f "$DATA/destinyos.db" ]; then
  "$APP/venv/bin/python" -c "import sqlite3,sys;s=sqlite3.connect(sys.argv[1]);d=sqlite3.connect(sys.argv[2]);s.backup(d)" \
    "$DATA/destinyos.db" "/var/backups/destinyos/db-$TS.sqlite"
fi
ls -1t /var/backups/destinyos/code-*.tgz | tail -n +11 | xargs -r rm -f      # keep the last 10
echo "   saved as $TS"

echo "== 4/7 config"
SVC_USER=$(systemctl show -p User --value destinyos-api); SVC_USER=${SVC_USER:-root}
mkdir -p "$DATA"; chown "$SVC_USER" "$DATA"; chmod 700 "$DATA"
grep -q '^SESSION_SECRET=' "$ENVF" || echo "SESSION_SECRET=$(openssl rand -hex 32)" >> "$ENVF"
grep -q '^DESTINY_DB=' "$ENVF"     || echo "DESTINY_DB=$DATA/destinyos.db" >> "$ENVF"
grep -q '^COOKIE_SECURE=' "$ENVF"  || echo "COOKIE_SECURE=1" >> "$ENVF"
chmod 600 "$ENVF"

echo "== 5/7 install"
rsync -a --delete --exclude tests --exclude __pycache__ --exclude '.env*' "$REPO/server/backend/" "$APP/backend/"
rsync -a --delete "$REPO/site/" "$APP/frontend/"
chown -R www-data:www-data "$APP/frontend"; chown -R "$SVC_USER" "$APP/backend"
"$APP/venv/bin/pip" install -q -r "$APP/backend/requirements.txt"

echo "== 6/7 daily WhatsApp timer (7:00 IST)"
sed "s/__USER__/$SVC_USER/" "$REPO/deploy/destinyos-daily.service" > /etc/systemd/system/destinyos-daily.service
cp "$REPO/deploy/destinyos-daily.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q --now destinyos-daily.timer

echo "== 7/7 restart and check"
systemctl restart destinyos-api; sleep 3
curl -fsS http://127.0.0.1:8100/api/health && echo
for u in / /app/ /business/ /free-report/; do printf "   %-14s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' "https://destinyos.in$u")"; done
echo "DEPLOYED $(git -C "$REPO" log -1 --format=%h). If anything looks wrong: bash $REPO/deploy/rollback.sh $TS"
