# 6. Uptime, Domains, Status Pages & Alerts

## Monitors (uptime)

**What it is:** continuous checks that tell you the instant a client site or service
goes down.

Open **Monitors**. Each website gets an HTTP monitor automatically; add more with
**New monitor**. Types:

| Type | Checks |
|------|--------|
| **HTTP/HTTPS** | The URL responds (status + response time) |
| **Ping** | Host is reachable |
| **Port** | A specific TCP port is open |
| **SSL Certificate** | The cert is valid and not expiring |

- Checks run on a schedule (the system evaluates due monitors **every 30 seconds**).
- Status is **Up / Down / Degraded / Paused / Pending**; you can **Pause**, **Resume**,
  or **Check now**.
- Each monitor has its own **notification rules** and an uptime history (rolled up
  daily).

**Get 100% benefit:** add an **SSL** monitor for every client — expiring certificates
cause silent outages, and this warns you in advance. Use **Port** monitors for mail
or database services clients rely on.

## Domains

**What it is:** WHOIS‑based domain registration + expiry tracking.

- A website's **Access & Domain** tab shows registrar, registration/expiry dates, and
  auto‑renew status. **Refresh** re‑pulls WHOIS.
- A background job re‑checks all domains **daily at 06:00 UTC**.

## Renewal Center *(owners & managers)*

**What it is:** one screen of everything expiring soon — domains, SSL, hosting, and
contract renewals — so nothing lapses.

Open **Renewal Center**. It aggregates expiry dates across the department and sorts by
urgency (colored by days remaining).

**Get 100% benefit:** make this your Monday view. Anything red/amber needs action this
week. Hosting and contract renewal dates come from the **Client** record — keep those
filled in (or sync from ClickUp) so they appear here.

## Status Pages (public)

**What it is:** a shareable public page showing real‑time uptime for a client's
services — like the big SaaS status pages.

- Each website auto‑gets one. Manage them under **Status Pages**.
- **Manage** to set branding, which monitors appear, and to post **incidents** and
  scheduled **maintenance** windows. **View public** opens the live page at
  `/status/<slug>`.
- Pages are `noindex` by default (won't show in Google) — toggle if you want it public.

**Get 100% benefit:** add only the monitors clients care about, and post an incident
when something breaks — it cuts "is the site down?" emails dramatically. Duplicate
status pages are prevented automatically (one per site).

## Alerts & notifications

**What it is:** rules that decide *who gets told, how, and how often* when scripts
change (or monitors fire).

Open **Alerts**. Create **alert rules** with:

- **Channel:** Email, Slack, or In‑App (real‑time toast in the dashboard).
- **Delivery mode:** Immediate, Hourly digest, or Daily digest.
- **Conditions:** by severity, by provider, or by source domain.

Manage delivery endpoints under **Notification Channels** (e.g. add and **test** a
Slack webhook).

**Get 100% benefit:**
- Route **critical/high** script changes to **Immediate Slack** so the team sees them
  live; send **medium/low** to a **Daily digest** email to avoid noise.
- Use **provider/domain** conditions to mute known‑noisy scripts while still catching
  the unexpected ones.
- In‑app alerts arrive over a live WebSocket — keep the dashboard open and you'll see
  changes the moment they're detected.

## How it works

- Monitor checks are pure functions (HTTP/ping/port/SSL) dispatched every 30 s; results
  roll up into daily uptime and feed status pages.
- Script changes create notifications; rules decide channel + timing; digests are sent
  hourly (top of the hour) and daily (08:00 UTC).

## Gotchas

- **No alerts arriving?** Check you have an alert rule *and* a configured channel
  (test the Slack webhook), and that the change isn't muted by a provider/domain
  condition.
- **Status page shows nothing:** add monitors to it under **Manage**.
