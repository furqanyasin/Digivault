# Deploy to VPS — digivault.digilatics.co

**IP:** 187.127.253.124  
**SSH:** `ssh root@187.127.253.124`  
**CloudPanel:** `https://187.127.253.124:8443`  
**Domain:** digivault.digilatics.co

CloudPanel manages Nginx and SSL — don't touch those manually.

---

## 1. Add the site in CloudPanel

1. Open `https://187.127.253.124:8443` → login as `admin`
2. **Sites → Add Site → Node.js**
3. Fill in:
   - **Domain name:** `digivault.digilatics.co`
   - **Node.js version:** 20
   - **App port:** `3006`
   - **Site user:** `digilatics-digivault`
   - **Site user password:** iwb74AWM79xJ1Fw4BS8K
4. Click **Create**

CloudPanel creates the system user, home directory `/home/digilatics-digivault`, and Nginx config automatically.

---

## 2. Issue SSL certificate

In CloudPanel → Sites → `digivault.digilatics.co` → **SSL/TLS** → **Actions → New Let's Encrypt Certificate**

> DNS must point `digivault.digilatics.co` → `187.127.253.124` before this works.

---

## 3. SSH in as root and install server dependencies

```bash
ssh root@187.127.253.124
```

**Check what's already running so we don't break other sites:**
```bash
systemctl is-active postgresql redis-server nginx
systemctl is-active postgresql redis-server nginx
# note which ones say "active" — skip installing those below
```

```bash
# Python 3.11 (safe — won't affect other sites)
apt update && apt install -y python3.12 python3.12-venv python3.12-dev \
  python3-pip build-essential libpq-dev git
```

```bash
# PM2 — install globally if not already there
pm2 --version 2>/dev/null || npm install -g pm2
```

```bash
# PostgreSQL — install only if not already active
# (WordPress uses MySQL so this is almost certainly safe)
apt install -y postgresql
systemctl enable postgresql
systemctl start postgresql
```

```bash
# Redis — install if not already active
apt install -y redis-server

# Check current bind setting before changing it
grep "^bind" /etc/redis/redis.conf
# If it already shows "bind 127.0.0.1" → skip the sed line below
# If it shows "bind 0.0.0.0" or is missing → run it:
sed -i 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf

systemctl enable redis-server
systemctl restart redis-server
```

> **Other sites are not affected.** CloudPanel gives each site its own Nginx vhost file.
> We only edit the vhost for `digivault.digilatics.co` in step 11.

---

## 4. Create the database

```bash
sudo -u postgres psql -c "CREATE ROLE digivault WITH LOGIN PASSWORD 'PICK_A_PASSWORD';"
sudo -u postgres createdb -O digivault digivault
```

Save that password — goes into `.env` next.

---

## 5. Clone repo and install Python packages

```bash
su - digilatics-digivault
cd /home/digilatics-digivault

git clone https://github.com/furqanyasin/ScriptSentry.git scdb
cd scdb

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements/base.txt
```

---

## 6. Create `.env`

```bash
# Generate the two keys first:
source /home/digilatics-digivault/scdb/.venv/bin/activate
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```bash
nano /home/digilatics-digivault/scdb/.env
```

```env
DJANGO_SECRET_KEY=<paste key from above>
DEBUG=False
ALLOWED_HOSTS=digivault.digilatics.co,localhost,127.0.0.1

DATABASE_URL=postgres://digivault:PICK_A_PASSWORD@localhost:5432/digivault

REDIS_URL=redis://localhost:6379/0

VAULT_ENCRYPTION_KEY=<paste key from above>

EMAIL_URL=console://

JWT_ACCESS_TOKEN_LIFETIME_MINUTES=15
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

CORS_ALLOWED_ORIGINS=https://digivault.digilatics.co

PAGESPEED_API_KEY=AIzaSyAYrC4gwLsuuZKwLoWmoDvjIM9RtktLv7A

SENTRY_DSN=
```

```bash
chmod 600 /home/digilatics-digivault/scdb/.env
```

---

## 7. Migrate + collectstatic + create admin user

```bash
cd /home/digilatics-digivault/scdb
source .venv/bin/activate

DJANGO_SETTINGS_MODULE=config.settings.production python manage.py migrate

DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput

DJANGO_SETTINGS_MODULE=config.settings.production python manage.py shell -c "
from apps.accounts.models import User, Team, TeamMembership
u = User.objects.create_superuser(email='admin@digilatics.com', password='PICK_ADMIN_PASSWORD')
t = Team.objects.create(name='Digilatics', slug='digilatics', owner=u)
TeamMembership.objects.create(user=u, team=t, role='owner')
u.active_team = t; u.save()
print('Done:', u.email)
"
```

---

## 8. systemd — Daphne (Django, private on 127.0.0.1:8000)

```bash
# Back as root:
exit

tee /etc/systemd/system/daphne.service <<'EOF'
[Unit]
Description=Digivault Django
After=network.target postgresql.service redis-server.service

[Service]
User=digilatics-digivault
WorkingDirectory=/home/digilatics-digivault/scdb
EnvironmentFile=/home/digilatics-digivault/scdb/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.production
ExecStart=/home/digilatics-digivault/scdb/.venv/bin/daphne \
    -b 127.0.0.1 -p 8000 --proxy-headers config.asgi:application
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable daphne
systemctl start daphne
systemctl status daphne
```

Check it's private: `ss -tlnp | grep 8000` must show `127.0.0.1:8000` — not `0.0.0.0`.

---

## 9. systemd — Celery worker + beat

```bash
tee /etc/systemd/system/celery.service <<'EOF'
[Unit]
Description=Digivault Celery Worker
After=redis-server.service

[Service]
User=digilatics-digivault
WorkingDirectory=/home/digilatics-digivault/scdb
EnvironmentFile=/home/digilatics-digivault/scdb/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.production
ExecStart=/home/digilatics-digivault/scdb/.venv/bin/celery \
    -A config worker -l info --concurrency=2
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

tee /etc/systemd/system/celerybeat.service <<'EOF'
[Unit]
Description=Digivault Celery Beat
After=redis-server.service

[Service]
User=digilatics-digivault
WorkingDirectory=/home/digilatics-digivault/scdb
EnvironmentFile=/home/digilatics-digivault/scdb/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.production
ExecStart=/home/digilatics-digivault/scdb/.venv/bin/celery \
    -A config beat -l info \
    -s /home/digilatics-digivault/scdb/celerybeat-schedule
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable celery celerybeat
systemctl start celery celerybeat
```

---

## 10. Build Next.js + start with PM2

```bash
su - digilatics-digivault
cd /home/digilatics-digivault/scdb/frontend

cat > .env.production <<'EOF'
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SITE_URL=https://digivault.digilatics.co
EOF

npm ci
npm run build

pm2 start npm --name digivault -- start -- --port 3006
pm2 save
```

```bash
# Back as root — create a PM2 startup service for this user only
# This creates /etc/systemd/system/pm2-digilatics-digivault.service
# It does NOT affect PM2 for any other user on the server
exit
env PATH=$PATH:/usr/bin pm2 startup systemd -u digilatics-digivault \
  --hp /home/digilatics-digivault
# Copy-paste and run the sudo command it prints
```

---

## 11. Edit Nginx vhost in CloudPanel

CloudPanel created an Nginx config for port 3006. We need to add `/ws/` and `/api/ingest/` to also proxy to port 8000.

1. CloudPanel → Sites → `digivault.digilatics.co` → **Vhost**
2. Find the `location /` block and add these **above it**:

```nginx
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400s;
}

location /api/ingest/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /api/extension/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /api/v1/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /static/ {
    alias /home/digilatics-digivault/scdb/staticfiles/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

3. Click **Save** — CloudPanel reloads Nginx automatically.

---

## 12. Verify everything works

```bash
# All services up?
systemctl status daphne celery celerybeat
su - digilatics-digivault -c "pm2 status"

# Django port closed to internet (run from your LOCAL machine):
curl --connect-timeout 3 http://187.127.253.124:8000/
# Expected: connection refused ✓

# Site is live?
curl -I https://digivault.digilatics.co
# Expected: HTTP/2 200 ✓
```

Open https://digivault.digilatics.co → login as `admin@digilatics.com`

---

## Future deploys

```bash
su - digilatics-digivault
cd /home/digilatics-digivault/scdb

git pull
source .venv/bin/activate
DJANGO_SETTINGS_MODULE=config.settings.production python manage.py migrate --noinput
DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput -v 0

exit
systemctl restart daphne celery celerybeat

su - digilatics-digivault
cd /home/digilatics-digivault/scdb/frontend
npm ci && npm run build && pm2 restart digivault
```
