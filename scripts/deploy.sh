#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/deploy.sh /opt/ro-bot
# Requires: BOT_TOKEN, BOT_CHANNEL, DATABASE_URL (optional), ADMIN_IDS in environment or .env

APP_DIR="${1:-/opt/ro-bot}"
PYTHON_BIN="python3"

if ! command -v $PYTHON_BIN >/dev/null 2>&1; then
	echo "python3 not found. Install Python 3.11+ first." >&2
	exit 1
fi

sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

# Copy repository
rsync -a --delete --exclude ".git" ./ "$APP_DIR"/
cd "$APP_DIR"

# Python venv
if [ ! -d .venv ]; then
	$PYTHON_BIN -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Env
generate_secret() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -hex 16
	else
		head -c 16 /dev/urandom | xxd -p
	fi
}

if [ ! -f .env ]; then
	REDIS_DEFAULT=""
	if command -v redis-cli >/dev/null 2>&1 || systemctl list-unit-files | grep -q redis; then
		REDIS_DEFAULT="redis://localhost:6379/0"
	fi
	WEBHOOK_SECRET_GEN=$(generate_secret)
	cat > .env <<EOF
BOT_TOKEN=CHANGEME_BOT_TOKEN
BOT_CHANNEL=@CHANGE_ME
DATABASE_URL=sqlite+aiosqlite:///./db.sqlite3
REDIS_URL=$REDIS_DEFAULT
ADMIN_IDS=
WEBHOOK_URL=
WEBHOOK_PATH_TEMPLATE=/webhook/{token}
WEBHOOK_SECRET=$WEBHOOK_SECRET_GEN
WEBAPP_HOST=0.0.0.0
WEBAPP_PORT=8080
EOF
	echo "Generated .env template. Please set BOT_TOKEN, BOT_CHANNEL, ADMIN_IDS, and optionally REDIS_URL/WEBHOOK_URL." >&2
fi

# Alembic migrations
export DATABASE_URL=$(grep -E '^DATABASE_URL=' .env | cut -d'=' -f2-)
if [ -z "${DATABASE_URL:-}" ]; then
	export DATABASE_URL="sqlite+aiosqlite:///./db.sqlite3"
fi
export PYTHONPATH="$APP_DIR"
alembic upgrade head

# Systemd service
SERVICE_NAME="ro-bot.service"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

SERVICE_CONTENT="[Unit]
Description=Ro Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"

echo "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "Deployment complete. Service: $SERVICE_NAME"
