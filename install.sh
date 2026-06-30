#!/usr/bin/env bash
# Kaptaan installer for a fresh Ubuntu VPS (e.g. AWS Lightsail).
# Idempotent: safe to re-run after every git push.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/sumit-waani/k2.git}"
APP_DIR="${APP_DIR:-/opt/kaptaan}"
DB_DIR="${DB_DIR:-/var/lib/kaptaan}"
BRANCH="${BRANCH:-main}"
DOMAIN="${DOMAIN:-_}"
APP_PORT="${APP_PORT:-8001}"
SERVICE_USER="${SERVICE_USER:-kaptaan}"

NODE_MAJOR=20
PY_MIN_MINOR=10

# ---------- helpers ----------
say()   { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()    { printf '  \033[1;32m✓\033[0m %s\n'  "$*"; }
warn()  { printf '  \033[1;33m!\033[0m %s\n'  "$*"; }
die()   { printf '\n\033[1;31m✗ %s\033[0m\n'  "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root (sudo $0)"

# ---------- FIX: git safe directory (root se run hone par ownership error aata tha) ----------
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

# ---------- 1. system packages ----------
say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg lsb-release \
    build-essential pkg-config \
    python3 python3-venv python3-pip python3-dev \
    nginx ufw

# --- Node.js 20 (NodeSource) ---
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/')" -lt "$NODE_MAJOR" ]]; then
    say "Installing Node.js $NODE_MAJOR.x"
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update -y
    apt-get install -y --no-install-recommends nodejs
fi
ok "Node $(node -v),  npm $(npm -v)"

ok "npm $(npm -v)"

# --- python version check ---
PY_MIN=$(python3 -c 'import sys; print(sys.version_info[1])')
[[ "$PY_MIN" -ge "$PY_MIN_MINOR" ]] || die "Python 3.${PY_MIN_MINOR}+ required (found 3.${PY_MIN})"
ok "Python $(python3 -V | awk '{print $2}')"

# ---------- 2. user + dirs ----------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    say "Creating service user '$SERVICE_USER'"
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$DB_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$(dirname "$APP_DIR")"

# ---------- 3. clone or update repo ----------
if [[ -d "$APP_DIR/.git" ]]; then
    say "Updating repo at $APP_DIR (branch $BRANCH)"
    cd "$APP_DIR"
    # FIX: ownership theek karo pehle, phir git pull
    chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
    git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
    git fetch --depth 1 origin "$BRANCH"
    git reset --hard "origin/$BRANCH"
else
    say "Cloning $REPO_URL → $APP_DIR"
    rm -rf "$APP_DIR"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# ---------- 4. backend venv + deps ----------
say "Setting up Python venv"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip wheel >/dev/null

sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
# Agar emergentintegrations GitHub pe available ho toh ye line uncomment karo:
# sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install \
#   git+https://github.com/sumit-waani/emergentintegrations.git 2>/dev/null || \
#   warn "emergentintegrations install nahi hua — Settings se manually add karo"

# ---------- 5. backend .env ----------
BACKEND_ENV="$APP_DIR/backend/.env"
if [[ ! -f "$BACKEND_ENV" ]]; then
    say "Writing default backend/.env"
    cat > "$BACKEND_ENV" <<EOF
CORS_ORIGINS="*"
KAPTAAN_DB_PATH="$DB_DIR/kaptaan.db"
BOOTSTRAP_USERNAME="kaptaan"
BOOTSTRAP_PASSWORD="kaptaan"
SESSION_COOKIE_SAMESITE="lax"
SESSION_COOKIE_SECURE="false"
MONGO_URL=""
DB_NAME=""
EOF
    chown "$SERVICE_USER:$SERVICE_USER" "$BACKEND_ENV"
    chmod 600 "$BACKEND_ENV"
else
    ok "Keeping existing backend/.env"
fi

# ---------- 6. db migrations ----------
say "Running DB migrations"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/python" - "$APP_DIR" <<'PY'
import asyncio, sys, os
app_dir = sys.argv[1]
backend_dir = os.path.join(app_dir, "backend")
sys.path.insert(0, backend_dir)
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))
from db import init_db, fetch_one
async def main():
    await init_db()
    r = await fetch_one("SELECT COUNT(*) AS c FROM users")
    print(f"  users={r['c']}")
asyncio.run(main())
PY
chown -R "$SERVICE_USER:$SERVICE_USER" "$DB_DIR"

# ---------- 7. frontend build ----------
say "Building frontend (Vite)"
sudo -u "$SERVICE_USER" bash -lc "cd $APP_DIR/frontend && npm install && npm run build"
ok "Built to $APP_DIR/frontend/dist"

# ---------- 8. systemd service ----------
say "Writing systemd unit"
cat > /etc/systemd/system/kaptaan.service <<EOF
[Unit]
Description=Kaptaan backend (FastAPI)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/backend/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn server:app --host 127.0.0.1 --port $APP_PORT --workers 1
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
KillSignal=SIGINT
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kaptaan.service >/dev/null

# ---------- 9. nginx ----------
say "Writing nginx site"
NGINX_SITE="/etc/nginx/sites-available/kaptaan"
cat > "$NGINX_SITE" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $DOMAIN;

    root $APP_DIR/frontend/dist;
    index index.html;

    client_max_body_size 10m;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript
               application/xml application/wasm image/svg+xml;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location ~* \\.(?:js|css|woff2?|ttf|otf|eot|svg|png|jpg|jpeg|webp|ico)\$ {
        expires 30d;
        access_log off;
        try_files \$uri =404;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        chunked_transfer_encoding on;
    }
}
EOF

ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/kaptaan
rm -f /etc/nginx/sites-enabled/default
nginx -t

# ---------- 10. firewall ----------
if command -v ufw >/dev/null 2>&1; then
    ufw --force enable >/dev/null 2>&1 || true
    ufw allow OpenSSH >/dev/null 2>&1 || true
    ufw allow "Nginx Full" >/dev/null 2>&1 || true
fi

# ---------- 11. restart ----------
say "Restarting services"
systemctl restart kaptaan.service
systemctl reload nginx || systemctl restart nginx

sleep 1
if systemctl is-active --quiet kaptaan.service; then
    ok "kaptaan.service is active"
else
    warn "kaptaan.service failed — check: journalctl -u kaptaan -n 50 --no-pager"
fi

PUB_IP=$(curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null || echo "your-server-ip")

cat <<EOF

\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
\033[1;32m  kaptaan is up!\033[0m
\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
   open       http://$PUB_IP/
   login      kaptaan / kaptaan
   then       Settings → paste Daytona / LLM / Firecrawl keys

   logs       sudo journalctl -u kaptaan -f
   reinstall  cd $APP_DIR && sudo ./install.sh
   db file    $DB_DIR/kaptaan.db   (NEVER deleted by re-runs)
EOF
