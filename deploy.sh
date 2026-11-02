#!/usr/bin/env bash
# Pull the latest pages onto the droplet. No restart needed: nginx serves the files directly.
set -euo pipefail
cd "$(dirname "$0")"
git fetch --quiet origin main
git reset --hard origin/main
echo "destinyos updated to $(git rev-parse --short HEAD)"
