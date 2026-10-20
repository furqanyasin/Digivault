# Public Launch Plan: Marketing Site + Multi-Tenant Signup

**Status:** Phase 0, 1 (core) and 2 built on `feat/tenant-hardening` (2026-10-21)
**Date:** 2026-10-14
**Goal:** Open Stacks Monitor to the public. Anyone can sign up, gets a private
workspace, and never sees another workspace's data. A marketing site on
stacksmonitor.com brings them in through search.

---

## 1. Where we stand today

### What already works for multi-tenancy

| Piece | State |
|---|---|
| `Team` model = one tenant (agency or freelancer) | Exists, `apps/accounts/models.py` |
| Roles: owner, manager, developer, viewer, custom | Exists, `apps/common/permissions.py` |
| Data scoped to `request.user.active_team` | `TeamScopedMixin`, `TeamScopedQuerySet`, used by websites, monitors, heatmap, status pages, scripts |
| Team switcher (user in several teams) | Exists |
| Sub-teams for credential access | Exists |
| `Team.plan` field (starter, agency, agency_pro, enterprise) | Field exists, nothing enforces it |

The data model is already tenant-shaped. The gaps are in **account flows**,
which were built for one internal company where every manager is trusted.

### What blocks a public launch

- No self-signup. `/register` redirects to `/login`, and the backend register
  endpoint was removed on purpose (`apps/accounts/urls.py`).
- Password reset needs a manager to approve it. A solo signup has nobody to
  approve it.
- `/` redirects to `/dashboard`. There is no public page at all.
- Four account endpoints trust "any manager of any team". Once strangers can
  become owners of their own team, these become a cross-tenant account
  takeover. See section 2.

---

## 2. Phase 0: Security blockers (must ship before signup opens)

Today every owner and manager is a colleague, so these are low risk. After
signup opens, every new user is the owner of a team, so each one is reachable
by an attacker.

### 2.1 The takeover chain

An attacker signs up, which makes them owner of their own team. Then:

1. `POST /auth/teams/<own team>/users/` with the victim's email.
   `TeamCreateUserView` finds the existing account and adds the victim to the
   attacker's team **without asking the victim** (`apps/accounts/views.py:822`).
2. `GET /auth/teams/<own team>/members/` now returns the victim's user id.
3. `POST /auth/password-reset/` with the victim's email (public endpoint).
4. `POST /auth/password-reset/<id>/approve/`. The attacker now "shares a team"
   with the victim, so approval passes, and the response body contains
   `reset_url` (`apps/accounts/views.py`, `PasswordResetApproveView`).
5. `POST /auth/2fa/disable/` with `user_id=<victim>`. `TotpDisableView` checks
   that the caller is a manager of *their own* active team, but never checks
   that the target is a member of that team (`apps/accounts/totp_views.py:207`).
6. Set the new password, log in as the victim, open the victim's real
   workspace and its credentials vault.

### 2.2 Fixes

| # | Fix | File |
|---|---|---|
| S1 | Adding an existing user to a team always becomes an **invitation the user must accept**. Never create the membership directly, never revive a deactivated account, never return `set_password_url` for an account that already exists. | `TeamCreateUserView` |
| S2 | Approving a reset never returns `reset_url` in the response. Email only. | `PasswordResetApproveView` |
| S3 | Replace admin-approved reset with self-service email reset (signed, single-use, 1 hour token). Managers get "send reset email" only. | `PasswordResetRequestView` and friends |
| S4 | `TotpDisableView` for another user: target must be a member of the caller's active team, with a role lower than the caller's. Better: replace with "reset 2FA on next login", which forces re-enrolment instead of switching it off. | `totp_views.py` |
| S5 | Same "target must be in my team" check on every view that takes a `user_id`: member detail, credential shares, folder members, handover, summary. | `accounts/views.py`, `credentials/views.py` |

### 2.3 Isolation test suite

Write one test module that proves isolation for every endpoint, so a future
view cannot quietly skip the team filter.

- Fixture: team A with a full set of objects (client, website, monitor,
  credential, folder, status page, report, alert rule, notification channel,
  heatmap rows, audit logs). Team B, empty.
- Walk every URL in `config/urls.py`. For each detail route, request team A's
  object id while logged in as team B's owner. Expect 404 (not 403, so ids are
  not confirmed to exist).
- For each list route, team B must get an empty result.
- Add the takeover chain from 2.1 as a test that must fail at step 1.
- Add a CI guard: a new view class that is not in an allowlist and does not use
  `TeamScopedMixin` or a team filter fails the test.

**Done when:** S1 to S5 merged, isolation suite green, takeover test green.

### 2.4 Status (2026-10-14, branch `feat/tenant-hardening`)

| Item | State |
|---|---|
| S1 existing user gets an invitation, never a direct membership or a returned link | Done |
| S2 + S3 self-service reset (1 hour, single use, per-account cooldown); approve/reject flow and its UI removed | Done |
| S4 2FA reset for others: same team, lower role, primary owner protected | Done |
| S5 other `user_id` views | Checked: credential shares, folder members, handover and summary already filter by team |
| Invitation accept no longer takes a password and returns tokens (it skipped 2FA) | Done |
| Team rename checks the role in that team, not the active one | Done |
| `tests/accounts/test_cross_tenant_accounts.py` | Takeover chain and each fix |
| `tests/common/test_tenant_isolation.py` | Sweeps every API route with another team's ids, all methods. Fails on any unmapped new route. |

### 2.4b Status (2026-10-21): launch build

| Item | State |
|---|---|
| Signup + email verify (`apps/accounts/signup_views.py`, `PendingSignup`) | Done. Nothing is created until the link is clicked. |
| `Team.plan` free/internal, `Team.require_2fa`, existing teams moved to internal + 2FA | Done (migration 0017) |
| Plan limits (`apps/accounts/plans.py`): websites, monitors, members, status pages, check interval, one free workspace per person | Done. `ENFORCE_PLAN_LIMITS` off in test settings only. |
| `plan` no longer writable by team owners through `PATCH /auth/teams/<id>/` | Done |
| 2FA optional for signup workspaces, daily banner, forced for superusers and `require_2fa` teams | Done |
| Platform owner: `/platform` page + `/api/v1/platform/*`, `make_platform_owner` run on api start from `PLATFORM_OWNER_EMAILS` | Done |
| Marketing site: home, features (9), pricing, free tools (4), contact, security, privacy, terms, sitemap, robots, OG image | Done |
| Free tools API `/api/v1/public/tools/{ssl,domain,uptime,scripts}/`, throttled + cached + SSRF guarded | Done |
| Design tokens `frontend/src/styles/design-tokens.css` | Done |
| Turnstile captcha on signup | Not done (honeypot + per-IP throttle + disposable domain list for now) |
| Workspace delete/export, onboarding checklist, retention per plan | Not done |

### 2.5 Follow-ups found during Phase 0

- **Sessions survive a password reset.** `BLACKLIST_AFTER_ROTATION` is on, but
  `rest_framework_simplejwt.token_blacklist` is not in `INSTALLED_APPS`, so no
  refresh token can be revoked. Install it and blacklist a user's tokens on
  password reset, removal from their last team, and 2FA reset.
- **Turning off your own 2FA needs no code.** A stolen session can switch it
  off. Ask for a current TOTP or backup code.
- **Email squatting.** An owner can create an account for an email nobody
  has registered yet. Phase 1 signup must treat such accounts as unverified
  and let the real owner of the email take them over.
- **Login `next` is lost on the 2FA setup and first-password pages.** Only
  the direct and TOTP-code paths honour it today.

---

## 3. Phase 1: Self-serve accounts

### 3.1 Signup

New endpoint `POST /api/v1/auth/signup/`:

- Fields: name, email, password, workspace name (default "<Name>'s workspace").
- Cloudflare Turnstile token, throttled per IP, disposable-email blocklist.
- Creates the user inactive, sends a verification email.
- On verify: activate the user, `TeamService.create(name, owner=user)` with
  `plan=free` and `require_2fa=False`, set `active_team`. One transaction.
- Same response for "email already registered" and success, so it cannot be
  used to check which emails have accounts. The existing owner gets a "someone
  tried to sign up with your email" mail instead.

Frontend: replace the redirect in `src/app/(auth)/register/page.tsx` with a
real `/signup` page and a `/verify-email` page. Add both to `PUBLIC_PATHS` in
`src/proxy.ts`.

### 3.2 2FA: optional, with a daily reminder

Decided: 2FA is **off by default** for new signups. Users who have not enabled
it get a reminder every day until they do.

Today `LoginView` forces setup for everyone (`requires_setup` response in
`apps/accounts/totp_views.py`). Change:

- New field `Team.require_2fa` (bool). Default `False` for signup teams.
  Data migration sets it `True` for the existing internal team, so current
  staff keep mandatory 2FA.
- `LoginView`: return `requires_setup` only when the user's active team has
  `require_2fa=True`. Otherwise issue tokens directly.
- Owners can switch `require_2fa` on in team settings for their own members.
- Reminder:
  - New field `User.twofa_reminder_dismissed_at` (nullable datetime).
  - `/auth/me/` returns `show_2fa_reminder = not totp_enabled and
    (dismissed_at is null or older than 24 hours)`.
  - Dashboard layout shows a banner: "Protect your account and your client
    passwords. Enable 2FA (2 minutes)." Buttons: "Enable now" goes to
    `/2fa/setup`, "Remind me tomorrow" posts the dismiss.
  - The existing `Notification` model is tied to a website and a rule, so it
    does not fit a per-user reminder. The banner is the daily channel.
  - Email: one reminder on day 1 and one on day 7 after signup, then stop.
    Daily email would read as spam and hurt deliverability for
    verification and reset mails.
- Stronger nudge on the vault: when a user without 2FA opens
  `/credentials`, show the banner inline at the top of the page even if it
  was dismissed today.

### 3.3 First-run onboarding

A new workspace is empty. Add a 3-step checklist on `/dashboard`:

1. Add your first website.
2. Install the snippet (copy code, WordPress plugin, verify button).
3. Add an alert channel (email is pre-filled).

### 3.4 Plan limits and fair use

Decided: a **free plan with 1 website**. Paid plans are upgraded by hand
(section 6), so there is no checkout at launch.

- Add `FREE = "free"` and `INTERNAL = "internal"` to `Team.Plan`. Signup
  teams start on `free`.
- Data migration: the existing internal team moves to `internal` (every limit
  is `None`, never shown on the pricing page) with `require_2fa=True`.
- One module, `apps/accounts/plans.py`, holds a dict of limits per plan.

#### Competitor pricing (researched 2026-10-14)

Third-party sources disagree on some figures. Check each vendor's own pricing
page before quoting these publicly.

| Product | What it covers | Price |
|---|---|---|
| UptimeRobot | Uptime, SSL and domain (paid only), status pages | Solo about $9 to 12/mo (10 monitors), Team about $33 to 39/mo (100 monitors), Enterprise from about $69/mo. Free plan now non-commercial only. |
| Better Stack | Uptime, on-call, status pages | Free 10 monitors. $29 to 34 per responder/mo, extra monitor packs, white-label status page about $208/mo. |
| WP Umbrella | WordPress maintenance and monitoring | About €1.99 per site/mo flat, security add-on about €2 per site/mo. |
| ManageWP | WordPress maintenance | Core free. Each add-on $1 per site/mo or $25 per 100 sites; everything for 100 sites $150/mo. |
| Bitwarden Teams | Password vault | About $4 per user/mo. |

Takeaways:

- Agencies think and pay **per client site**. The market rate for a
  monitoring or maintenance tool is roughly **$1 to $2 per site per month**.
- Uptime-only tools are cheap and crowded. We justify a higher per-site price
  only because one plan covers uptime, SSL and domain, script change alerts,
  the vault and status pages. Those would otherwise be 3 or 4 tools.
- Price by websites, not by users or monitors. Members are a soft limit so
  the whole agency can join.

#### Proposed tiers (draft, owner to confirm)

USD, monthly. Annual = 10x monthly (2 months free). Billing is manual at
launch, so these are list prices for invoices and the pricing page.

| | Free | Starter | Agency | Agency Pro | Enterprise |
|---|---|---|---|---|---|
| Price per month | $0 | $19 | $49 | $99 | Custom |
| Effective per site | n/a | $1.90 | $1.63 | $1.32 | n/a |
| Websites | 1 | 10 | 30 | 75 | 75+ |
| Uptime monitors | 3 | 50 | 150 | 400 | Custom |
| Min check interval | 5 min | 1 min | 1 min | 30 s | 30 s |
| Team members | 1 | 3 | 10 | Unlimited | Unlimited |
| Status pages | 1 | 3 | 10 | Unlimited | Unlimited |
| Script change monitoring | Yes | Yes | Yes | Yes | Yes |
| SSL and domain expiry | Yes | Yes | Yes | Yes | Yes |
| Credentials vault | Yes | Yes | Yes + sub-teams | Yes + sub-teams | Yes + sub-teams |
| Heatmap events per month | 10k | 100k | 500k | 2M | Custom |
| Manual PageSpeed runs per day | 1 | 20 | 60 | 150 | Custom |
| WordPress vulnerability scan | No | Yes | Yes | Yes | Yes |
| Client reports (PDF) | No | Yes | Yes | Yes | Yes |
| ClickUp integration | No | No | Yes | Yes | Yes |
| Data retention (checks, events) | 7 days | 30 days | 90 days | 1 year | Custom |
| Support | Docs | Email | Email, priority | Email + call | Dedicated |

Why these numbers:

- **Free = 1 site, everything on.** The point of Free is to show the
  combination working on a real site. Turning features off would hide the
  reason to upgrade.
- **Starter $19:** between UptimeRobot Solo (about $9 to 12, uptime only) and
  Team (about $33 to 39). A freelancer with 5 to 10 client sites.
- **Agency $49 / Agency Pro $99:** per-site price drops with volume, and stays
  under ManageWP's all-in $150 for 100 sites.
- The plan names `starter`, `agency`, `agency_pro`, `enterprise` already
  exist in `Team.Plan`, so no rename is needed.

#### Cost guards behind the limits

- **WPScan is the tight one.** The free API key allows 25 requests a day, and
  a scan spends one request per plugin and theme, so one site with 30
  plugins already exceeds it. Options: buy a WPScan paid tier sized to paid
  sites only, or switch to the Wordfence Intelligence vulnerability feed
  (free, download once a day, match locally, so cost does not grow with
  sites). Check Wordfence's current licence terms before switching.
  Recommendation: the Wordfence feed, since it removes a per-tenant cost.
- **PageSpeed:** one key, 25k requests a day across all tenants. Scheduled
  daily runs stay on; the per-team manual-run cap protects the shared quota.
- **Retention** is the main storage lever. Hook the per-plan days into the
  existing purge jobs (`apps/common/partitions.py` and the per-app
  `tasks.py` purges in monitors, heatmap, scripts, performance, alerts).
- On downgrade (manual), keep data but pause the newest websites above the
  limit, never delete. The owner picks which ones stay active.

- When a limit is hit, the API returns a 402-style error with
  `code: "plan_limit"`, and the UI shows "Free plan includes 1 website.
  Contact us to upgrade." with a link to `/contact` (or a mailto).

Other limits, needed for every plan:

| Limit | Why |
|---|---|
| Websites, monitors, members, status pages | Pricing tiers |
| Minimum check interval | A free user at 30s across 50 monitors is real load |
| PageSpeed, WPScan, WHOIS runs per day | These use one shared API key (`config/settings/base.py`). One tenant can burn the quota for everyone. |
| Heatmap events per month | Ingest is public and high volume |
| Monitor target rate | Monitors make outbound requests. Without a cap, a free account is a free load tester. `apps/common/ssrf.py` already blocks private targets. |

Enforce in serializers' `create`, return a clear "upgrade" error, show usage
on the settings page.

### 3.5 Account lifecycle

- Delete workspace (owner, typed confirmation, 7 day grace, then hard delete
  including vault rows and media).
- Export workspace data (JSON + CSV), already partly there for clients and
  credentials.
- Delete my account (refused while sole owner of a team with other members).

### 3.6 Platform admin

Staff need to see tenants for support without being team members. Keep this
in Django admin, read-only for tenant data, never the vault plaintext. Log
every staff view in the audit log.

---

## 4. Phase 2: Marketing site

### 4.1 Structure

Same Next.js app, same domain. A new route group renders static pages with
their own header and footer, separate from the dashboard shell.

```
frontend/src/app/
  (marketing)/
    layout.tsx              header, footer, no auth providers
    page.tsx                home  (replaces the redirect in app/page.tsx)
    pricing/page.tsx
    features/
      uptime-monitoring/page.tsx
      ssl-domain-monitoring/page.tsx
      script-monitoring/page.tsx
      credentials-vault/page.tsx
      status-pages/page.tsx
      performance-monitoring/page.tsx
      heatmaps/page.tsx
      chrome-extension/page.tsx
    for-agencies/page.tsx
    for-freelancers/page.tsx
    compare/[slug]/page.tsx  uptimerobot, managewp, pingdom, statuspage
    security/page.tsx
    about/page.tsx
    contact/page.tsx
    privacy/page.tsx
    terms/page.tsx
  sitemap.ts
  robots.ts
  opengraph-image.tsx
```

Notes:

- `/` today is `redirect("/dashboard")`. New behaviour: logged-out visitors see
  the home page; the header shows "Go to dashboard" when an `ss_access` cookie
  is present. Do not auto-redirect logged-in users, or Google's crawler and
  shared links behave inconsistently.
- `src/proxy.ts`: add every marketing path to `PUBLIC_PATHS`, and exclude
  `sitemap.xml`, `robots.txt`, `opengraph-image` and `icon` from the matcher.
  Easiest is an explicit marketing allowlist plus `/` as an exact match (a
  `startsWith("/")` check would open everything).
- Marketing pages are Server Components with no client data fetching. They
  must not import the dashboard `Providers`, react-query, or chart libraries.
- Read `node_modules/next/dist/docs/` for the Next 16 metadata, sitemap and
  OG image conventions before writing them (`frontend/AGENTS.md`).

### 4.2 Technical SEO checklist

- Root `metadata`: `metadataBase: new URL("https://stacksmonitor.com")`,
  title template `"%s | Stacks Monitor"`, default description.
- Every page: unique title (under 60 chars), description (under 155 chars),
  canonical URL, OG image.
- `robots.ts`: allow marketing, disallow `/dashboard`, `/api/`, all
  `(dashboard)` and `(auth)` routes except `/login` and `/signup`.
- `sitemap.ts`: marketing pages only.
- JSON-LD: `Organization` on home, `SoftwareApplication` with `offers` on
  pricing, `FAQPage` on each feature page that has an FAQ block.
- One H1 per page that contains the page's primary keyword.
- Internal links: every feature page links to pricing, signup and two sibling
  features.
- Core Web Vitals: static rendering, `next/image` for screenshots, fonts are
  already self-hosted via `next/font`.
- Google Search Console and Bing Webmaster verified before launch; submit the
  sitemap on day one.

---

## 5. Keyword research

### 5.1 Method and limits

- Competitors studied: UptimeRobot (has an agency page), Better Stack,
  Pingdom, Observioo, upsonar, ManageWP, MainWP, WP Umbrella, Bitwarden and
  TeamPassword (agency vaults), cside and pagecrawl (PCI script monitoring).
- **Search volumes are not in this doc.** The Ahrefs connector is not
  authorised in this environment, and the web results did not give reliable
  numbers. Difficulty below is a judgement from who ranks on page one, not a
  tool score. Before writing copy, pull volume and KD for each keyword from
  Ahrefs, Semrush or Google Keyword Planner (country: US, UK, plus one target
  market) and fill in the two empty columns.

### 5.2 Positioning

Generic "uptime monitoring" is owned by UptimeRobot, Better Stack and
Pingdom. We will not outrank them soon. Our angle is the **combination** no
single competitor has:

> Every client website in one dashboard: uptime, SSL and domain expiry,
> third-party script changes, and a shared credentials vault. Built for web
> agencies.

Lead with "for agencies". Win the long-tail and the niche (script monitoring)
first, then climb toward the head terms.

### 5.3 Keyword map

Priority: **P1** = build at launch, **P2** = first month, **P3** = later.
Difficulty: H / M / L, estimated.

| Page | Primary keyword | Secondary keywords | Intent | Diff. | Pri. | Volume | KD |
|---|---|---|---|---|---|---|---|
| Home | website monitoring for agencies | client website monitoring, monitor multiple websites, agency website management dashboard | Commercial | M | P1 | | |
| /for-agencies | website maintenance tool for agencies | manage client websites, web agency tools | Commercial | M | P1 | | |
| /features/script-monitoring | third-party script monitoring | javascript change detection, magecart detection, client-side script monitoring | Commercial | L | P1 | | |
| /features/script-monitoring (section) | PCI DSS 6.4.3 script inventory | PCI DSS 11.6.1 change detection, payment page script monitoring | Commercial, compliance | L to M | P1 | | |
| /features/uptime-monitoring | uptime monitoring for agencies | website uptime monitor, website down alert, multi-site uptime monitoring | Commercial | H (head), M (long-tail) | P1 | | |
| /features/ssl-domain-monitoring | ssl certificate expiry monitoring | domain expiration monitoring, ssl expiry alert, domain renewal reminder | Commercial | M | P1 | | |
| /features/credentials-vault | password manager for agencies | share client passwords securely, client credentials vault, website login sharing for teams | Commercial | M to H | P1 | | |
| /features/status-pages | status page for clients | white label status page, free status page | Commercial | M | P2 | | |
| /features/performance-monitoring | core web vitals monitoring | pagespeed monitoring, lighthouse monitoring, crux monitoring | Commercial | M | P2 | | |
| /features/heatmaps | website heatmap tool | free heatmap, click heatmap | Commercial | H (Hotjar, Clarity) | P3 | | |
| /features/chrome-extension | (brand + feature) | credential autofill extension, script checker extension | Navigational | L | P3 | | |
| /pricing | stacks monitor pricing | website monitoring pricing | Transactional | L | P1 | | |
| /compare/uptimerobot | uptimerobot alternative | uptimerobot vs | Commercial | M | P2 | | |
| /compare/managewp | managewp alternative | mainwp alternative, wp umbrella alternative | Commercial | M | P2 | | |
| /compare/pingdom | pingdom alternative | | Commercial | M | P3 | | |
| /compare/statuspage | statuspage alternative | atlassian statuspage alternative | Commercial | M | P3 | | |
| /security | (trust page, no target) | | Trust | n/a | P1 | | |

### 5.4 Free tools (phase 4, biggest SEO lever)

Free tools rank for high-volume "checker" searches and convert to signups.
The backend already does each check.

| Tool URL | Keyword | Backend already has |
|---|---|---|
| /tools/ssl-checker | ssl checker, check ssl certificate expiry | `apps/domains` |
| /tools/domain-expiry-checker | domain expiry checker, whois expiry date | `apps/domains` |
| /tools/website-script-scanner | check third party scripts on website | server-side scan in `apps/scripts` |
| /tools/is-my-website-down | is my website down, website down checker | `apps/monitors` |

Each tool: no login, rate-limited, result page with "monitor this daily, free"
signup CTA.

### 5.5 Content (phase 4)

A `/blog` with 2 posts a month, each linked to one feature page:

- "PCI DSS 6.4.3 and 11.6.1: a checklist for agencies running client stores"
- "Client website handover checklist"
- "How to share client passwords without Slack or spreadsheets"
- "Domain and SSL renewal tracking for 50+ client sites"
- "Agency website maintenance plan: what to monitor and how to price it"

---

## 6. Phase 3: Launch readiness

| Item | Note |
|---|---|
| Privacy policy, terms, DPA | We store client credentials and visitor heatmap data. GDPR applies to EU agencies. |
| Cookie consent | Only if marketing pages load analytics. Plausible or similar avoids the banner. |
| Transactional email | Verification and reset now depend on email. Dedicated provider, SPF, DKIM, DMARC on stacksmonitor.com. |
| Billing | Decided: **manual at launch.** User asks to upgrade through `/contact`; staff changes `Team.plan` in Django admin; invoice sent by hand. Every plan change is written to the audit log. Add Paddle, Lemon Squeezy or Stripe later. |
| Pricing page | Shows Free (1 website) and paid tiers with a "Contact us" button instead of checkout. |
| Abuse handling | Report link in footer, ability to suspend a team from Django admin. |
| Backups and restore drill | `backup-db.sh` exists; test a restore before launch. |
| Monitoring of the app itself | Error tracking and an uptime monitor on our own status page. |
| Load check | Celery capacity with 100 new tenants each running 10 monitors. |

---

## 7. Order of work

| Step | Phase | Output |
|---|---|---|
| 1 | 0 | S1 to S5 fixes |
| 2 | 0 | Isolation test suite + takeover test |
| 3 | 1 | Signup, email verify, self-service reset |
| 4 | 1 | Onboarding checklist |
| 5 | 1 | Plan limits and per-team quotas |
| 6 | 2 | Marketing layout, home, pricing, P1 feature pages |
| 7 | 2 | Metadata, sitemap, robots, JSON-LD, OG images, proxy changes |
| 8 | 3 | Legal pages, email setup, Search Console |
| 9 | 3 | Soft launch (invite list), then public |
| 10 | 4 | Free tools, comparison pages, blog |

Steps 6 and 7 do not depend on Phase 0 and can run in parallel. **Signup must
not go live before steps 1 and 2.**

---

## 8. Decisions

### Made (2026-10-14)

| Topic | Decision | Where in plan |
|---|---|---|
| Free plan | Yes, 1 website | 3.4 |
| Billing | Manual at launch, payment provider later | 6 |
| 2FA | Off by default, daily in-app reminder until enabled | 3.2 |
| Domain | Marketing and app both on stacksmonitor.com | 4.1 |

### Proposed, waiting for owner sign-off

1. Paid tiers and limits: draft in 3.4 (Starter $19, Agency $49,
   Agency Pro $99, Enterprise custom).
2. Current internal team: stays one tenant on a new `internal` plan with no
   limits and `require_2fa=True`.
3. WordPress vulnerability data: move from the WPScan API to the Wordfence
   Intelligence feed (3.4, cost guards).
