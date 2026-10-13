# Stacks Monitor — Complete User Guide

Stacks Monitor is a control center for web agencies: monitor the third‑party scripts on
your clients' sites, track uptime and domains, store logins in an encrypted vault,
watch performance and security, and keep everything organized per client and per
department.

This guide explains **every feature, how to use it, and how to get 100% benefit**.
Each page follows the same shape:

- **What it is** — the feature in one line
- **Where to find it** — how to reach it in the UI
- **How to use it** — step by step
- **Get 100% benefit** — pro tips most people miss
- **How it works** — the logic behind it, so you trust the numbers
- **Gotchas** — the traps and their fixes

## Contents

1. [Getting Started](01-getting-started.md) — login, 2FA, navigation, roles & departments
2. [Websites & Scripts](02-websites-and-scripts.md) — add sites, the tracking snippet, script detection, change log, unknown‑script review, plugins
3. [Forms & Performance](03-forms-and-performance.md) — form detection, failed‑submission alerts, Lighthouse, CrUX, the Optimization Plan
4. [Security & Site Health](04-security-and-site-health.md) — vulnerability scan, PHP errors, site events, CMS detection
5. [Credentials Vault](05-credentials-vault.md) — encrypted logins, granular sharing, autofill, the browser extension
6. [Uptime, Domains, Status Pages & Alerts](06-uptime-domains-status-alerts.md)
7. [Clients & ClickUp](07-clients-and-clickup.md)
8. [Reports](08-reports.md)
9. [Team, Roles & Departments](09-team-roles-departments.md) — and your personal **My Account** / 2FA

## The 60‑second mental model

- A **Team = a department** (e.g. *Web Department*, *SEO Department*). Everything —
  clients, websites, credentials, monitors, reports — lives inside one team and is
  invisible to other teams. People in two departments switch between them with the
  team switcher (bottom‑left).
- Each website carries a tiny **tracking snippet** (`/api/s.js`). When a real
  browser loads a page, the snippet reports the scripts and forms it sees. Stacks Monitor
  diffs that against what it saw before and raises **changes** and **alerts**.
- Detection is **passive** — data arrives only when real visitors (or you) load a
  page that has the snippet. There is no crawler.

## Roles at a glance

| Role | Sees | Can manage |
|------|------|-----------|
| **Owner** | Everything in the team | Everything, incl. team, settings, billing-level config |
| **Manager** | Everything in the team | Team members, settings, ClickUp, renewals |
| **Developer / Editor / SEO** | Only what's shared with them | Their own 2FA; the websites/data of the team; *not* team/settings |
| **Viewer** | Read‑only | Nothing |

Owners and managers see all credentials and the full activity log. Developer/Editor/SEO
are "member" roles with identical access — pick the label that matches the person's job.

> **Deploying changes?** This guide is for *using* Stacks Monitor. To ship code changes
> to the live site, see the deploy section in the repo's `CLAUDE.md` (`./deploy.sh`).
