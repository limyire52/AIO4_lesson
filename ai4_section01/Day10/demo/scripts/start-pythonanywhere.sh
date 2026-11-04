#!/bin/bash
set -euo pipefail
# PythonAnywhere runs this script in a new process; interactive console exports do not persist.
TASK_USER="$(id -un)"
PROJECT_DIR="/home/${TASK_USER}/community-demo"
export DATABASE_PATH="/home/${TASK_USER}/community-data/community.sqlite3"
export COOKIE_SECURE=1
export SESSION_SECONDS=7200
# For an EU account change this to https://${TASK_USER}.eu.pythonanywhere.com.
export PUBLIC_ORIGIN="https://${TASK_USER}.pythonanywhere.com"
exec "/home/${TASK_USER}/.virtualenvs/community-demo/bin/uvicorn" \
  --app-dir "$PROJECT_DIR" --uds "${DOMAIN_SOCKET:?PythonAnywhere ASGI socket is required}" \
  --workers 1 --proxy-headers --forwarded-allow-ips "${TRUSTED_PROXY_IPS:-127.0.0.1,::1}" \
  app.main:app
