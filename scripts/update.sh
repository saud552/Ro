#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/update.sh /opt/ro-bot
APP_DIR="${1:-/opt/ro-bot}"
SERVICE_NAME="ro-bot.service"

if [ ! -d "$APP_DIR" ]; then
	echo "App directory not found: $APP_DIR" >&2
	exit 1
fi

cd "$APP_DIR"

# Sync latest from remote if the app dir is a git clone; otherwise rsync from current dir
if [ -d .git ]; then
	git fetch --all
	git reset --hard origin/$(git rev-parse --abbrev-ref HEAD || echo main)
else
	echo "WARNING: $APP_DIR is not a git clone. Skipping git pull." >&2
fi

# Install deps
source .venv/bin/activate || true
pip install --upgrade pip
pip install -r requirements.txt

# Migrations (safe)
export DATABASE_URL=$(grep -E '^DATABASE_URL=' .env | cut -d'=' -f2-)
if [ -z "${DATABASE_URL:-}" ]; then
	export DATABASE_URL="sqlite+aiosqlite:///./db.sqlite3"
fi
export PYTHONPATH="$APP_DIR"
alembic upgrade head

# Restart service
sudo systemctl restart "$SERVICE_NAME"

echo "Update complete. Service restarted: $SERVICE_NAME"