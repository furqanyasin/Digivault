# Deploy to VPS — stacksmonitor.com

**IP:** `<SERVER_IP>`  
**SSH:** `ssh root@<SERVER_IP>`  
**CloudPanel:** `https://<SERVER_IP>:8443`  
**Domain:** stacksmonitor.com

CloudPanel manages Nginx and SSL — don't touch those manually.

---

## 1. Add the site in CloudPanel

1. Open `https://<SERVER_IP>:8443` → login as `admin`
2. **Sites → Add Site → Node.js**
3. Fill in:
   - **Domain name:** `stacksmonitor.com`
   - **Node.js version:** 20
   - **App port:** `3006`
   - **Site user:** `stacksmonitor`
   - **Site user password:** generate a strong one and keep it in your password manager
4. Click **Create**

CloudPanel creates the system user, home directory `/home/stacksmonitor`, and Nginx config automatically.

---

## 2. Issue SSL certificate

In CloudPanel → Sites → `stacksmonitor.com` → **SSL/TLS** → **Actions → New Let's Encrypt Certificate**

> DNS must point `stacksmonitor.com` → `<SERVER_IP>` before this works.

---

## 3. SSH in as root and install server dependencies

```bash
ssh root@<SERVER_IP>
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
> We only edit the vhost for `stacksmonitor.com` in step 11.

---

## 4. Create the database

```bash
sudo -u postgres psql -c "CREATE ROLE stacksmonitor WITH LOGIN PASSWORD 'PICK_A_PASSWORD';"
sudo -u postgres createdb -O stacksmonitor stacksmonitor
```

Save that password — goes into `.env` next.

---

## 4b. Deploy key (server -> GitHub)

The repo is private, so the server needs its own read-only SSH key.

**The key belongs to the user that runs the deploy, which is `root`** — `.git`
and `.env.production` are root-owned, and `./deploy.sh` does the `git pull`.
Putting it in the site user's home looks right and fails: `su` is blocked for
CloudPanel site users, and a pull as `stacksmonitor` dies on "dubious
ownership" before it ever reaches the network.

A deploy key is scoped to one repository and **cannot be reused on a second repo
anywhere on GitHub** — if this server already carried a key for a previous
account's repo, generate a fresh one rather than re-adding the same public key.

As root:

```bash
mkdir -p /root/.ssh && chmod 700 /root/.ssh

# 1. Generate the keypair (no passphrase — deploy.sh runs unattended)
ssh-keygen -t ed25519 -C "stacksmonitor-deploy@cloudpanel" -f /root/.ssh/stacksmonitor_deploy -N ""
chmod 600 /root/.ssh/stacksmonitor_deploy

# 2. Print the PUBLIC half — one line, starts `ssh-ed25519`
cat /root/.ssh/stacksmonitor_deploy.pub
```

In GitHub: **furqanyasin/stacks-monitor -> Settings -> Deploy keys -> Add deploy
key**. Title it `CloudPanel VPS`, paste that single line, and leave **Allow write
access unchecked** — the deploy only ever pulls. GitHub rejects anything else
with "key is invalid": the randomart block, the private key, or a paste that
wrapped across lines.

```bash
# 3. Route this repo to that key via a HOST ALIAS — not `Host github.com`.
#    This server deploys several repos, each with its own deploy key, and
#    /root/.ssh/config may already carry a `Host github.com` block. ssh takes
#    the FIRST match for each keyword, so appending a second `Host github.com`
#    block is silently ignored and the pull authenticates as whichever repo
#    owns the first one — which reports "Repository not found" while GitHub's
#    deploy key page still reads "Never used".
grep -A4 'Host github-stacksmonitor' /root/.ssh/config   # confirm it exists first

# Only if it is missing, append it:
cat >> /root/.ssh/config <<'EOF'

Host github-stacksmonitor
    HostName github.com
    User git
    IdentityFile /root/.ssh/stacksmonitor_deploy
    IdentitiesOnly yes
EOF
chmod 600 /root/.ssh/config

# 4. Verify against the ALIAS. The greeting must name this repo:
#    "Hi furqanyasin/stacks-monitor! You've successfully authenticated..."
#    A different repo name means ssh matched another key — fix the config,
#    do not proceed to the pull.
ssh -T git@github-stacksmonitor
```

`IdentitiesOnly yes` matters: without it ssh offers every key it holds and GitHub
authenticates as whichever matches first.

**On a server already cloned over HTTPS** (or from a previous account), repoint
the existing checkout rather than re-cloning:

```bash
cd /home/stacksmonitor/app
git remote set-url origin git@github-stacksmonitor:furqanyasin/stacks-monitor.git
git remote -v          # both lines: git@github-stacksmonitor:furqanyasin/stacks-monitor.git
git pull origin main
```

---

## 5. Clone repo and install Python packages

```bash
su - stacksmonitor
cd /home/stacksmonitor

# Requires the repo deploy key to be installed first (see section 4b above).
git clone git@github-stacksmonitor:furqanyasin/stacks-monitor.git app
cd app

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements/base.txt
```

---

## 6. Create `.env`

```bash
# Generate the two keys first:
source /home/stacksmonitor/app/.venv/bin/activate
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```bash
nano /home/stacksmonitor/app/.env
```

```env
DJANGO_SECRET_KEY=<paste key from above>
DEBUG=False
ALLOWED_HOSTS=stacksmonitor.com,localhost,127.0.0.1

DATABASE_URL=postgres://stacksmonitor:PICK_A_PASSWORD@localhost:5432/stacksmonitor

REDIS_URL=redis://localhost:6379/0

VAULT_ENCRYPTION_KEY=<paste key from above>

EMAIL_URL=console://

JWT_ACCESS_TOKEN_LIFETIME_MINUTES=15
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

CORS_ALLOWED_ORIGINS=https://stacksmonitor.com

PAGESPEED_API_KEY=<your Google PageSpeed API key>

SENTRY_DSN=
```

```bash
chmod 600 /home/stacksmonitor/app/.env
```

---

## 7. Migrate + collectstatic + create admin user

```bash
cd /home/stacksmonitor/app
source .venv/bin/activate

DJANGO_SETTINGS_MODULE=config.settings.production python manage.py migrate

DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput

DJANGO_SETTINGS_MODULE=config.settings.production python manage.py shell -c "
from apps.accounts.models import User, Team, TeamMembership
u = User.objects.create_superuser(email='admin@stacksmonitor.com', password='PICK_ADMIN_PASSWORD')
t = Team.objects.create(name='Stacks Monitor', slug='stacks-monitor', owner=u)
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
Description=Stacks Monitor Django
After=network.target postgresql.service redis-server.service

[Service]
User=stacksmonitor
WorkingDirectory=/home/stacksmonitor/app
EnvironmentFile=/home/stacksmonitor/app/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.production
ExecStart=/home/stacksmonitor/app/.venv/bin/daphne \
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
Description=Stacks Monitor Celery Worker
After=redis-server.service

[Service]
User=stacksmonitor
WorkingDirectory=/home/stacksmonitor/app
EnvironmentFile=/home/stacksmonitor/app/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.production
ExecStart=/home/stacksmonitor/app/.venv/bin/celery \
    -A config worker -l info --concurrency=2
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

tee /etc/systemd/system/celerybeat.service <<'EOF'
[Unit]
Description=Stacks Monitor Celery Beat
After=redis-server.service

[Service]
User=stacksmonitor
WorkingDirectory=/home/stacksmonitor/app
EnvironmentFile=/home/stacksmonitor/app/.env
Environment=DJANGO_SETTINGS_MODULE=config.settings.production
ExecStart=/home/stacksmonitor/app/.venv/bin/celery \
    -A config beat -l info \
    -s /home/stacksmonitor/app/celerybeat-schedule
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
su - stacksmonitor
cd /home/stacksmonitor/app/frontend

cat > .env.production <<'EOF'
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SITE_URL=https://stacksmonitor.com
EOF

npm ci
npm run build

pm2 start npm --name stacksmonitor-frontend -- start -- --port 3006
pm2 save
```

```bash
# Back as root — create a PM2 startup service for this user only
# This creates /etc/systemd/system/pm2-stacksmonitor.service
# It does NOT affect PM2 for any other user on the server
exit
env PATH=$PATH:/usr/bin pm2 startup systemd -u stacksmonitor \
  --hp /home/stacksmonitor
# Copy-paste and run the sudo command it prints
```

---

## 11. Edit Nginx vhost in CloudPanel

CloudPanel created an Nginx config for port 3006. We need to add `/ws/` and `/api/ingest/` to also proxy to port 8000.

1. CloudPanel → Sites → `stacksmonitor.com` → **Vhost**
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
    alias /home/stacksmonitor/app/staticfiles/;
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
su - stacksmonitor -c "pm2 status"

# Django port closed to internet (run from your LOCAL machine):
curl --connect-timeout 3 http://<SERVER_IP>:8000/
# Expected: connection refused ✓

# Site is live?
curl -I https://stacksmonitor.com
# Expected: HTTP/2 200 ✓
```

Open https://stacksmonitor.com → login as `admin@stacksmonitor.com`

---

## Future deploys

```bash
su - stacksmonitor
cd /home/stacksmonitor/app

git pull
source .venv/bin/activate
DJANGO_SETTINGS_MODULE=config.settings.production python manage.py migrate --noinput
DJANGO_SETTINGS_MODULE=config.settings.production python manage.py collectstatic --noinput -v 0

exit
systemctl restart daphne celery celerybeat

su - stacksmonitor
cd /home/stacksmonitor/app/frontend
npm ci && npm run build && pm2 restart stacksmonitor-frontend
```
