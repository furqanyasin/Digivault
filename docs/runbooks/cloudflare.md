# Runbook — Cloudflare in front of Digivault (optional)

**Why:** every visitor to every client site fetches `/api/s.js` from this one
VPS whenever their 5-minute browser cache expires, so snippet traffic grows
with client pageviews. Cloudflare's free plan can serve it from the edge
instead. Origin load for the snippet drops to near zero and visitors get it
faster.

**What doesn't change:** uptime checks, scans and PageSpeed calls go *out*
from this server's own IP, not through Cloudflare. Client firewall allowlists
(SiteGround tickets, Cloudflare rules on client sites) stay as they are.

## Order matters

Do these steps in order. If step 1 is skipped, every user appears to Digivault
as a Cloudflare address. The per-IP limits are shared across everyone behind
the same address, so the extension sign-in limit (20/minute) would be shared
by the whole team, and the audit log would record Cloudflare's IPs instead of
people's.

### 1. Teach nginx Cloudflare's addresses (before proxying anything)

CloudPanel → Sites → `digivault.digilatics.co` → **Vhost**. Inside the
`server { }` block, add:

```nginx
# Cloudflare edge ranges: https://www.cloudflare.com/ips/ (re-check yearly)
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;
real_ip_header CF-Connecting-IP;
```

Compare the list against https://www.cloudflare.com/ips/ when you paste it.

nginx then sets `$remote_addr` to the visitor, so the `X-Forwarded-For`
headers in the `/api` blocks carry the visitor's address. uvicorn and Django
need no change: they already take the address nginx appended
(`apps/common/client_ip.py`). This block does nothing until traffic arrives
from Cloudflare, so it is safe to add first.

### 2. Move DNS to Cloudflare

Add the site in Cloudflare and copy the existing DNS records. Turn the proxy
(orange cloud) **on for `digivault.digilatics.co` only**.

- SSL/TLS mode: **Full (strict)**. The origin already has a valid certificate.
- Network → WebSockets: **on**. The dashboard's live alerts use `/ws/`.

### 3. Cache the snippet and nothing else

Caching → Cache Rules → create a rule:

- **When:** URI Path equals `/api/s.js`
- **Then:** Eligible for cache, Edge TTL = *use origin cache-control header*
  (Django sends `max-age=300`)

Create a second rule below it:

- **When:** Hostname equals `digivault.digilatics.co`
- **Then:** Bypass cache

The API, the ingest endpoints and the dashboard must never be cached.

## Verify

```bash
# Served by the edge (repeat once; the second answer should say HIT):
curl -sI https://digivault.digilatics.co/api/s.js | grep -i cf-cache-status

# The API is not cached:
curl -sI https://digivault.digilatics.co/api/ready/ | grep -i cf-cache-status   # DYNAMIC or BYPASS
```

Then sign in to the dashboard and open the Activity Log. Your sign-in row must
show **your own public IP**, not a `104.x` / `172.6x` / `162.15x` Cloudflare
address. If it shows a Cloudflare address, step 1 is missing or incomplete.
Turn the orange cloud off until it is fixed.

## Rollback

Turn the orange cloud off for `digivault.digilatics.co`. Traffic goes straight
to the VPS again, and the `set_real_ip_from` block goes back to doing nothing.
