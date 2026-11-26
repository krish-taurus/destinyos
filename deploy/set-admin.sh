#!/usr/bin/env bash
# Set the admin panel's email and password. Run on the droplet:  sudo bash /opt/destinyos-src/deploy/set-admin.sh
# The password is typed here, hidden, and stored only in /etc/destinyos.env (readable by root alone).
set -euo pipefail
ENVF=/etc/destinyos.env
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
read -rp "Admin email: " EMAIL
case "$EMAIL" in *@*.*) ;; *) echo "That doesn't look like an email address."; exit 1;; esac
read -rsp "New admin password (12 or more characters): " P1; echo
read -rsp "Type it again: " P2; echo
[ "$P1" = "$P2" ] || { echo "The two passwords don't match. Nothing changed."; exit 1; }
[ "${#P1}" -ge 12 ] || { echo "Use at least 12 characters. Nothing changed."; exit 1; }
case "$P1" in *[\'\"\\\ ]*) echo "Leave out spaces, quotes and backslashes. Nothing changed."; exit 1;; esac
sed -i '/^ADMIN_EMAIL=/d;/^ADMIN_PASSWORD=/d' "$ENVF"
printf 'ADMIN_EMAIL=%s\nADMIN_PASSWORD=%s\n' "$EMAIL" "$P1" >> "$ENVF"
chmod 600 "$ENVF"; unset P1 P2
systemctl restart destinyos-api
echo "Done. Sign in at https://destinyos.in/admin/ with $EMAIL and your new password."
