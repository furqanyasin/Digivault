# Stacks Monitor — Complete Platform Guide

Stacks Monitor is an all-in-one platform for web agencies to monitor client websites: track third-party scripts, store credentials securely, monitor uptime, measure performance, and publish status pages — all under one account with team-based access control.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Account & Teams](#2-account--teams)
3. [Adding a Website](#3-adding-a-website)
4. [Installing the Snippet](#4-installing-the-snippet)
5. [Script Monitoring](#5-script-monitoring)
6. [Script Change Alerts](#6-script-change-alerts)
7. [Credentials Vault](#7-credentials-vault)
8. [Domain & SSL Tracking](#8-domain--ssl-tracking)
9. [Uptime Monitoring](#9-uptime-monitoring)
10. [Performance & Web Vitals](#10-performance--web-vitals)
11. [Status Pages](#11-status-pages)
12. [Chrome Extension](#12-chrome-extension)
13. [Roles & Permissions](#13-roles--permissions)
14. [API Reference](#14-api-reference)

---

## 1. Quick Start

**5 minutes to get your first site monitored:**

1. Register at `https://stacksmonitor.com/register`
2. Create your team (your agency name)
3. Add a website (client domain)
4. Copy the 2-line snippet from the **Snippet** tab → paste it into the site's `<head>`
5. Visit the site — Stacks Monitor receives the first payload and starts building your script inventory

That's it. Scripts appear in the **Scripts** tab within seconds of the first page load.


---

## 2. Account & Teams

### Registration

Go to `/register`. One email address = one account. Your account can belong to multiple teams (useful if you work with more than one agency).

### Teams

A **team** is your agency workspace. All websites, credentials, alerts, and monitors belong to a team — nothing is shared between teams.

**Create a team:** Dashboard → team name (top-left) → Create new team

**Switch teams:** Click the team name in the top-left dropdown → select another team

**Plans:** Starter · Agency · Agency Pro · Enterprise (controls limits — not feature gates in the current version)

### Inviting team members

**Who can invite:** Manager and Owner roles only.

1. Go to **Team** in the sidebar
2. Click **Invite member**
3. Enter their email and choose a role
4. They receive an invitation email with an acceptance link

If the invitee has no account yet, one is created automatically with a temporary password emailed to them.

**Roles:** See [Section 13 — Roles & Permissions](#13-roles--permissions)

### Switching between teams

If you're a member of multiple teams (e.g. a freelancer working with two agencies), use the team switcher in the top-left. Each team has completely separate data.

---

## 3. Adding a Website

1. Go to **Websites** → **Add Website**
2. Fill in:
   - **Name** — internal label (e.g. "Acme Corp Blog")
   - **Domain** — the root domain, e.g. `acme.com` (no `https://`, no trailing slash)
   - **Platform** — WordPress, Webflow, Wix, Shopify, Framer, Squarespace, or Custom
3. Click **Create**

Stacks Monitor generates a unique **Site ID** and a ready-to-paste snippet for this site.

### Regenerating the snippet

If you need to invalidate the current snippet (e.g. a contractor had access and left), go to the website → **Snippet** tab → **Regenerate**. The old Site ID stops working immediately.

### Deleting a website

Website detail page → **Delete** (Owner only). Deletes all associated scripts, changes, credentials, monitors, and domain data. Irreversible.

---

## 4. Installing the Snippet

The snippet is two lines of HTML. Copy it from the **Snippet** tab.

```html
<script async src="https://stacksmonitor.com/s.js"
        data-site="YOUR_SITE_ID"></script>
```

Paste it in the `<head>` of every page you want to monitor (ideally via your CMS's global header injection so it's on every page automatically).

### Platform-specific instructions

| Platform | Where to add it |
|---|---|
| **WordPress** | Install a "Header Footer Code" plugin, or use a theme's `functions.php` with `wp_head` hook |
| **Webflow** | Site Settings → Custom Code → Head Code |
| **Wix** | Settings → Custom Code → Add to `<head>` |
| **Framer** | Site Settings → General → Custom Code → Start of `<head>` |
| **Shopify** | Themes → Edit code → `theme.liquid` inside `<head>` |
| **Squarespace** | Settings → Advanced → Code Injection → Header |
| **Custom HTML** | Paste directly in `<head>` of your base template |

### Verify the snippet is installed

Website → **Snippet** tab → **Verify installation**. Stacks Monitor fetches your homepage and checks for the `data-site` attribute.

### How the snippet works

The snippet loads asynchronously (never blocks your page). When the DOM is ready it:
1. Scans all `<script>` tags on the page
2. Records: URL, location (head/body), async/defer flags
3. Sends a lightweight beacon to Stacks Monitor (fire-and-forget, uses `sendBeacon` API for zero performance impact)

---

## 5. Script Monitoring

### What you see

Open any website → **Scripts** tab. You get a full inventory of every third-party script detected on that site, enriched with:

| Column | What it means |
|---|---|
| **Provider** | The company that owns the script (e.g. Google Analytics, Hotjar, Intercom) |
| **Category** | What the script does (Analytics, Advertising, Chat, Tag Management, etc.) |
| **Location** | Where in the HTML it loads (Head, Body, Footer, Dynamic) |
| **Source domain** | The CDN or domain serving the script |
| **Status** | Pending review / Approved / Blocked / Ignored |

### Script categories

Analytics · Advertising · Tag Management · Session Recording · Call Tracking · Chat · CRM · Payment · SEO · Security · Performance · Social · **Unknown**

**Unknown** scripts are ones Stacks Monitor hasn't classified yet. They appear orange in the extension badge. Investigate these — they're the most likely to be problematic.

### Reviewing scripts

For each script you can set a review status:
- **Approved** — you've verified this is intentional
- **Blocked** — this should not be on the site (flags it for follow-up)
- **Ignored** — known but not worth tracking

### Server-side scan

Website → **Scan** button. Stacks Monitor fetches your homepage server-side and extracts scripts from the raw HTML — useful if the snippet hasn't been installed yet or you want a second opinion.

---

## 6. Script Change Alerts

Stacks Monitor's diff engine compares every new page load against the previous snapshot and creates a **Change** record whenever something is different.

### Change types

| Type | What happened |
|---|---|
| **Added** | A new script appeared that wasn't there before |
| **Removed** | A script disappeared |
| **Moved** | Script moved from head to body (or vice versa) |
| **URL Changed** | Same script, different URL (version bump or CDN change) |
| **Plugin Changed** | WordPress plugin version changed |

### Severity

| Severity | When |
|---|---|
| **High** | Unknown script added, payment script changed, security script removed |
| **Medium** | Analytics or tag manager changed |
| **Low** | Known script moved or minor URL change |

### Viewing changes

Website → **Changes** tab. Filter by severity, type, or "unacknowledged only".

### Acknowledging changes

Click **Acknowledge** on a change to mark it as reviewed. You can acknowledge in bulk. Unacknowledged high-severity changes appear prominently in the dashboard.

### Setting up alerts

Go to **Alerts** in the sidebar → **Create alert rule**.

| Setting | Options |
|---|---|
| **Scope** | All websites, or one specific website |
| **Channel** | Email · Slack · SMS · In-app |
| **Min severity** | High only · High + Medium · All |
| **Change types** | All, or specific types (e.g. Added only) |
| **Delivery** | Immediate · Hourly digest · Daily digest |

**Slack setup:** Create an Incoming Webhook in your Slack workspace and paste the URL into the alert rule.

**Digests:** Instead of one email per change, get a single summary email at the top of each hour (hourly digest) or at 8am each day (daily digest).

---

## 7. Credentials Vault

Store login credentials for client sites — encrypted, audited, and accessible from anywhere via the browser extension.

### Storing a credential

Website → **Credentials** tab → **Add credential**

| Field | Notes |
|---|---|
| **Label** | Friendly name, e.g. "WordPress Admin" |
| **Type** | WordPress · cPanel · GoDaddy · Cloudflare · FTP · Shopify · WP Engine · Kinsta · Custom + more |
| **Login URL** | Direct URL of the login page |
| **Username / Email** | |
| **Password** | Encrypted at rest with AES-256 (Fernet) |
| **Notes** | Any extra context |

### Accessing a credential

1. Find the credential in the list
2. Click **Reveal** — password is decrypted and shown for 30 seconds
3. Every reveal is logged (who, when, from which IP)

> Viewer-role members can see that a credential exists but cannot reveal the password.

### Credential types supported

WordPress · cPanel · GoDaddy · Namecheap · Hostinger · Cloudflare · FTP/SFTP · Wix · Webflow · Framer · Shopify · SiteGround · Bluehost · WP Engine · Kinsta · Custom

### Audit log

Website → **Credential Audit** tab (Manager+). See every reveal, copy, and edit with timestamp and IP address. Use this to prove who accessed what if a client asks.

### Autofill via the Chrome extension

Install the extension → sign in → visit any login page for a registered site → click the green shield in the username field → select the saved credential → fields fill automatically.

See [Section 12 — Chrome Extension](#12-chrome-extension) for full details.

---

## 8. Domain & SSL Tracking

Stacks Monitor automatically checks domain and SSL expiry for every registered website.

### What's tracked

| Data | Source |
|---|---|
| Registrar | WHOIS |
| Registration date | WHOIS |
| Expiry date | WHOIS |
| Auto-renew status | WHOIS |
| Nameservers | WHOIS |
| SSL issuer | Live TLS check |
| SSL expiry date | Live TLS check |
| Hosting provider | IP → ASN lookup |
| Cloudflare detection | IP range check |
| Server IP + location | Geo lookup |

### Viewing domain info

Website → **Domain** tab. Last checked timestamp shown. Click **Refresh** to run a fresh WHOIS + SSL check immediately.

### Expiry alerts

Stacks Monitor sends alerts as expiry approaches. Thresholds: 90 days · 30 days · 14 days · 7 days.

Alerts appear in the notification feed and are sent via your configured alert channels.

### How often it runs

Domain checks run daily via a scheduled background task. Use **Refresh** for on-demand updates.

---

## 9. Uptime Monitoring

Monitor any URL, port, or SSL certificate on a schedule from 30 seconds to 1 hour.

### Creating a monitor

**Monitors** → **New Monitor**

| Setting | Notes |
|---|---|
| **Name** | Display name |
| **Type** | HTTP · HTTPS · Ping · Port · SSL |
| **URL / Host** | Full URL for HTTP; hostname for ping/port |
| **Check interval** | 30s / 1m / 2m / 5m / 10m / 15m / 30m / 1h |
| **Timeout** | Request timeout in seconds |
| **Retries** | How many consecutive failures before status → DOWN |
| **Expected status** | e.g. 200 for HTTP monitors |
| **Keyword match** | Optional: mark DOWN if response body contains/lacks a string |

### Monitor statuses

| Status | Meaning |
|---|---|
| **UP** | All checks passing |
| **DOWN** | Failed more than retry threshold consecutively |
| **DEGRADED** | Intermittent failures or slow responses |
| **PAUSED** | Manually disabled |
| **PENDING** | Not yet run |

### Uptime percentages

Each monitor shows uptime for **last 24h**, **last 7 days**, **last 30 days**.

### Notification channels

**Monitors → Channels** → **New channel**

Supported: Slack · Discord · Webhook · Email · Telegram

Each channel is reusable across multiple monitors.

### Notification rules

Monitor detail → **Notifications** tab → **Add rule**

Trigger on: **Down** · **Recovery** · **Degraded** (choose any combination)

### Pausing a monitor

Useful during scheduled maintenance. Monitor detail → **Pause**. Badge shows PAUSED. No alerts fire while paused. **Resume** to re-enable.

---

## 10. Performance & Web Vitals

Two data sources: **Lighthouse** (lab data) and **Chrome UX Report / CrUX** (real user data).

### Lighthouse (PageSpeed Insights)

Website → **Performance** tab → **Run report**

Runs a full Lighthouse audit on your page and returns:

| Metric | What it measures |
|---|---|
| **Performance score** | 0–100 overall score |
| **FCP** | First Contentful Paint — when content first appears |
| **LCP** | Largest Contentful Paint — when main content loads |
| **CLS** | Cumulative Layout Shift — visual stability |
| **TBT** | Total Blocking Time — main thread blocked |
| **TTFB** | Time to First Byte — server response speed |
| **SI** | Speed Index — visual completeness over time |
| **TTI** | Time to Interactive — when page is fully interactive |
| **INP** | Interaction to Next Paint — responsiveness |

Each metric is rated **Fast** (green) · **Average** (orange) · **Slow** (red).

Run both **Mobile** and **Desktop** strategies — Google ranks mobile separately.

### Chrome UX Report (CrUX)

CrUX shows how **real Chrome users** actually experience your site — not a simulated test. Fetched weekly automatically (or on demand).

Shows **p75 values** (75th percentile — the experience of the 75% slowest user) and distribution percentages: what % of users have a Good / Needs Improvement / Poor experience for each Core Web Vital.

**Why CrUX matters more than Lighthouse for SEO:** Google's Page Experience ranking signal uses field data (CrUX), not lab data (Lighthouse). If CrUX shows Poor LCP for 40% of users, that's what affects your ranking — regardless of your Lighthouse score.

### Tracking trends

Every report is stored. Run reports regularly (e.g. after a deployment) to spot regressions.

---

## 11. Status Pages

Publish a public uptime status page for your clients — they can bookmark it and check for themselves rather than emailing you.

### Creating a status page

**Status Pages** → **New status page**

| Setting | Notes |
|---|---|
| **Name** | e.g. "Acme Corp — Service Status" |
| **Slug** | URL-safe identifier; becomes `https://stacksmonitor.com/status/<slug>` |
| **Description** | Optional subtitle shown on the public page |
| **Allow indexing** | Off by default — turn on if the page should be publicly searchable |

### Adding monitors to a status page

1. Open the status page → **Add monitor**
2. Select from your monitors
3. Optionally set a **Display name** (e.g. show "Main Website" instead of the internal monitor name — don't expose implementation details to clients)
4. Drag to reorder

### How the overall status is calculated

| Overall status | When |
|---|---|
| 🟢 Operational | All monitors UP |
| 🟡 Degraded | One or more monitors DEGRADED |
| 🔴 Outage | One or more monitors DOWN |

### Sharing with clients

Send clients the public URL: `https://stacksmonitor.com/status/<slug>`

The page auto-refreshes every 60 seconds. It shows:
- Overall status banner (green / yellow / red)
- Per-monitor current status
- 90-day uptime bar chart (one bar per day)

No login required to view a status page.

---

## 12. Chrome Extension

Install by loading the `extension/` folder unpacked in `chrome://extensions` (Developer mode).

### Feature 1 — Script badge

A badge on the toolbar icon shows the script count for every registered site you visit:
- **Green badge** — all scripts from known providers
- **Orange badge** — one or more unknown scripts detected
- **No badge** — site not registered in Stacks Monitor

You see this without clicking anything. It's the fastest way to spot a rogue script on a client site.

### Feature 2 — Script popup

Click the extension icon on any registered site to see:
- Total script count
- Unknown script count (flagged in orange)
- Top 10 scripts with provider, category, and source domain
- Link to open the full dashboard for that site

### Feature 3 — Credential autofill

**Setup:** Click ⚙ in the popup → enter your Stacks Monitor email and password → Log in.

**Using it:**
1. Visit any login page for a site with saved credentials
2. A **green shield icon** appears inside the username/email field
3. Click the shield → dropdown of saved credentials appears
4. Click a credential → username and password fill in automatically
5. Submit the form as usual

**Keyboard:** `↑` / `↓` to navigate the dropdown · `Escape` to close

> Credentials are fetched from the encrypted vault on demand. No passwords are stored in the browser or extension storage.

### Feature 4 — Auto-login to the web app

If you're signed into the extension and visit `https://stacksmonitor.com/login`, you're automatically logged into the web app and redirected to `/dashboard` — no typing required.

### Feature 5 — Auth status in popup

Open the popup while on the Stacks Monitor website to see your account status, jump to the dashboard, or sign out.

### Settings

Click ⚙ → Options:
- **Account** — Log in / log out of the extension
- **Server URL** — Only change this if you're running a self-hosted instance

---

## 13. Roles & Permissions

Every team member has one of four roles. Assign roles carefully — the **Viewer** role is appropriate for clients you want to give read access to; **Developer** for technical staff; **Manager** for leads; **Owner** for agency principals.

| Permission | Viewer | Developer | Manager | Owner |
|---|---|---|---|---|
| View websites, scripts, changes | ✅ | ✅ | ✅ | ✅ |
| Acknowledge script changes | ✅ | ✅ | ✅ | ✅ |
| Create / edit websites | ❌ | ✅ | ✅ | ✅ |
| Delete websites | ❌ | ❌ | ❌ | ✅ |
| View credential names / labels | ✅ | ✅ | ✅ | ✅ |
| Reveal credential passwords | ❌ | ✅ | ✅ | ✅ |
| Add / edit / delete credentials | ❌ | ✅ | ✅ | ✅ |
| View credential audit log | ❌ | ❌ | ✅ | ✅ |
| Create / edit alert rules | ✅ | ✅ | ✅ | ✅ |
| Create / edit monitors | ❌ | ✅ | ✅ | ✅ |
| Create / edit status pages | ❌ | ✅ | ✅ | ✅ |
| Invite team members | ❌ | ❌ | ✅ | ✅ |
| Change member roles | ❌ | ❌ | ✅ | ✅ |
| Remove members | ❌ | ❌ | ✅ | ✅ |
| Delete team | ❌ | ❌ | ❌ | ✅ |

> A Manager cannot invite someone to a role higher than their own.

---

## 14. API Reference

All endpoints require `Authorization: Bearer <access_token>` unless marked **public**.

Get a token: `POST /api/v1/auth/token/` with `{"email": "...", "password": "..."}` → returns `{"data": {"access": "...", "refresh": "..."}}`

Refresh: `POST /api/v1/auth/token/refresh/` with `{"refresh": "..."}` → returns `{"data": {"access": "..."}}`

All responses are wrapped: `{"data": ..., "errors": [], "meta": {}}`

### Auth & Teams
```
POST   /api/v1/auth/register/
POST   /api/v1/auth/token/
POST   /api/v1/auth/token/refresh/
GET    /api/v1/auth/me/
PATCH  /api/v1/auth/me/
GET    /api/v1/auth/teams/
POST   /api/v1/auth/teams/
GET    /api/v1/auth/teams/<id>/
PATCH  /api/v1/auth/teams/<id>/
POST   /api/v1/auth/teams/<id>/switch/
GET    /api/v1/auth/teams/<id>/members/
PATCH  /api/v1/auth/teams/<id>/members/<id>/
DELETE /api/v1/auth/teams/<id>/members/<id>/
POST   /api/v1/auth/teams/<id>/invite/
GET    /api/v1/auth/teams/<id>/invitations/
DELETE /api/v1/auth/teams/<id>/invitations/<id>/
GET    /api/v1/auth/invitations/<token>/          ← public
POST   /api/v1/auth/invitations/<token>/accept/   ← public
```

### Websites
```
GET    /api/v1/websites/
POST   /api/v1/websites/
GET    /api/v1/websites/<id>/
PATCH  /api/v1/websites/<id>/
DELETE /api/v1/websites/<id>/
GET    /api/v1/websites/<id>/snippet/
POST   /api/v1/websites/<id>/regenerate-snippet/
POST   /api/v1/websites/<id>/scan/
POST   /api/v1/websites/<id>/verify-snippet/
```

### Scripts & Changes
```
POST   /api/ingest/                               ← public (snippet endpoint)
GET    /api/extension/lookup/?domain=<domain>    ← public, rate-limited
GET    /s.js                                      ← public (snippet file)
GET    /api/v1/websites/<id>/scripts/
GET    /api/v1/websites/<id>/changes/
POST   /api/v1/changes/<id>/acknowledge/
PATCH  /api/v1/websites/<id>/scripts/<id>/review/
```

### Credentials
```
GET    /api/v1/websites/<id>/credentials/
POST   /api/v1/websites/<id>/credentials/
GET    /api/v1/credentials/<id>/
PATCH  /api/v1/credentials/<id>/
DELETE /api/v1/credentials/<id>/
POST   /api/v1/credentials/<id>/reveal/
GET    /api/v1/websites/<id>/credential-audit/
GET    /api/extension/credentials/?domain=<domain>
POST   /api/extension/web-handoff/
GET    /api/extension/exchange/?code=<code>       ← public (one-time)
```

### Domain, Alerts, Notifications
```
GET    /api/v1/websites/<id>/domain/
POST   /api/v1/websites/<id>/domain/refresh/
GET    /api/v1/alert-rules/
POST   /api/v1/alert-rules/
PATCH  /api/v1/alert-rules/<id>/
DELETE /api/v1/alert-rules/<id>/
GET    /api/v1/notifications/
POST   /api/v1/notifications/mark-read/
```

### Monitors & Status Pages
```
GET    /api/v1/monitors/
POST   /api/v1/monitors/
GET    /api/v1/monitors/<id>/
PATCH  /api/v1/monitors/<id>/
DELETE /api/v1/monitors/<id>/
GET    /api/v1/monitors/<id>/checks/
POST   /api/v1/monitors/<id>/pause/
POST   /api/v1/monitors/<id>/resume/
POST   /api/v1/monitors/<id>/check-now/
GET    /api/v1/notification-channels/
POST   /api/v1/notification-channels/
PATCH  /api/v1/notification-channels/<id>/
DELETE /api/v1/notification-channels/<id>/
GET    /api/v1/monitors/<id>/notification-rules/
POST   /api/v1/monitors/<id>/notification-rules/
PATCH  /api/v1/monitors/<id>/notification-rules/<id>/
DELETE /api/v1/monitors/<id>/notification-rules/<id>/
GET    /api/v1/status-pages/
POST   /api/v1/status-pages/
PATCH  /api/v1/status-pages/<id>/
DELETE /api/v1/status-pages/<id>/
GET    /api/v1/status-pages/<id>/monitors/
POST   /api/v1/status-pages/<id>/monitors/
PATCH  /api/v1/status-pages/<id>/monitors/<id>/
DELETE /api/v1/status-pages/<id>/monitors/<id>/
GET    /api/v1/public/status/<slug>/              ← public
```

### Performance
```
GET    /api/v1/websites/<id>/performance/
POST   /api/v1/websites/<id>/performance/run/
GET    /api/v1/websites/<id>/crux/
POST   /api/v1/websites/<id>/crux/run/
```

---

## Recommended Setup Workflow for a New Client

1. **Add the website** — enter domain and platform
2. **Install the snippet** — paste into site `<head>`, verify installation
3. **Let it run 24 hours** — builds the initial script inventory from real page loads
4. **Review scripts** — go through the Scripts tab, mark known scripts as Approved, investigate any Unknowns
5. **Save credentials** — add WordPress admin, hosting panel, DNS, etc. to the Credentials vault
6. **Add a monitor** — HTTPS check on the homepage with 5-minute interval
7. **Set up alerts** — create an email alert rule for High severity changes, immediate delivery
8. **Optionally add a status page** — link the monitor, share URL with the client
9. **Install the extension** — sign in, browse the client site to confirm badge shows correctly
