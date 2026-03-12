#!/bin/bash
# =============================================================
#  ChatBot V11 — Step 2: Full server setup
#  Run this ON the Ubuntu server as ubuntu user:
#    bash ~/chatbot/2_server_setup.sh
# =============================================================

set -e  # Exit on any error

APP_DIR="/home/ubuntu/chatbot"
APP_USER="ubuntu"
DOMAIN=""   # <-- SET THIS to your domain, e.g. bot.yourcompany.com
            #     Leave blank to skip SSL (HTTP only, not suitable for Meta webhooks)

# ─────────────────────────────────────────────
# 1. System packages
# ─────────────────────────────────────────────
echo ""
echo "=== [1/8] Installing system packages ==="
sudo apt update -y
sudo apt install -y \
    python3.12 python3.12-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    supervisor ufw git curl

# ─────────────────────────────────────────────
# 2. Node.js 20 (for building React frontend)
# ─────────────────────────────────────────────
echo ""
echo "=== [2/8] Installing Node.js 20 ==="
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt install -y nodejs
fi
node -v && npm -v

# ─────────────────────────────────────────────
# 3. Python virtual env + pip install
# ─────────────────────────────────────────────
echo ""
echo "=== [3/8] Setting up Python venv ==="
cd "$APP_DIR"
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
echo "Python dependencies installed."

# ─────────────────────────────────────────────
# 4. Build React frontend (if dist not present)
# ─────────────────────────────────────────────
echo ""
echo "=== [4/8] Building React frontend ==="
cd "$APP_DIR/frontend-web"
npm install
npm run build
echo "Frontend built → $APP_DIR/frontend-web/dist"
cd "$APP_DIR"

# ─────────────────────────────────────────────
# 5. .env permissions
# ─────────────────────────────────────────────
echo ""
echo "=== [5/8] Securing .env ==="
chmod 600 "$APP_DIR/.env"
echo ".env permissions set to 600."

# ─────────────────────────────────────────────
# 6. Supervisor (keep uvicorn alive)
# ─────────────────────────────────────────────
echo ""
echo "=== [6/8] Configuring Supervisor ==="
sudo mkdir -p /var/log/chatbot

sudo tee /etc/supervisor/conf.d/chatbot.conf > /dev/null <<EOF
[program:chatbot]
command=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
directory=$APP_DIR
user=$APP_USER
autostart=true
autorestart=true
stdout_logfile=/var/log/chatbot/out.log
stderr_logfile=/var/log/chatbot/err.log
environment=HOME="/home/ubuntu",USER="ubuntu"
EOF

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start chatbot || sudo supervisorctl restart chatbot
echo "Supervisor configured. App is running."

# ─────────────────────────────────────────────
# 7. Nginx reverse proxy
# ─────────────────────────────────────────────
echo ""
echo "=== [7/8] Configuring Nginx ==="

if [ -z "$DOMAIN" ]; then
    # No domain — serve on IP with HTTP only
    SERVER_NAME="_"
else
    SERVER_NAME="$DOMAIN"
fi

sudo tee /etc/nginx/sites-available/chatbot > /dev/null <<EOF
server {
    listen 80;
    server_name $SERVER_NAME;

    # Serve React static files
    root $APP_DIR/frontend-web/dist;
    index index.html;

    # React SPA: all non-API routes go to index.html
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Proxy API calls to FastAPI backend
    location ~ ^/(buyer|channels|whatsapp|health|docs|openapi) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }

    client_max_body_size 1M;
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/chatbot /etc/nginx/sites-enabled/chatbot
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
echo "Nginx configured."

# ─────────────────────────────────────────────
# 8. Firewall
# ─────────────────────────────────────────────
echo ""
echo "=== [8/8] Configuring UFW firewall ==="
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
echo "Firewall enabled."

# ─────────────────────────────────────────────
# SSL (only if DOMAIN is set)
# ─────────────────────────────────────────────
if [ -n "$DOMAIN" ]; then
    echo ""
    echo "=== SSL: Obtaining Let's Encrypt certificate for $DOMAIN ==="
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@"$DOMAIN"
    echo "SSL certificate installed."
fi

# ─────────────────────────────────────────────
# Done!
# ─────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║           SETUP COMPLETE ✓                       ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Backend:   http://127.0.0.1:8000 (internal)     ║"
if [ -z "$DOMAIN" ]; then
echo "║  Frontend:  http://13.250.220.109                 ║"
echo "║  WhatsApp webhook: http://13.250.220.109/channels/whatsapp/webhook"
else
echo "║  Frontend:  https://$DOMAIN                      ║"
echo "║  WhatsApp webhook: https://$DOMAIN/channels/whatsapp/webhook"
fi
echo "╠══════════════════════════════════════════════════╣"
echo "║  Logs:  sudo tail -f /var/log/chatbot/out.log    ║"
echo "║  Status: sudo supervisorctl status chatbot       ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "⚠  Set DOMAIN= at the top of this script and re-run"
echo "   to add SSL (required for Meta WhatsApp webhooks)."
