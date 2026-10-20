# VPS Deployment — Digivault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Digivault (Django + Next.js) to a Hostinger Ubuntu VPS with the Django REST API fully private — only reachable internally from Next.js, never directly from the internet.

**Architecture:** Nginx sits on ports 80/443 and proxies all traffic to Next.js (localhost:3000). Next.js server-side code calls Django on localhost:8000 directly. Django/Daphne binds to 127.0.0.1 only — port 8000 is never opened in the firewall. Three Nginx exceptions exist for endpoints that must be publicly reachable by third-party clients: `/ws/` (WebSocket alerts), `/api/ingest/` (JS snippet POSTs), and `/api/extension/` (browser extension lookups).

**Tech Stack:** Ubuntu 22.04 LTS, Python 3.11, Django 5.1 / Daphne 4.1, Node.js 20 LTS, Next.js 16, PostgreSQL 16, Redis 7, Nginx, Certbot, systemd, PM2

---

## Traffic Map

```
Internet
  │
  ▼
Nginx :443
  ├── /ws/*              → 127.0.0.1:8000  (WebSocket, JWT-authenticated)
  ├── /api/ingest/       → 127.0.0.1:8000  (public — JS snippet POSTs here)
  ├── /api/extension/    → 127.0.0.1:8000  (public — browser extension)
  └── everything else    → 127.0.0.1:3000  (Next.js)
                                │
                                └── server-side fetches → 127.0.0.1:8000
                                    (all /api/v1/* — never exposed via Nginx)
```

---

## File Structure

Files **created on the VPS** during this plan:

| Path | Purpose |
|------|---------|
| `/etc/nginx/sites-available/digivault` | Nginx vhost — reverse proxy config |
| `/etc/systemd/system/daphne.service` | Django ASGI server — binds 127.0.0.1:8000 |
| `/etc/systemd/system/celery.service` | Celery worker |
| `/etc/systemd/system/celerybeat.service` | Celery beat (periodic tasks) |
| `/home/deploy/scdb/.env` | Production environment variables |
| `/home/deploy/scdb/frontend/.env.production` | Next.js env (API base URL) |

Files **modified in the repo** before deploying:

| Path | Change |
|------|--------|
| `config/settings/production.py` | Add `SECURE_PROXY_SSL_HEADER`, `ALLOWED_HOSTS` from env |
| `Dockerfile` / `docker-compose.yml` | No change — not used on VPS |

---

## Pre-flight Checklist (do before starting)

- [ ] Know your VPS IP address (e.g. `123.45.67.89`)
- [ ] Have your domain pointed at the VPS — A record `yourdomain.com → <VPS IP>` and `www.yourdomain.com → <VPS IP>` (DNS needs to propagate before Certbot works)
- [ ] Have SSH root access to the VPS
- [ ] Decide your deploy username (plan uses `deploy`)
- [ ] Decide your domain (plan uses `yourdomain.com` — replace everywhere)

---

## Task 1: VPS Initial Setup

**Goal:** Non-root deploy user, SSH key auth only, UFW firewall.

**Run on your local machine first** — then SSH as root.

- [ ] **Step 1: Copy your SSH public key to the VPS**

  On your local machine:
  ```bash
  ssh-copy-id root@<VPS_IP>
  # or if using a key file:
  ssh-copy-id -i ~/.ssh/id_rsa.pub root@<VPS_IP>
  ```

- [ ] **Step 2: SSH into the VPS as root**
  ```bash
  ssh root@<VPS_IP>
  ```

- [ ] **Step 3: Create a non-root deploy user**
  ```bash
  adduser deploy
  usermod -aG sudo deploy
  ```

- [ ] **Step 4: Copy SSH key to deploy user**
  ```bash
  mkdir -p /home/deploy/.ssh
  cp /root/.ssh/authorized_keys /home/deploy/.ssh/
  chown -R deploy:deploy /home/deploy/.ssh
  chmod 700 /home/deploy/.ssh
  chmod 600 /home/deploy/.ssh/authorized_keys
  ```

- [ ] **Step 5: Disable root SSH login and password auth**

  Edit `/etc/ssh/sshd_config`:
  ```
  PermitRootLogin no
  PasswordAuthentication no
  PubkeyAuthentication yes
  ```

  Then reload:
  ```bash
  systemctl reload sshd
  ```

- [ ] **Step 6: Test deploy user login before closing root session**

  Open a new terminal:
  ```bash
  ssh deploy@<VPS_IP>
  sudo whoami   # should print: root
  ```

- [ ] **Step 7: Configure UFW — only SSH, HTTP, HTTPS**
  ```bash
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw allow OpenSSH
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw enable
  sudo ufw status
  ```

  Expected output includes:
  ```
  22/tcp   ALLOW IN
  80/tcp   ALLOW IN
  443/tcp  ALLOW IN
  ```

  Port 8000 is NOT open. Django is private.

---

## Task 2: Install Server Dependencies

**Run as `deploy` user (all subsequent tasks use `deploy`).**

- [ ] **Step 1: Update system packages**
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```

- [ ] **Step 2: Install Python 3.11, pip, venv, build tools**
  ```bash
  sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip \
    build-essential libpq-dev curl git
  ```

- [ ] **Step 3: Install Node.js 20 via NodeSource**
  ```bash
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt install -y nodejs
  node --version   # should print v20.x.x
  npm --version
  ```

- [ ] **Step 4: Install PM2 globally (Next.js process manager)**
  ```bash
  sudo npm install -g pm2
  pm2 --version
  ```

- [ ] **Step 5: Install Nginx and Certbot**
  ```bash
  sudo apt install -y nginx certbot python3-certbot-nginx
  sudo systemctl enable nginx
  sudo systemctl start nginx
  ```

  Verify: `curl http://localhost` should return the Nginx welcome page.

- [ ] **Step 6: Install PostgreSQL 16**
  ```bash
  sudo apt install -y postgresql-16 postgresql-client-16
  sudo systemctl enable postgresql
  sudo systemctl start postgresql
  ```

- [ ] **Step 7: Install Redis 7**
  ```bash
  sudo apt install -y redis-server
  sudo systemctl enable redis-server
  ```

---

## Task 3: PostgreSQL — Create Database and User

- [ ] **Step 1: Create the database user and database**
  ```bash
  sudo -u postgres psql <<'SQL'
  CREATE ROLE digivault WITH LOGIN PASSWORD 'CHOOSE_A_STRONG_PASSWORD_HERE';
  CREATE DATABASE digivault OWNER digivault;
  GRANT ALL PRIVILEGES ON DATABASE digivault TO digivault;
  SQL
  ```

  Replace `CHOOSE_A_STRONG_PASSWORD_HERE` with a real password — save it, you'll need it in `.env`.

- [ ] **Step 2: Verify PostgreSQL only listens on localhost**
  ```bash
  sudo -u postgres psql -c "SHOW listen_addresses;"
  ```

  Expected: `localhost` — PostgreSQL is not exposed to the internet by default. Good.

---

## Task 4: Redis — Lock Down to Localhost

- [ ] **Step 1: Verify Redis bind config**
  ```bash
  grep "^bind" /etc/redis/redis.conf
  ```

  Should show `bind 127.0.0.1 -::1`. If it shows `0.0.0.0`, fix it:
  ```bash
  sudo sed -i 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf
  sudo systemctl restart redis-server
  ```

- [ ] **Step 2: Confirm Redis is only on localhost**
  ```bash
  redis-cli ping   # PONG
  ```

---

## Task 5: Clone Repo and Install Python Dependencies

- [ ] **Step 1: Clone the repository**
  ```bash
  cd /home/deploy
  git clone https://github.com/YOUR_ORG/scdb.git scdb
  cd scdb
  ```

  If repo is private, set up a deploy key:
  ```bash
  ssh-keygen -t ed25519 -C "deploy@vps" -f ~/.ssh/deploy_key -N ""
  cat ~/.ssh/deploy_key.pub
  # Add this public key to GitHub repo → Settings → Deploy keys
  eval "$(ssh-agent -s)"
  ssh-add ~/.ssh/deploy_key
  GIT_SSH_COMMAND="ssh -i ~/.ssh/deploy_key" git clone git@github.com:YOUR_ORG/scdb.git scdb
  ```

- [ ] **Step 2: Create Python virtualenv and install dependencies**
  ```bash
  cd /home/deploy/scdb
  python3.11 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements/base.txt
  ```

  Verify:
  ```bash
  python -c "import django; print(django.__version__)"   # 5.1.4
  ```

---

## Task 6: Create Production `.env` File

- [ ] **Step 1: Create `/home/deploy/scdb/.env`**

  ```bash
  cat > /home/deploy/scdb/.env <<'ENV'
  DJANGO_SECRET_KEY=GENERATE_50_CHAR_RANDOM_STRING
  DEBUG=False
  ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,localhost,127.0.0.1

  # Database — use the password from Task 3
  DATABASE_URL=postgres://digivault:STRONG_PASSWORD@localhost:5432/digivault

  # Redis
  REDIS_URL=redis://localhost:6379/0

  # Vault key — generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  VAULT_ENCRYPTION_KEY=GENERATE_FERNET_KEY

  # Email (use SMTP in production; console for initial setup)
  EMAIL_URL=console://

  # JWT
  JWT_ACCESS_TOKEN_LIFETIME_MINUTES=15
  JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

  # CORS — only your domain
  CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

  # PageSpeed
  PAGESPEED_API_KEY=your_pagespeed_key

  # Sentry (optional)
  SENTRY_DSN=
  ENV
  ```

  Replace every UPPERCASE placeholder before saving.

- [ ] **Step 2: Generate DJANGO_SECRET_KEY**
  ```bash
  source .venv/bin/activate
  python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
  ```

  Paste the output into `.env` as `DJANGO_SECRET_KEY=`.

- [ ] **Step 3: Generate VAULT_ENCRYPTION_KEY**
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  Paste the output into `.env` as `VAULT_ENCRYPTION_KEY=`.

- [ ] **Step 4: Secure the .env file (readable only by deploy user)**
  ```bash
  chmod 600 /home/deploy/scdb/.env
  ```

---

## Task 7: Fix Production Django Settings

**Edit `config/settings/production.py` locally, commit, then pull on VPS.**

- [ ] **Step 1: Update `config/settings/production.py`**

  Replace the full file with:
  ```python
  import sentry_sdk
  from sentry_sdk.integrations.django import DjangoIntegration

  from .base import *  # noqa: F401, F403
  from .base import env

  DEBUG = False

  ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

  # Tell Django it's behind an SSL-terminating Nginx proxy
  SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

  # Security headers — Nginx terminates TLS so don't double-redirect
  SECURE_SSL_REDIRECT = False   # Nginx handles HTTP→HTTPS redirect
  SECURE_HSTS_SECONDS = 31_536_000
  SECURE_HSTS_INCLUDE_SUBDOMAINS = True
  SECURE_HSTS_PRELOAD = True
  SECURE_CONTENT_TYPE_NOSNIFF = True
  SESSION_COOKIE_SECURE = True
  CSRF_COOKIE_SECURE = True
  X_FRAME_OPTIONS = "DENY"

  CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")

  # Sentry (optional)
  _sentry_dsn = env("SENTRY_DSN", default="")
  if _sentry_dsn:
      sentry_sdk.init(
          dsn=_sentry_dsn,
          integrations=[DjangoIntegration()],
          traces_sample_rate=0.1,
          send_default_pii=False,
      )
  ```

- [ ] **Step 2: Commit and push**
  ```bash
  git add config/settings/production.py
  git commit -m "fix(prod): proxy SSL header, ALLOWED_HOSTS from env, no double-redirect"
  git push
  ```

- [ ] **Step 3: Pull on the VPS**
  ```bash
  cd /home/deploy/scdb
  git pull
  ```

---

## Task 8: Django — Migrate, Static Files, Superuser

- [ ] **Step 1: Run migrations**
  ```bash
  cd /home/deploy/scdb
  source .venv/bin/activate
  DJANGO_SETTINGS_MODULE=config.settings.production python manage.py migrate
  ```

  Expected: all migrations applied including `scripts.0002_add_review_status`.

- [ ] **Step 2: Collect static files**
  ```bash
  DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput
  ```

  Files land in `staticfiles/`.

- [ ] **Step 3: Create admin superuser**
  ```bash
  DJANGO_SETTINGS_MODULE=config.settings.production python manage.py shell -c "
  from apps.accounts.models import User, Team, TeamMembership
  u = User.objects.create_superuser(email='admin@yourdomain.com', password='CHOOSE_STRONG_PASSWORD')
  t = Team.objects.create(name='My Team', slug='my-team', owner=u)
  TeamMembership.objects.create(user=u, team=t, role='owner')
  u.active_team = t
  u.save()
  print('Created:', u.email)
  "
  ```

  Replace email and password.

- [ ] **Step 4: Smoke-test Django can start**
  ```bash
  DJANGO_SETTINGS_MODULE=config.settings.production \
    .venv/bin/daphne -b 127.0.0.1 -p 8000 config.asgi:application &
  sleep 2
  curl -s http://127.0.0.1:8000/api/v1/auth/token/ -X POST \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@yourdomain.com","password":"WRONG"}' | head -c 200
  # Expected: {"data":null,"errors":[{"code":"authentication_failed",...}],...}
  kill %1
  ```

---

## Task 9: systemd — Daphne Service

**Daphne binds to 127.0.0.1 only. This is the core of API privacy.**

- [ ] **Step 1: Create `/etc/systemd/system/daphne.service`**
  ```bash
  sudo tee /etc/systemd/system/daphne.service <<'UNIT'
  [Unit]
  Description=Digivault Django ASGI (Daphne)
  After=network.target postgresql.service redis-server.service
  Requires=postgresql.service redis-server.service

  [Service]
  User=deploy
  Group=deploy
  WorkingDirectory=/home/deploy/scdb
  EnvironmentFile=/home/deploy/scdb/.env
  Environment=DJANGO_SETTINGS_MODULE=config.settings.production
  ExecStart=/home/deploy/scdb/.venv/bin/daphne \
      -b 127.0.0.1 \
      -p 8000 \
      --proxy-headers \
      config.asgi:application
  Restart=on-failure
  RestartSec=5
  StandardOutput=journal
  StandardError=journal

  [Install]
  WantedBy=multi-user.target
  UNIT
  ```

  Note: `--proxy-headers` tells Daphne to trust `X-Forwarded-For` from Nginx.

- [ ] **Step 2: Enable and start Daphne**
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable daphne
  sudo systemctl start daphne
  sudo systemctl status daphne
  ```

  Expected: `Active: active (running)`.

- [ ] **Step 3: Confirm Daphne is only on localhost**
  ```bash
  ss -tlnp | grep 8000
  ```

  Expected: `127.0.0.1:8000` — NOT `0.0.0.0:8000`. This is the privacy guarantee.

---

## Task 10: systemd — Celery Worker and Beat

- [ ] **Step 1: Create `/etc/systemd/system/celery.service`**
  ```bash
  sudo tee /etc/systemd/system/celery.service <<'UNIT'
  [Unit]
  Description=Digivault Celery Worker
  After=network.target redis-server.service

  [Service]
  User=deploy
  Group=deploy
  WorkingDirectory=/home/deploy/scdb
  EnvironmentFile=/home/deploy/scdb/.env
  Environment=DJANGO_SETTINGS_MODULE=config.settings.production
  ExecStart=/home/deploy/scdb/.venv/bin/celery -A config worker -l info \
      --concurrency=2 --max-tasks-per-child=100
  Restart=on-failure
  RestartSec=10
  StandardOutput=journal
  StandardError=journal

  [Install]
  WantedBy=multi-user.target
  UNIT
  ```

- [ ] **Step 2: Create `/etc/systemd/system/celerybeat.service`**
  ```bash
  sudo tee /etc/systemd/system/celerybeat.service <<'UNIT'
  [Unit]
  Description=Digivault Celery Beat Scheduler
  After=network.target redis-server.service

  [Service]
  User=deploy
  Group=deploy
  WorkingDirectory=/home/deploy/scdb
  EnvironmentFile=/home/deploy/scdb/.env
  Environment=DJANGO_SETTINGS_MODULE=config.settings.production
  ExecStart=/home/deploy/scdb/.venv/bin/celery -A config beat -l info \
      -s /home/deploy/scdb/celerybeat-schedule
  Restart=on-failure
  RestartSec=10
  StandardOutput=journal
  StandardError=journal

  [Install]
  WantedBy=multi-user.target
  UNIT
  ```

- [ ] **Step 3: Enable and start both services**
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable celery celerybeat
  sudo systemctl start celery celerybeat
  sudo systemctl status celery
  sudo systemctl status celerybeat
  ```

  Both should show `Active: active (running)`.

- [ ] **Step 4: Verify Celery Beat fires the monitor task**
  ```bash
  sudo journalctl -u celerybeat -n 30 --no-pager
  ```

  Within 30 seconds you should see: `monitors.run_due_checks`.

---

## Task 11: Next.js — Production Build and PM2

- [ ] **Step 1: Create `/home/deploy/scdb/frontend/.env.production`**
  ```bash
  cat > /home/deploy/scdb/frontend/.env.production <<'ENV'
  # Internal URL — Next.js server-side calls Django on localhost
  NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
  # Public URL — used in meta tags, canonical links
  NEXT_PUBLIC_SITE_URL=https://yourdomain.com
  ENV
  ```

- [ ] **Step 2: Install Node dependencies**
  ```bash
  cd /home/deploy/scdb/frontend
  npm ci --production=false
  ```

- [ ] **Step 3: Build Next.js for production**
  ```bash
  npm run build
  ```

  Expected final lines:
  ```
  ✓ Compiled successfully
  Route (app) ...
  ```

  If TypeScript errors appear, fix them before continuing.

- [ ] **Step 4: Start with PM2**
  ```bash
  pm2 start npm --name digivault-frontend -- start
  pm2 save
  pm2 startup
  ```

  The `pm2 startup` command prints a `sudo env PATH=...` command — **run that command** to make PM2 survive reboots.

- [ ] **Step 5: Verify Next.js is up**
  ```bash
  curl -s http://127.0.0.1:3000 | head -c 200
  # Should return HTML
  pm2 status
  ```

---

## Task 12: Nginx Configuration

**This is where API privacy is enforced at the network level.**

- [ ] **Step 1: Remove default Nginx site**
  ```bash
  sudo rm -f /etc/nginx/sites-enabled/default
  ```

- [ ] **Step 2: Create `/etc/nginx/sites-available/digivault`**
  ```bash
  sudo tee /etc/nginx/sites-available/digivault <<'NGINX'
  # Redirect HTTP → HTTPS
  server {
      listen 80;
      listen [::]:80;
      server_name yourdomain.com www.yourdomain.com;
      return 301 https://$host$request_uri;
  }

  server {
      listen 443 ssl http2;
      listen [::]:443 ssl http2;
      server_name yourdomain.com www.yourdomain.com;

      # SSL — Certbot will fill these in Task 13
      ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
      ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
      include /etc/letsencrypt/options-ssl-nginx.conf;
      ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

      # Security headers
      add_header X-Frame-Options "DENY" always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header Referrer-Policy "strict-origin-when-cross-origin" always;

      # ── WebSocket — proxied directly to Daphne ──────────────────────────
      location /ws/ {
          proxy_pass http://127.0.0.1:8000;
          proxy_http_version 1.1;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection "upgrade";
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
          proxy_read_timeout 86400s;
      }

      # ── Public API endpoints — snippet ingest + browser extension ───────
      # These are called by third-party sites and browser extensions,
      # NOT by the frontend — so they must be reachable via Nginx.
      location /api/ingest/ {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }

      location /api/extension/ {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }

      # ── Everything else → Next.js ────────────────────────────────────────
      # This includes the dashboard, auth UI, and the /api/* proxy routes
      # that Next.js uses to forward to Django internally.
      location / {
          proxy_pass http://127.0.0.1:3000;
          proxy_http_version 1.1;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection "upgrade";
          proxy_cache_bypass $http_upgrade;
      }
  }
  NGINX
  ```

  Replace `yourdomain.com` everywhere in this file.

- [ ] **Step 3: Enable the site**
  ```bash
  sudo ln -s /etc/nginx/sites-available/digivault /etc/nginx/sites-enabled/
  sudo nginx -t
  ```

  Expected: `syntax is ok` and `test is successful`.

---

## Task 13: SSL with Certbot

Nginx must be running and DNS must be pointing at the VPS before this step.

- [ ] **Step 1: Temporarily serve HTTP (comment out the SSL block)**

  Since SSL certs don't exist yet, replace the `scriptsentry` Nginx config with a temporary HTTP-only version for Certbot's HTTP challenge:

  ```bash
  sudo tee /etc/nginx/sites-available/digivault <<'NGINX'
  server {
      listen 80;
      listen [::]:80;
      server_name yourdomain.com www.yourdomain.com;

      location / {
          proxy_pass http://127.0.0.1:3000;
          proxy_set_header Host $host;
      }
  }
  NGINX
  sudo systemctl reload nginx
  ```

- [ ] **Step 2: Obtain SSL certificate**
  ```bash
  sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com \
    --non-interactive --agree-tos -m admin@yourdomain.com
  ```

  Expected: `Successfully deployed certificate`.

- [ ] **Step 3: Restore the full Nginx config**

  Re-run the `sudo tee /etc/nginx/sites-available/digivault` command from Task 12 Step 2 (the full config with SSL, WebSocket, and ingest blocks). Then:

  ```bash
  sudo nginx -t
  sudo systemctl reload nginx
  ```

- [ ] **Step 4: Verify auto-renewal**
  ```bash
  sudo certbot renew --dry-run
  ```

  Expected: `Congratulations, all simulated renewals succeeded`.

---

## Task 14: Final Verification

- [ ] **Step 1: Confirm Django API port is NOT publicly reachable**

  From your local machine:
  ```bash
  curl --connect-timeout 5 http://<VPS_IP>:8000/api/v1/auth/token/ -X POST
  ```

  Expected: connection refused or timeout. **If it connects, check UFW and Daphne bind address.**

- [ ] **Step 2: Confirm login works through Next.js**
  ```bash
  curl -s -X POST https://yourdomain.com/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@yourdomain.com","password":"YOUR_ADMIN_PASSWORD"}'
  ```

  Expected: `{"access":"...","refresh":"..."}` — Next.js proxy route hit Django internally.

- [ ] **Step 3: Confirm ingest endpoint is reachable**
  ```bash
  curl -s -X POST https://yourdomain.com/api/ingest/ \
    -H "Content-Type: application/json" \
    -d '{"site_id":"nonexistent","page_url":"https://test.com","scripts":[]}'
  ```

  Expected: `404` — correct, site_id not found. Proves endpoint is reachable.

- [ ] **Step 4: Confirm WebSocket proxying works**
  ```bash
  curl -s -I -H "Upgrade: websocket" -H "Connection: Upgrade" \
    https://yourdomain.com/ws/alerts/
  ```

  Expected: `101 Switching Protocols` or `403` (auth required) — both prove Nginx is routing to Daphne.

- [ ] **Step 5: Check all services are healthy**
  ```bash
  sudo systemctl status daphne celery celerybeat
  pm2 status
  sudo nginx -t
  ```

  All should show `active (running)`.

- [ ] **Step 6: Open the app in a browser**

  Visit `https://yourdomain.com` — login, add a website, visit the dashboard.

---

## Task 15: Deployment Workflow (Future Updates)

Create a one-command deploy script for future updates.

- [ ] **Step 1: Create `/home/deploy/deploy.sh`**
  ```bash
  cat > /home/deploy/deploy.sh <<'DEPLOY'
  #!/bin/bash
  set -e
  cd /home/deploy/scdb

  echo "==> Pulling latest code..."
  git pull

  echo "==> Installing Python dependencies..."
  source .venv/bin/activate
  pip install -r requirements/base.txt -q

  echo "==> Running migrations..."
  DJANGO_SETTINGS_MODULE=config.settings.production python manage.py migrate --noinput

  echo "==> Collecting static files..."
  DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput -v 0

  echo "==> Restarting Django..."
  sudo systemctl restart daphne celery celerybeat

  echo "==> Rebuilding Next.js..."
  cd frontend
  npm ci --production=false
  npm run build
  pm2 restart digivault-frontend

  echo "==> Done. Checking status..."
  sudo systemctl status daphne --no-pager -l | tail -5
  pm2 status
  DEPLOY

  chmod +x /home/deploy/deploy.sh
  ```

- [ ] **Step 2: Allow deploy user to restart services without a password**
  ```bash
  sudo tee /etc/sudoers.d/deploy-services <<'SUDO'
  deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart daphne, \
                              /bin/systemctl restart celery, \
                              /bin/systemctl restart celerybeat, \
                              /bin/systemctl status daphne, \
                              /bin/systemctl status celery, \
                              /bin/systemctl status celerybeat
  SUDO
  ```

- [ ] **Step 3: Test the deploy script**
  ```bash
  /home/deploy/deploy.sh
  ```

---

## Security Summary

| Layer | What's protected | How |
|-------|-----------------|-----|
| Firewall | Port 8000 (Django) | UFW only allows 22, 80, 443 |
| Process bind | Port 8000 | Daphne binds to `127.0.0.1` only |
| Nginx routing | `/api/v1/*` not proxied | Only `/ws/`, `/api/ingest/`, `/api/extension/` go to Daphne |
| Django auth | All `/api/v1/` endpoints | JWT `IsAuthenticated` permission class |
| Database | PostgreSQL | Listens on localhost only, password-protected |
| Redis | Cache/broker | Binds to `127.0.0.1` only |
| TLS | All traffic | Let's Encrypt, auto-renewed |
| SSH | Server access | Key-only, root login disabled |
