# Digivault — Software Requirements Specification (As-Built)

**Document type:** SRS / system description of the system as implemented
**Version:** 1.0
**Date:** 2026-08-02
**Repository:** `d:\tools-working\Digivault` (branch `phase-0-hardening`)
**Live deployment:** https://digivault.digilatics.co

> This document describes what the Digivault portal **actually does today**, derived
> from the source tree rather than from a plan. Where the implementation diverges from
> intent or from configuration, that divergence is recorded in
> [§16 Known constraints, divergences and gaps](#16-known-constraints-divergences-and-gaps)
> rather than smoothed over.

---

## Table of contents

1. [Introduction](#1-introduction)
2. [Overall description](#2-overall-description)
3. [System architecture](#3-system-architecture)
4. [Cross-cutting mechanisms](#4-cross-cutting-mechanisms)
5. [Accounts, teams, roles and feature access](#5-accounts-teams-roles-and-feature-access)
6. [Authentication, 2FA and onboarding](#6-authentication-2fa-and-onboarding)
7. [Clients](#7-clients)
8. [Websites](#8-websites)
9. [Script ingest pipeline](#9-script-ingest-pipeline)
10. [Forms, form submissions and form errors](#10-forms-form-submissions-and-form-errors)
11. [JavaScript error capture](#11-javascript-error-capture)
12. [Alerts and notifications](#12-alerts-and-notifications)
13. [Uptime monitoring and notification channels](#13-uptime-monitoring-and-notification-channels)
14. [Domain, SSL, hosting and mail intelligence](#14-domain-ssl-hosting-and-mail-intelligence)
15. [Performance and Core Web Vitals](#15-performance-and-core-web-vitals)
16. [Known constraints, divergences and gaps](#16-known-constraints-divergences-and-gaps)

> Chapters 17–28 (Site health, Status pages, Reports, Audit log, Chatbot,
> Credential vault, Chrome extension, Frontend, Scheduled jobs, Retention,
> Non-functional requirements, Deployment, Testing, API catalogue) continue in
> [`digivault-srs-part2.md`](digivault-srs-part2.md).

---

## 1. Introduction

### 1.1 Purpose

Digivault is a multi-tenant SaaS platform through which a web agency monitors the
websites it manages on behalf of its clients. Its founding concern is the
**third-party JavaScript inventory** of a client site — what tags, pixels and
trackers are present, when they change, and whether a change was authorised. Around
that core it has accumulated the other operational surfaces an agency needs for the
same fleet of sites: uptime, domain and certificate expiry, hosting renewals, page
performance, SEO indexability, HTTP security posture, WordPress vulnerability
exposure, PHP and JavaScript error capture, form inventory and deliverability, an
encrypted credential vault, public status pages, client reporting and an audit trail.

This document specifies each of those capabilities: the data it stores, the rules it
applies, the interfaces it exposes and the background work it schedules.

### 1.2 Scope

Three deployable components live in one monorepo:

| Component | Path | Technology | Runtime |
|---|---|---|---|
| Backend API | `/` | Django 5.1.4, DRF 3.15, Celery 5.4, PostgreSQL 16, Redis 7, Django Channels 4 | Docker Compose (Daphne ASGI) |
| Web portal | `frontend/` | Next.js 16.2.6 App Router, React 19.2, TypeScript 5, Tailwind v4 | Host process under pm2 |
| Browser extension | `extension/` | Chrome Manifest V3 | User's browser |

A fourth artefact is not deployed but is **installed by the customer**: the tracking
snippet `apps/scripts/snippet.js`, served at `GET /api/s.js` and pasted into the
client's site. An optional WordPress PHP snippet (`apps/websites/wp_sso_snippet.py`)
enables one-click `wp-admin` login.

### 1.3 Definitions, acronyms and abbreviations

| Term | Meaning |
|---|---|
| **Team** | The tenant boundary. One agency, or one department within an agency. Every resource belongs to exactly one team. |
| **Active team** | The single team a user is currently "acting as" (`User.active_team`). Determines what every request sees. |
| **Website** | A registered client site, identified to the snippet by an opaque `site_id`. |
| **Client** | A commercial customer record: hosting platform, renewal dates, tier, departments, revenue. Zero or more Websites hang off it. |
| **Snippet** | The JS tag embedded in client pages that reports scripts, forms, form errors and JS errors. |
| **Script** | One unique third-party script on one Website, keyed by normalised URL. |
| **ScriptChange** | A diff event (added / removed / moved / url_changed / plugin_changed / inline_changed). |
| **Snapshot** | The raw, unfiltered payload of one snippet page-load event. Retained 90 days. |
| **Monitor** | An uptime check (HTTP, ping, port or SSL) run on an interval. |
| **Health score** | A 0–100 composite per Website, and the single writer of Website `status`. |
| **Envelope** | The `{data, errors, meta}` wrapper around every DRF response. |
| **BFF** | Backend-for-frontend: the Next.js `/api/*` route handlers that hold the HttpOnly cookies and proxy to Django. |
| **PSI / CrUX** | Google PageSpeed Insights (lab data) / Chrome UX Report (field data). |
| **TOTP** | Time-based one-time password — the 2FA second factor. |

### 1.4 References

Source-of-truth files referenced throughout:

- [CLAUDE.md](../CLAUDE.md) — repository conventions and deployment rules
- [config/settings/base.py](../config/settings/base.py) — all global configuration
- [config/urls.py](../config/urls.py) — URL composition root
- [apps/scripts/snippet.js](../apps/scripts/snippet.js) — the client-side collector
- [docs/guide/](guide/) — end-user documentation (9 chapters)
- [docs/deploy.md](deploy.md), [deploy.sh](../deploy.sh) — deployment procedure
- [docs/runbooks/key-rotation.md](runbooks/key-rotation.md) — vault key rotation

### 1.5 Document conventions

- Endpoint paths are given exactly as routed. `<pk>`/`<id>` are UUIDs unless stated.
- "MUST/MUST NOT" describes behaviour the code enforces; "does" describes observed
  behaviour without implying a hard guarantee.
- Every numeric threshold quoted here was read from the code, not inferred.

---

## 2. Overall description

### 2.1 Product perspective

Digivault sits **outside** the sites it watches and never has privileged access to
them by default. It learns about a site through four independent channels, which are
deliberately unequal in what they can see:

| Channel | Direction | Sees scripts | Sees forms | Sees JS errors | Trigger |
|---|---|---|---|---|---|
| Passive snippet (`/api/s.js`) | Site → Digivault | Yes | Yes | Yes | Real browser page loads |
| Server-side Scan | Digivault → site | Homepage only | No | No | User clicks "Scan" |
| Chrome extension | Browser → Digivault | Yes | No | No | Page has a `script[data-site]` tag |
| WordPress PHP snippet | Site → Digivault | — | — | — (PHP errors) | PHP error handler |

Because collection is **traffic-driven**, a site with no visitors reports nothing.
There is no crawler, so `robots.txt`, `noindex` and `nofollow` are irrelevant to
detection (they matter only to the separate SEO module, which reads them as data).

### 2.2 System context

```
                        ┌──────────────────────────────┐
   Client website ─────▶│  POST /api/ingest/           │
   (snippet.js)         │  POST /api/ingest/js-errors/  │
                        │  POST /api/ingest/form-errors/│
                        │  POST /api/ingest/form-submission/
   WP PHP snippet ─────▶│  POST /api/php-errors/        │
                        │  GET  /api/s.js               │
   Chrome extension ───▶│  /api/extension/*             │
                        │                              │
   Agency user ────────▶│  Next.js portal :3006 ──BFF──▶ /api/v1/*  (JWT)
                        │                              │
   Public visitor ─────▶│  /status/<slug>  ────────────▶ /api/v1/public/status/<slug>/
                        └──────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
   PostgreSQL 16                Redis 7                    Outbound calls
   (all state)          (cache, Celery broker,     WHOIS · DNS · SMTP · TLS
                         Channels layer, rate      PageSpeed · CrUX · WPScan
                         limits, pre-auth,         wordpress.org · ClickUp
                         device trust, handoff)    Slack · SMTP relay (Brevo)
```

### 2.3 User classes and characteristics

Roles live on `TeamMembership.role`. Privilege is ordered by
`RolePermission.ROLE_LEVELS` in [apps/common/permissions.py](../apps/common/permissions.py):

| Role | Level | Characteristics |
|---|---|---|
| `owner` | 4 | Created the team. Always has every feature; cannot be removed or role-changed. Owner membership is auto-created in `Team.save()`. |
| `manager` | 3 | Full operational control: invites, creates users, assigns websites, manages WP SSO secrets, sees the whole team's activity log and the Renewal Center. |
| `developer` | 2 | Day-to-day member. Can reveal credentials shared with them. Sees only assigned websites once any assignment exists. |
| `custom` | 2 | Same tier as developer, but visible app sections are limited to `TeamMembership.feature_access`. |
| `editor`, `seo` | 2 | Legacy member-level roles, no longer offered in the UI, kept valid for existing rows. |
| `viewer` | 1 | Read-only. **Cannot reveal credentials** — `CredentialService._REVEAL_ROLES` excludes it. |

Two non-team actors also exist: the **anonymous snippet** (authenticated only by
`site_id` plus origin binding) and the **public status page visitor** (no auth).

### 2.4 Operating environment

- **Production:** CloudPanel VPS. Backend as four containers (`api`, `celery`,
  `celery-beat`, plus `db` and `redis`) via
  `docker-compose.production.cloudpanel.yml`; the `api` entrypoint runs `migrate`
  and `collectstatic` then starts Daphne on `127.0.0.1:8000`. The frontend runs
  **on the host under pm2** (`digivault-frontend`, `next start`, `PORT=3006`).
  nginx routes `/api`, `/admin`, `/ws` → `:8000` and everything else → `:3006`.
- **Development:** `python manage.py runserver` + `npm run dev`, with
  `config.settings.development` substituting LocMem cache, the in-memory Channels
  layer, eager Celery, the console email backend and a 2FA bypass.
- **Tests:** `config.settings.test` inherits development, forces eager Celery and a
  memory result backend.

### 2.5 Design and implementation constraints

1. **Django 5.1 / DRF conventions** — models, serializers, viewsets, Celery tasks.
2. **Next.js 16 breaking changes** — `frontend/AGENTS.md` requires reading
   `node_modules/next/dist/docs/` before writing frontend code; APIs differ from
   older releases (`cookies()` is async, `proxy.ts` replaces middleware conventions).
3. **`output: "standalone"` is forbidden** in `frontend/next.config.ts` — Next 16
   refuses `next start` with standalone output and the frontend is host-pm2, not Docker.
4. **Ingest URLs are version-free** (`/api/ingest/`, `/api/s.js`) because they are
   baked into third-party HTML permanently and can never be renamed.
5. **New public endpoints must live under `/api/ingest`, `/api/v1`,
   `/api/php-errors` or `/api/extension`** — nginx proxies only those prefixes.
6. **Never deploy with bare `docker compose up`** — the default `docker-compose.yml`
   pins development settings; this drift once ran DEBUG in production for weeks.
7. **Vault keys live only in environment variables**, never in the database.
8. **Celery hard time limit is 300 s per task** (`CELERY_TASK_TIME_LIMIT`).

### 2.6 Assumptions and dependencies

- PostgreSQL and Redis are reachable; Redis loss disables login (pre-auth session),
  rate limiting, device trust, Celery and WebSockets.
- Outbound network access is available for WHOIS, DNS, SMTP probing, TLS handshakes
  and the Google/WPScan/ClickUp/Slack APIs. Every one of these is wrapped so a
  failure degrades a single field rather than failing the request.
- `EMAIL_URL` points at a real SMTP relay in production — `config/settings/production.py`
  **refuses to boot** on a blank or `consolemail://` value, because that default
  silently discarded onboarding and password-reset mail once before.
- The customer can paste a `<script>` tag into every page of their site.

---

## 3. System architecture

### 3.1 Django application layout

Fifteen local apps, registered in `LOCAL_APPS`:

| App | Responsibility |
|---|---|
| `apps.common` | Base model, envelope renderer, exception handler, pagination, team-scoping mixin/queryset, role permission, SSRF guard, heartbeat task |
| `apps.accounts` | `User`, `Team`, `TeamMembership`, `TeamInvitation`, `PasswordResetRequest`, feature-access presets, 2FA views |
| `apps.websites` | `Website`, `WebsiteAssignment`, health score, scan, snippet verification, WP SSO, platform detection, provisioning signals |
| `apps.scripts` | Snippet source, all four ingest endpoints, `Script`, `ScriptSnapshot`, `ScriptChange`, `DetectedForm`, `JsError`, `FormSubmissionError`, classifier, diff engine, normaliser, suspicion heuristics, dedup |
| `apps.credentials` | Fernet vault, `Credential`, `CredentialShare`, `CredentialAccessLog`, extension lookup/save, web handoff, LastPass-style import, key rotation command |
| `apps.domains` | `DomainInfo`, `DomainAlert`, WHOIS/hosting/SSL/SMTP/SPF/DKIM/DMARC checks, expiry alert delivery |
| `apps.alerts` | `AlertRule`, `AlertSuppression`, `Notification`, delivery backends, digests, WebSocket consumer |
| `apps.monitors` | `Monitor`, `MonitorCheck`, `MonitorUptimeRollup`, `NotificationChannel`, `MonitorNotificationRule`, checkers, dispatchers |
| `apps.performance` | `PerformanceReport`, `CruxReport`, PSI + CrUX clients, weekly trends, regression alerting |
| `apps.site_health` | `PhpError`, `SiteEvent`, `VulnerabilityReport`, `SiteScanState`, `SeoReport`, `SecurityHeaderReport`, SEO and header checkers |
| `apps.status_pages` | `StatusPage`, `StatusPageMonitor`, `StatusPageIncident`, `MaintenanceWindow`, public read endpoint |
| `apps.clients` | `Client`, CSV import/export, hosting mirroring, auto-website creation |
| `apps.reports` | `Report`, ReportLab PDF / CSV builder, monthly generation |
| `apps.audit` | `ActivityLog`, `AuditService`, filtered list + CSV export, purge |
| `apps.chat` | Regex-intent dashboard assistant |

### 3.2 Request paths

**Authenticated portal request.** Browser → Next.js page (server component) →
`getAccessToken()` reads the HttpOnly `ss_access` cookie → `api.get()` calls Django
with `Authorization: Bearer` → DRF authenticates via SimpleJWT → `TeamScopedMixin`
narrows the queryset to `request.user.active_team` → serializer → `EnvelopeJSONRenderer`.

Client components instead call a Next.js `/api/*` route handler, which reads the
cookie server-side and forwards. The browser therefore never holds a JWT.

**Ingest request.** Snippet `sendBeacon` → `POST /api/ingest/` (no auth) →
`Content-Length` ≤ 1 MB → serializer validation → `site_id` lookup → origin/referer
host must equal the registered domain → `process_ingest_payload.delay()` →
**202 Accepted**. All work happens in Celery so the endpoint stays under ~50 ms.

**WebSocket.** Browser → `/ws/alerts/` with the JWT as a `Sec-WebSocket-Protocol`
subprotocol → `AlertConsumer` validates and joins group `alerts_team_<team_id>` →
Celery's delivery task calls `push_notification()` → Redis channel layer → group
broadcast.

### 3.3 Deployment topology

```
                       nginx (CloudPanel, TLS)
                                │
        ┌───────────────────────┴──────────────────────┐
   /api, /admin, /ws                          everything else
        │                                              │
  127.0.0.1:8000                                127.0.0.1:3006
  Daphne (docker: api)                          next start (host pm2)
        │
   ┌────┴─────┬───────────────┬──────────────┐
   db         redis        celery         celery-beat
 (postgres  (broker,    (worker,        (scheduler,
   16)      cache,       --concurrency=2)  -s /tmp/celerybeat-schedule)
            channels)
```

Volumes: `postgres_data`, `static_files`, `media_files`. The `api` container is the
only one publishing a port, and only on loopback.

---

## 4. Cross-cutting mechanisms

### 4.1 Response envelope

Every DRF response is wrapped by `EnvelopeJSONRenderer`
([apps/common/renderers.py](../apps/common/renderers.py)):

```json
{ "data": <payload>, "errors": [], "meta": {} }
```

A view may set `response.meta` before returning to populate `meta`. Already-wrapped
payloads (from the exception handler) pass through untouched.

Errors go through `custom_exception_handler`
([apps/common/exceptions.py](../apps/common/exceptions.py)), which recursively
flattens DRF validation detail into a list:

```json
{ "data": null,
  "errors": [{ "code": "invalid", "message": "domain: This field is required." }],
  "meta": {} }
```

Typed domain errors subclass `AppError`: `NotFoundError` (404), `ForbiddenError`
(403), `ConflictError` (409).

**Two exceptions matter to callers.** The SimpleJWT token endpoints
(`/api/v1/auth/token/`, `/token/refresh/`) are not envelope-wrapped, so their tokens
sit at the top level. And in tests `response.data` is the *raw* payload — the
renderer only runs on rendered HTTP responses — so assertions read
`resp.data["access"]`, not `resp.data["data"]["access"]`.

### 4.2 Model base

`BaseModel` ([apps/common/models.py](../apps/common/models.py)) is abstract and
gives every model a UUID primary key, an indexed immutable `created_at`, an
auto-updated `updated_at`, and default ordering `-created_at`.

Five models deliberately do **not** inherit it and declare their own UUID pk plus
timestamps: `Monitor`, `MonitorCheck`, `MonitorUptimeRollup`, `NotificationChannel`,
`MonitorNotificationRule`, `PerformanceReport`, `CruxReport`, `StatusPage` and its
children. Consequences are real: `PerformanceReport` orders by `checked_at`,
`MonitorCheck` by `checked_at`, `CruxReport` by `fetched_at` — code that assumes
`created_at` on those models is wrong.

### 4.3 Multi-tenancy

Isolation is enforced in three layers:

1. **`TeamScopedQuerySet.for_team(team)`** — `.filter(team=team)`, overridden on
   `Script` to traverse `website__team`.
2. **`TeamScopedMixin.get_queryset()`** — calls `.for_team(request.user.active_team)`
   on every request; returns `.none()` when the user has no active team.
3. **`IsTeamMember` permission** — verifies a `TeamMembership` row exists for the
   `team_pk` URL kwarg, or that `active_team` is set.

Views that do not use the mixin filter explicitly (e.g. `website__team=team`).

A fourth, narrower layer applies to websites only: `_restrict_to_assignments()` in
[apps/websites/views.py](../apps/websites/views.py). Once a non-manager has at least
one `WebsiteAssignment` in the team, their website queryset is restricted to those
IDs — enforced server-side, not merely hidden. A member with no assignments still
sees the whole team (backwards-compatible default), and owners/managers always do.

### 4.4 Pagination

`StandardPagination` — `page_size=25`, `?page_size=` up to 100. Paginator metadata
goes into the envelope's `meta` as `{count, next, previous}`, and
`get_paginated_response_schema` returns the schema unchanged so the envelope isn't
double-wrapped.

This shape is a trap the frontend has already hit: `api.get()` returns only the
first 25 rows. `api.getAll()` exists for exactly this reason — it requests
`page_size=100` and follows `meta.next` (max 50 iterations), stripping the origin
from the absolute `next` URL so `API_BASE` still applies.

### 4.5 Throttling

`AnonRateThrottle` + `UserRateThrottle` are the defaults. Configured scopes:

| Scope | Configured rate | Env var | Applies to |
|---|---|---|---|
| `anon` | 1000/hour | `THROTTLE_ANON` | Unauthenticated requests |
| `user` | 10000/day | `THROTTLE_USER` | Authenticated requests |
| `auth` | 120/minute | `THROTTLE_AUTH` | Login, token refresh |
| `ingest` | 10000/day (setting) | `THROTTLE_INGEST` | Ingest endpoints |
| `extension` | 300/hour | `THROTTLE_EXTENSION` | Extension lookup |
| `totp_verify` | 10/minute | — | 2FA code verification |
| `totp_setup` | 10/hour | — | 2FA enrolment |

`anon` is deliberately generous because the Next.js server proxies login and refresh,
so Django sees one shared IP for all users; brute-force protection is the separate
tight `auth` scope instead.

`IngestThrottle` overrides `get_cache_key()` to bucket **per `site_id`**, so one
busy site cannot starve others behind the same IP. Note that it also hardcodes
`rate = "2000/day"`, which takes precedence over the `ingest` setting — see §16.

### 4.6 SSRF protection

Any endpoint that fetches a user-supplied URL calls `assert_public_url()`
([apps/common/ssrf.py](../apps/common/ssrf.py)) first. It requires `http`/`https`,
resolves **every** A/AAAA record for the host, and raises `BlockedURLError` if any
address is private, loopback, link-local (169.254/16 — cloud metadata), reserved,
multicast or unspecified. Unparseable addresses are refused rather than allowed.

Guarded call sites: `websites` `scan` and `verify-snippet` actions,
`site_health.seo_checker.fetch` (and therefore the SEO and security-header checks).

### 4.7 Audit logging

`AuditService.log_request(request, action, …)`
([apps/audit/services.py](../apps/audit/services.py)) extracts actor, active team
and client IP (`X-Forwarded-For` first hop, else `REMOTE_ADDR`) and writes an
`ActivityLog` row. All failures are caught and logged — **an audit write must never
crash the caller**. Rows are never updated or deleted by application code; a weekly
task purges them at 90 days.

`site_meta(obj, **extra)` is a helper that stamps `metadata["website_id"]` onto
site-scoped actions whose primary resource is a sub-object (a report, a monitor, a
credential). Without it the Activity Log's Website column and its `?website_id=`
filter both come up empty.

### 4.8 Content Security Policy and HTTP hardening

`django-csp` runs second in the middleware stack. Base policy: `default-src 'self'`,
`script-src 'self'`, `style-src 'self' 'unsafe-inline'` (Tailwind needs inline
styles), `img-src 'self' data: https:`, `font-src 'self' data:`,
`connect-src 'self'`, `frame-ancestors 'none'`, `base-uri 'none'`,
`form-action 'self'`. `CSP_REPORT_ONLY` is `True` in base, **enforced** in
production, and the middleware is removed entirely in development.

Production also sets `SECURE_PROXY_SSL_HEADER`, HSTS for one year with
`includeSubDomains` and `preload`, `SECURE_CONTENT_TYPE_NOSNIFF`, secure session and
CSRF cookies, and `X_FRAME_OPTIONS = "DENY"`. `SECURE_SSL_REDIRECT` is deliberately
`False` because nginx already enforces HTTPS and internal HTTP calls from Next.js
must not be redirected. `CORS_ALLOWED_ORIGINS` is asserted to contain no
`http://localhost` origin.

### 4.9 Observability

Console logging at `LOG_LEVEL` (default INFO) with a verbose formatter; `django`,
`celery` and `apps` loggers configured explicitly. Sentry initialises only when
`SENTRY_DSN` is set, behind a guarded import, with `send_default_pii=False`.

A dead-man's-switch task `common.system_heartbeat` runs every 5 minutes and pings
`HEARTBEAT_PING_URL` if configured; when beat or the workers stall, the external
service stops receiving pings and alerts. It is a no-op when the URL is blank.

---

## 5. Accounts, teams, roles and feature access

### 5.1 Data model

**`User`** (`AUTH_USER_MODEL`, extends `AbstractUser`) — UUID pk, unique `email` as
`USERNAME_FIELD`, `username` retained for Django internals but never shown,
`profile_photo`, `timezone` (default UTC), `active_team` FK (`SET_NULL`, nullable
because a fresh registrant has no team), `totp_secret` (BinaryField, encrypted),
`totp_enabled`, `totp_backup_codes` (JSON list of SHA-256 hashes),
`must_change_password`. Ordered by email.

**`Team`** — `name`, unique auto-generated `slug` (collision-suffixed in
`_generate_unique_slug`), `owner` FK (`PROTECT`), `plan` (`starter` / `agency` /
`agency_pro` / `enterprise`), and `_clickup_api_token` as an encrypted BinaryField
exposed through a `clickup_api_token` property that returns `""` on any decryption
failure. `Team.save()` always `get_or_create`s an owner-level `TeamMembership`.

**`TeamMembership`** — unique `(user, team)`, `role`, and `feature_access` (JSON list
of feature keys, meaningful only when `role == "custom"`).

**`TeamInvitation`** — unique `(team, email)`, `role`, a `secrets.token_urlsafe(48)`
token minted in `save()`, `accepted`, `accepted_at`, `expires_at`.

**`PasswordResetRequest`** — `user`, `status` (pending/approved/rejected/used),
unique `reset_token`, `approved_by`, `approved_at`, `expires_at`.

### 5.2 Feature access

[apps/accounts/features.py](../apps/accounts/features.py) defines six gateable
sections: `websites`, `clients`, `alerts`, `renewals`, `credentials`,
`activity_log`. Monitors, Status Pages and Reports are **not** gateable because they
were folded into website detail tabs.

`ROLE_DEFAULT_FEATURES` seeds a preset a manager can then fine-tune per member:
owner and manager get all six; developer, viewer, editor and seo get all except
`renewals` (the Renewal Center is manager-only); `custom` starts empty.

`effective_features(role, feature_access)` returns all six for owners, the stored
list when set, and otherwise the role default (covering legacy rows with an empty
list). The sidebar consumes this via `Team.my_features`.

### 5.3 Team endpoints

| Method | Path | Behaviour |
|---|---|---|
| GET/POST | `/api/v1/auth/teams/` | List teams the user belongs to (with `my_role`, `my_features`, `member_count`); create a team via `TeamService.create`, which also sets it as the creator's active team |
| GET/PATCH | `/api/v1/auth/teams/<pk>/` | Read/rename; a rename writes `SETTINGS_TEAM_NAME_CHANGED` |
| GET | `/api/v1/auth/teams/<team_pk>/members/` | Members with role, `feature_access`, `effective_features`, `totp_enabled` |
| PATCH/DELETE | `/api/v1/auth/teams/<team_pk>/members/<pk>/` | Change role / feature access, or remove. Owner is immutable and unremovable |
| POST | `/api/v1/auth/teams/<pk>/switch/` | Set `active_team` |
| POST | `/api/v1/auth/teams/<team_pk>/invite/` | Email invitation |
| POST | `/api/v1/auth/teams/<team_pk>/users/` | Manager creates a user directly with a temporary password |
| GET | `/api/v1/auth/teams/<team_pk>/invitations/` | Pending invitations |
| DELETE | `/api/v1/auth/teams/<team_pk>/invitations/<pk>/` | Revoke |
| GET/PATCH | `/api/v1/auth/teams/<pk>/settings/` | Team integration settings (ClickUp token) |
| POST | `/api/v1/auth/teams/<pk>/settings/clickup-test/` | Verify the stored ClickUp token works |

`TeamService` ([apps/accounts/services.py](../apps/accounts/services.py)) owns the
invariants, each inside `transaction.atomic`: adding an existing member raises
`ConflictError`; removing the owner raises `ForbiddenError`; changing the owner's
role raises `ForbiddenError`; operating on a non-member raises `NotFoundError`.

`InvitationService.accept()` selects the invitation `FOR UPDATE`, refuses if the
email does not match the accepting user, adds the membership, marks the invitation
accepted, and sets `active_team` if the user had none.

---

## 6. Authentication, 2FA and onboarding

### 6.1 Token model

SimpleJWT, HS256, `Bearer`. Access token 15 minutes
(`JWT_ACCESS_TOKEN_LIFETIME_MINUTES`), refresh 7 days
(`JWT_REFRESH_TOKEN_LIFETIME_DAYS`), `ROTATE_REFRESH_TOKENS=True`,
`BLACKLIST_AFTER_ROTATION=True`, `UPDATE_LAST_LOGIN=True`.

Tokens are held **only** in HttpOnly cookies set by the Next.js BFF —
`ss_access` (maxAge 5 min), `ss_refresh` (7 days), `ss_2fa_device` (10 h). The
browser cannot read them.

### 6.2 Login flow

`POST /api/v1/auth/login/` ([apps/accounts/totp_views.py](../apps/accounts/totp_views.py))
returns one of five shapes. 2FA is **mandatory** — there is no way to hold an
account without it in production.

```
POST /api/v1/auth/login/  {email, password}
        │
        ├─ authenticate() fails ──▶ 401 + AUTH_LOGIN_FAILED audit row
        │
        ├─ settings.ALLOW_2FA_BYPASS (development only) ──▶ {access, refresh}
        │
        ├─ store preauth:<session_key> in Redis for 300 s
        │
        ├─ user.must_change_password ──▶ {requires_password_change, session_key}
        │
        ├─ user.totp_enabled
        │     ├─ X-2FA-Device-Token matches device_trust:<token>
        │     │     ──▶ rotate device token, {access, refresh, device_trust_token}
        │     └─ else ──▶ {requires_2fa: true, session_key}
        │
        └─ else ──▶ {requires_setup: true, session_key}
```

`POST /api/v1/auth/2fa/verify/` exchanges `session_key` + `code` for tokens. It
tries the **backup code first** (SHA-256 hash lookup, consumed on use), then the
TOTP with `valid_window=1` (±30 s). Success deletes the pre-auth key, mints a fresh
10-hour device-trust token and writes an `AUTH_LOGIN` row.

`POST /api/v1/auth/first-password/` handles the admin-created-user case: it accepts
the pre-auth `session_key`, runs Django's password validators, clears
`must_change_password`, and **refreshes the pre-auth TTL** so the caller can continue
straight into mandatory 2FA setup without a second login.

### 6.3 2FA enrolment

`PreAuthSessionAuthentication` is a custom DRF authenticator that accepts an
`X-Pre-Auth-Key` header resolved against `preauth:<key>` in Redis. It lets a user who
has passed email+password but not yet enrolled request their QR code without a JWT.

- `GET /api/v1/auth/2fa/setup/` — mints a `pyotp.random_base32()` secret, builds the
  `otpauth://` provisioning URI (issuer `Digivault`), renders a PNG QR as a base64
  data URI, and caches the pending secret under `totp_pending:<user_pk>` for 600 s.
  2FA is **not** yet enabled.
- `POST /api/v1/auth/2fa/confirm/` — verifies the code against the pending secret,
  encrypts and persists the secret, sets `totp_enabled=True`, generates **8 backup
  codes** (`secrets.token_hex(4).upper()`), stores their hashes and returns the
  plaintext **once**. If the caller authenticated via pre-auth key, it also issues
  JWTs and a device-trust token so enrolment lands on the dashboard directly.
- `POST /api/v1/auth/2fa/disable/` — self-service, or a manager/owner disabling for
  another user via `user_id`. Clears secret, flag and backup codes.
- `POST /api/v1/auth/2fa/regenerate-backup/` — replaces all 8 codes.
- `GET /api/v1/auth/2fa/status/` — `{totp_enabled, backup_codes_count}`.

The TOTP secret is encrypted at rest with the **same Fernet key as the credential
vault** (`apps.credentials.encryption`).

### 6.4 Admin-gated password reset

Digivault does not self-serve password resets; a human approves each one.

1. `POST /api/v1/auth/password-reset/` (public) — user submits an email. A
   `PasswordResetRequest` is created `PENDING`. The response does not reveal whether
   the address exists.
2. `GET /api/v1/auth/password-reset/` (manager) — lists pending requests.
3. `POST /api/v1/auth/password-reset/<pk>/approve/` — mints a `reset_token`, sets
   `APPROVED` with an expiry, and emails the link.
4. `POST /api/v1/auth/password-reset/<pk>/reject/` — sets `REJECTED`.
5. `POST /api/v1/auth/password-reset/confirm/` — user posts token + new password;
   validators run, the password is set, the request becomes `USED`.

### 6.5 Manager-created users

`POST /api/v1/auth/teams/<team_pk>/users/` creates a user, adds the membership with
a role and seeded `feature_access`, and sends onboarding mail. Two helpers matter:
`_issue_set_password_link()` creates an already-APPROVED reset token so the invitee
sets their own password, and `_send_account_email()` returns a boolean so the API can
tell the manager the mail failed instead of silently succeeding.

### 6.6 Extension web handoff

The extension holds its own JWT (from `/api/extension/token/`). To make the portal
log in as the same user without exposing the token to page JS:

1. Extension `POST /api/extension/web-handoff/` with its JWT → a one-time
   `uuid4().hex` code, cached under `ext_handoff:<code>` for **60 s** with a fresh
   access/refresh pair.
2. The portal page `/auth/extension?code=…` calls
   `GET /api/extension/exchange/?code=…` (unauthenticated — the code *is* the
   credential, rate-limited by `HandoffExchangeThrottle`). The cache key is
   **deleted immediately**, so replay is impossible.
3. The Next.js route sets the same HttpOnly cookies as a normal login.

`ExtensionAuthBridge` (mounted in the dashboard layout) `postMessage`s auth state to
the extension so the two stay in sync on logout.

---

## 7. Clients

### 7.1 Purpose and model

`Client` ([apps/clients/models.py](../apps/clients/models.py)) is the commercial
record behind zero or more Websites. It is **soft-deleted only** — status moves to
`offboarded`, rows are never hard-deleted.

| Field group | Fields |
|---|---|
| Identity | `name` (indexed), `website_url` (indexed), `status` (active/paused/offboarded), `tier` (gold/silver/bronze/none) |
| Hosting | `hosting_platform` (WPEngine, SiteGround, Cloudways, Bluehost, GoDaddy, Squarespace, Wix, Shopify, other, unknown), `hosting_platform_other` free text, `hosting_renewal_date`, `domain_renewal_date`, `domain_access_location` |
| Access | `website_access_level` — `full_admin`, `delegate`, `none`, `not_working`, unknown. `not_working` is deliberately distinct from `none`: credentials exist but don't get us in |
| Work | `departments` (JSON subset of `seo`, `ads`, `dev`, `content`, `lead_insight`, `social_media`), `running_ppc_ads`, `website_built_by_digi`, `website_maintained_by_digi`, `notes` |
| Notifications | `notify_desktop`, `notify_email` |
| Commercial | `assigned_to` FK, `monthly_revenue` (decimal 10,2) |

`DEPARTMENTS` is a plain tuple on the model, so adding a department needs no
migration — it widens the serializer's `ChoiceField` and the CSV importer together.
A `domain` property strips scheme, `www.` and trailing slash from `website_url`.

### 7.2 Endpoints

| Method | Path | Behaviour |
|---|---|---|
| GET/POST | `/api/v1/clients/` | List (team-scoped, department-filtered) / create |
| GET | `/api/v1/clients/search/` | Typeahead search |
| POST | `/api/v1/clients/import/` | CSV import with lenient parsing |
| GET | `/api/v1/clients/export/` | CSV export |
| GET/PATCH | `/api/v1/clients/<pk>/` | Read / update |
| POST | `/api/v1/clients/<pk>/activate/` | Status → active |
| POST | `/api/v1/clients/<pk>/deactivate/` | Status → offboarded |

### 7.3 Import parsing

The importer is deliberately forgiving because the source is a hand-maintained
spreadsheet. Dedicated `_parse_*` helpers normalise hosting platform, status, tier,
access level, departments (comma/slash separated), dates (multiple formats) and
booleans with a default. Anything unrecognised falls back to the model's "unknown"
sentinel rather than rejecting the row.

### 7.4 Side effects on save

Two behaviours make the Client record propagate rather than sit inert:

**`_sync_hosting_to_websites(client)`** mirrors `hosting_renewal_date` onto
`DomainInfo.hosting_expires_at` for every Website matched by the `client` FK *or* by
an exact same-team domain match. Hosting renewal is not discoverable via WHOIS or
DNS, so this is the only path by which it reaches the Access & Domain tab and the
expiry alerts. It only ever **writes** a date — it never clears one a user set on the
website.

**`_auto_create_website(client, request)`** attaches a Website to a newly added
client. It matches case-insensitively within the team, so re-importing never
duplicates a site. An existing site with **no** client is adopted (this is what makes
"wipe the clients and re-import" reattach sites, since `Website.client` is
`SET_NULL`). A site already owned by a **different** client is left alone — an import
must never silently move a website between clients. Creating one triggers the full
`post_save` provisioning chain in §8.6.

---

## 8. Websites

### 8.1 Model

`Website` ([apps/websites/models.py](../apps/websites/models.py)):

| Field | Notes |
|---|---|
| `team` | CASCADE — tenant owner |
| `client` | SET_NULL — optional commercial owner |
| `name`, `domain` | `domain` indexed |
| `platform` | wordpress / webflow / wix / framer / shopify / squarespace / custom / other |
| `site_id` | `secrets.token_urlsafe(32)` (43 chars), unique, indexed. Embedded in public HTML — an **identifier, not a secret**; rate limiting and origin binding protect it |
| `status` | active / inactive / warning / critical |
| `notes`, `tags` | Free text, JSON list |
| `last_seen_at` | Last ingest — the reporting heartbeat |
| `health_score` | 0–100, default 100 |
| `is_vip` | Per-**site**, not per-client: a client often has one site that matters and several that don't |
| `seo_scan_interval_days` | 0 (off) / 1 / 3 / 7 / 14 / 30 |
| `notification_channel` | One channel for all this site's alerts; falls back to the team's active channels |
| `uptime_notification_channel` | Downtime routes separately; falls back to `notification_channel` then team defaults |
| `wp_sso_secret` | Shared HMAC secret for one-click wp-admin login; empty = not set up |

Indexes: `(team, status)`, `(team, is_vip)`, `(domain)`. Ordered by name.

`WebsiteAssignment` — unique `(website, user)` plus `assigned_by`. Its enforcement
consequence is described in §4.3.

### 8.2 Snippet properties

- `snippet_html` — `<script async src="{SNIPPET_CDN_URL}/s.js" data-site="{site_id}"></script>`.
  In production `SNIPPET_CDN_URL` **must** be `https://digivault.digilatics.co/api`;
  `cdn.digivault.digilatics.co` has no DNS or vhost, and nginx only proxies `/api/…`.
- `snippet_instructions` — platform-specific installation copy for WordPress
  (WPCode/Code Snippets → Footer), Webflow, Wix, Framer, Shopify and Squarespace,
  with a generic "before `</body>` on every page" fallback.
- `wp_sso_snippet` — the PHP snippet with this site's secret baked in, pasted into
  the same WPCode tool as the tracking script. No plugin install required.

`regenerate_site_id()` mints a new token, invalidating every deployed snippet
immediately.

### 8.3 Health score

`recalculate_health_score()` is the **single writer of both `health_score` and
`status`**. The two answer different questions and both are kept: the score is
cumulative "how healthy overall"; status is "how urgent is the worst open issue".

Status is **not** a pure function of the score. A single unacknowledged
high-severity script change costs only 10 points but is precisely what the product
exists to catch, so it must still read critical. Conversely a low score forces at
least the matching status, so a badge can never say "active" beside a score of 42.

**Deductions** (start at 100):

| Input | Deduction | Cap | Urgency flag |
|---|---|---|---|
| Unacknowledged `critical` script changes | 15 each | 30 | urgent |
| Unacknowledged `high` | 10 each | 30 | urgent |
| Unacknowledged `medium` | 3 each | 15 | warn |
| Unacknowledged `low` | 1 each | 5 | — |
| Domain expires ≤ 7 d / ≤ 30 d | 20 / 8 | — | urgent / warn |
| SSL expires ≤ 7 d / ≤ 14 d / ≤ 30 d | 20 / 12 / 5 | — | urgent / warn / warn |
| Hosting expires ≤ 7 d / ≤ 30 d | 20 / 8 | — | urgent / warn |
| `critical` vulnerabilities | 8 each | 16 | — |
| `high` vulnerabilities | 4 each | 8 | — |
| Unreviewed active scripts (pending) | 2 each | 10 | — |
| Any monitor `down` | 30 | — | urgent |
| Any monitor `degraded` (none down) | 12 | — | warn |
| Worst `uptime_30d` < 95% / < 99% | 15 / 5 | — | — |
| Form submission errors in last 7 days | 6 each | 18 | warn |
| `last_seen_at` older than 30 d / 7 d | 20 / 10 | — | warn |

Then `score = clamp(100 - deductions, 0, 100)`.

**Status derivation:** `critical` if any urgency flag or `score < 60`; `warning` if
any warn flag or `score < 85`; otherwise `active`. `inactive` is a lifecycle state a
human chose and health **never** overwrites it — only the score is refreshed.

Three details carry hard-won intent:

- **Digivault's own infra is excluded.** `_internal_hosts()` returns
  `digivault.digilatics.co`, `cdn.digivault.digilatics.co`,
  `digilaticsvps.digilatics.co` plus the configured `SNIPPET_CDN_URL` host. The
  tracking snippet is itself a script on the page; its changes are hidden from the
  UI and can never be acknowledged, so counting them would pin every site to
  critical forever.
- **Form errors are bounded to 7 days** so a fixed form earns its score back rather
  than being punished by history.
- **Sites that have never reported are exempt** from the reporting-gap deduction — a
  newly added site has no traffic yet, which is not a fault.

**Recalculation triggers:** every ingest; acknowledging a change (single or bulk);
reviewing a script (single or bulk); a monitor status *flip* (not every 30-second
check); after a domain check; after a security scan; on `retrieve()` of a single
website; and the nightly `websites.recalculate_all_health` sweep at 06:30 UTC.

`list()` deliberately does **not** recalculate. It used to, costing ~8 queries and a
write per site — 1.03 s for 13 sites, on the critical path of every page load and
every filter change, growing linearly. The nightly sweep exists specifically because
several deductions are functions of elapsed time (expiry windows, reporting gap) and
event triggers never fire for a site that has simply gone quiet.

### 8.4 Website endpoints

`WebsiteViewSet` is a `ModelViewSet` at `/api/v1/websites/` with `TeamScopedMixin`.
`get_queryset()` annotates `script_count` and `unknown_script_count` — both excluding
internal hosts, and `unknown_script_count` counting only `provider="unknown"` **and**
`review_status="pending"`, so approving or ignoring a script clears it and the
dashboard KPI matches the detail page.

| Method | Path | Behaviour |
|---|---|---|
| GET/POST | `/api/v1/websites/` | List with annotations / create (audited) |
| GET | `/api/v1/websites/<pk>/` | Retrieve; **self-heals** health/status first, then re-reads with annotations |
| PATCH/DELETE | `/api/v1/websites/<pk>/` | Update / delete, both audited |
| GET | `/api/v1/websites/<pk>/health/` | Aggregated Health Center snapshot |
| GET | `/api/v1/websites/<pk>/snippet/` | Snippet HTML + platform instructions |
| POST | `/api/v1/websites/<pk>/regenerate-snippet/` | New `site_id` |
| GET/POST | `/api/v1/websites/<pk>/scan/` | Read scan state / trigger a scan |
| POST | `/api/v1/websites/<pk>/verify-snippet/` | Confirm the tag is live |
| GET/PUT | `/api/v1/websites/<pk>/assignments/` | Read / replace assignment set (managers only) |
| POST | `/api/v1/websites/<pk>/wp-sso-secret/` | Generate or rotate the WP SSO secret (managers only) |
| POST | `/api/v1/websites/<pk>/wp-login/` | Issue a signed 2-minute wp-admin login URL |
| GET | `/api/v1/websites/expiring-domains/?days=30` | Domain expiry list |
| GET | `/api/v1/websites/expiring-ssl/?days=14` | SSL expiry list |
| GET | `/api/v1/websites/expiring-hosting/?days=30` | Hosting expiry list |
| GET | `/api/v1/websites/fleet-summary/` | Team-wide SEO / performance / security / vulnerability / tracking roll-up |

### 8.5 Scan, verify and platform detection

**`POST …/scan/`** fetches only the **homepage**, server-side:

1. `assert_public_url()` on the bare URL.
2. Fetch with a random `_dvv=` cache-buster, browser-like headers, `no-cache`,
   20 s timeout, redirects followed. The cache-buster is stripped from the stored URL.
3. `detect_platform(html, headers)` runs first, so `platform` is set even for pages
   with no external scripts. It prefers `<meta name="generator">`, then
   platform-specific response headers (`x-shopid`, `x-wix-request-id`,
   `x-served-by-squarespace`), then HTML markers (`/wp-content/`, `data-wf-page`,
   `framerusercontent.com`, `cdn.shopify.com`, …), falling back to `other`.
4. `_extract_script_urls(html)` finds scripts that a naive `src=` regex would miss:
   static `<script src>`, GTM container IDs, GA4 `gtag/js` URLs and bare `G-` IDs
   from `gtag('config', …)`, the Meta Pixel loader, Hotjar reconstructed from
   `hjid`/`hjsv`, Microsoft Clarity's tag ID from its IIFE, HubSpot's
   `hs-scripts.com/<id>`, and any quoted `https://…​.js` literal inside inline script.
5. The extracted list is handed to `process_ingest_payload.delay()` with
   `snippet_version="server-scan"`, `SiteScanState.scan_status` is set to `running`,
   and `run_security_scan` + `run_seo_check` are queued with a 5-second countdown.

**Scan sees scripts only — never forms.** Only the passive snippet detects forms.

**`POST …/verify-snippet/`** fetches the homepage with a cache-buster and searches
for the literal `data-site="<site_id>"`. On failure it reports how many bytes of HTML
it checked, which distinguishes "tag missing" from "page didn't load".

### 8.6 Provisioning on creation

`post_save` on `Website` ([apps/websites/signals.py](../apps/websites/signals.py))
does synchronous DB-only work then defers all network I/O:

1. `_create_uptime_monitor_db_only()` — `get_or_create` an HTTP `Monitor` keyed
   `(team, url)` with a 300 s interval, 30 s timeout and `retry_count=1`, and links
   `monitor.website`.
2. `_create_status_page()` — creates a public `StatusPage` slugged from the domain
   and adds the monitor. **Idempotent per team + domain**: it looks for an existing
   page whose slug is the base slug *or* any `-N` collision variant and reuses it,
   which stops duplicate pages when a site is re-added or exists as multiple
   `Website` rows for one domain. The `-N` suffix loop only guards the model's
   global slug uniqueness across teams.
3. `run_initial_checks.delay()` — one uptime check, one domain check
   (`_persist_domain_check`) and one mobile PageSpeed run, each individually
   try/except'd so one failure doesn't lose the others.

### 8.7 WordPress one-click login

`POST …/wp-sso-secret/` (managers/owners only) mints `secrets.token_urlsafe(32)`,
writes it with `.update()` and returns the secret plus the ready-to-paste PHP
snippet. Rotating invalidates every previously issued link.

`POST …/wp-login/` maps the caller's Digivault role to a WordPress role —
`owner`/`manager` → `administrator`, `developer` → `editor`, anything else → 403 —
then builds a payload `{email, name, role, exp: now+120, jti: uuid4}`,
base64url-encodes it, HMAC-SHA256-signs it with the site secret, and returns

```
https://<domain>/wp-json/digivault/v1/sso?p=<payload_b64>&s=<hex_sig>
```

The link is single-use (`jti`) and expires in **120 seconds**. Both actions are
audited (`WEBSITE_WP_SSO_SECRET_ROTATED`, `WEBSITE_WP_LOGIN` with the mapped role).

### 8.8 Health Center snapshot

`build_health_snapshot(website)` ([apps/websites/health.py](../apps/websites/health.py))
is read-only and returns active script count, pending changes, high-risk pending
count, registrar/hosting/domain-days/SSL-days, latest mobile and desktop performance
scores, vulnerability counts by severity, PHP errors in 30 days, and a **separate
security sub-score**.

`_security_score()` is deliberately steeper on vulnerabilities than overall health
(25/critical capped 50, 10/high capped 30, 3/medium capped 15, plus PHP errors capped
10). That is not a disagreement: overall health caps vulnerability deductions low
because they are one of eight inputs, whereas this score has three and needs the
range to stay meaningful. The **SSL window was reconciled** — it now uses the same
7/14/30 → 20/12/5 tiers as overall health, because it previously deducted a flat 15
inside 14 days and produced contradictory readings for one certificate.

### 8.9 Fleet summary

`GET /api/v1/websites/fleet-summary/` is one aggregate call per area rather than per
website — the dashboard needs all four for every site, and fanning out would be
4 × N requests. It **only reads stored scan results and never triggers a scan**.

- **SEO** — count checked, indexable, blocked (`robots_blocks_all` OR
  `homepage_indexable=False`), summed `noindex_count`.
- **Performance** — the newest run per `(site, strategy)`, then averages, plus
  Lighthouse's own bands (`<50` poor, `90+` good) for mobile.
- **Security headers** — count checked, average score, grade histogram, and
  `failing` = grades starting C/D/F.
- **Vulnerabilities** — counts by severity plus distinct sites affected.
- **Tracking coverage** — distinct sites carrying analytics or tag management
  (`missing_analytics` is the complement — "a site with no measurement is invisible
  to the client's reporting"), tag manager, advertising, call tracking, unknown
  scripts, and suspicious sites/scripts.

---

## 9. Script ingest pipeline

### 9.1 The snippet

[apps/scripts/snippet.js](../apps/scripts/snippet.js) — version `1.6`, ~450 lines of
ES5, served by `SnippetJsView` at `GET /api/s.js` with
`Cache-Control: public, max-age=300` and `Access-Control-Allow-Origin: *`.

It reads `data-site` from its own `<script>` tag and derives the ingest URL by
replacing `/s.js…` with `/ingest/`, falling back to
`window.location.origin + '/api/ingest/'`. Every sub-endpoint is derived from that
one base. Transport is `navigator.sendBeacon` with an `XMLHttpRequest` fallback.

**Collection:** `collectScripts()` walks every `<script>` with a `src`, dedupes,
skips `/wp-includes/` and `/wp-admin/` (WordPress core), and records location
(`head` / `body` / `unknown` by DOM containment) plus `async` and `defer`.

**Firing schedule:**

| Trigger | Delay |
|---|---|
| `DOMContentLoaded` (or immediately if already interactive/complete) | 0 |
| Unconditional second pass — catches JS-framework content | 2500 ms |
| `elementor/popup/show` | 300 ms |
| `shown.bs.modal`, `dialogopen` | 300 ms |
| `MutationObserver` sees a new `<script src>` or `<form>` (or a subtree containing one) | 400 ms debounce |

The observer watches `document.documentElement` with `childList` + `subtree` and
**disconnects after 30 s** to avoid overhead on long-lived pages.

Everything in the error-reporting paths is wrapped in `try/catch` so a failure in
Digivault's reporter can never break the host page.

### 9.2 URL normalisation

[apps/scripts/normalize.py](../apps/scripts/normalize.py) exists because WordPress
and page builders append volatile cache-busters. Diffing raw URLs minted a new
`Script` row and a fake change event on **every plugin update**.

`normalize_script_url()` drops the fragment, lowercases scheme and host, removes
volatile params (`ver`, `version`, `nonce`, `cb`, `cachebust`, `cache`, `bust`,
`rev`, `build`, `t`, `ts`, `time`, `timestamp`, `_`, `rand`, `random`) plus any value
matching `^[0-9a-f]{16,}$` regardless of key, then sorts what survives. Meaningful
identifiers (`?id=GTM-XXX`, `?id=AW-XXX`, `?render=sitekey`) are preserved as part of
identity. Non-absolute inputs are returned unchanged.

`normalize_page_url()` reduces a page to scheme + host + path: querystrings (UTM
tags, click IDs), fragments, `www.` and trailing slashes all vary per visit without
changing which page it is. So `/contact`, `/contact/` and `/contact?utm=x` are one page.

### 9.3 Noise filter

`_should_track_script(src, website_domain)`
([apps/scripts/tasks.py](../apps/scripts/tasks.py)) returns `False` for:

1. Relative URLs (always self-hosted).
2. Digivault's own infra hosts (`_internal_hosts()`).
3. The site's own domain or any subdomain of it.
4. Known utility CDNs: `cdnjs.cloudflare.com`, `cdn.jsdelivr.net`, `unpkg.com`,
   `code.jquery.com`, `maxcdn.bootstrapcdn.com`, `stackpath.bootstrapcdn.com`,
   `ajax.googleapis.com`, `ajax.aspnetcdn.com`, plus the review/widget platforms
   `cdn.trustindex.io`, `cdn.elfsight.com`, `apps.elfsight.com`, `elfsight-cdn.com`.
5. Utility filename patterns (jQuery, Bootstrap, slick, webpack, `.chunk.`, runtime,
   vendor, lodash, underscore, modernizr, popper, magnific, shims, FontAwesome,
   lazysizes, Swiper, Owl Carousel, `/utils.`) — **only when the classifier already
   returned `unknown`**, so a real but unrecognised analytics script is never dropped.

The task additionally skips any `src` containing `/wp-includes/` or `/wp-admin/`.

### 9.4 Classifier

[apps/scripts/classifier.py](../apps/scripts/classifier.py) holds **358 ordered
regex entries covering ~300 named providers**, most-specific first so broad CDN
patterns cannot shadow specific ones. First match wins; no match yields
`provider="unknown", category="unknown", is_known=False`.

Thirteen categories: `analytics`, `advertising`, `tag_management`,
`session_recording`, `call_tracking`, `chat`, `crm`, `payment`, `seo`, `security`,
`performance`, `social`, `unknown`.

Eight providers are **critical** — their removal is always high severity: Google
Analytics 4, Google Universal Analytics, Google Tag Manager, Meta Pixel,
WhatConverts, CallRail, Stripe, PayPal.

### 9.5 Diff engine

[apps/scripts/diff_engine.py](../apps/scripts/diff_engine.py) is pure — no DB, no
network. `DiffEngine.diff(previous, current)` keys both lists on **normalised** URLs
and returns `ChangeResult` dataclasses.

**URL_CHANGED collapsing** runs first. A version swap would otherwise produce a
scary Added + Removed pair. Removed and added URLs are grouped by a
`_group_key`: known scripts group by **provider** (so a GTM container-ID swap is one
event), unknown third-party scripts group by **host** (so self-updating widgets that
version their filenames stop producing churn). Only an exact 1-to-1 swap within a
group collapses. Severity is `high` for critical providers, otherwise `medium`;
description is `"<Provider> URL changed"` or `"Script updated on <host>"`.

Remaining events:

| Type | Condition | Severity |
|---|---|---|
| `removed` | Was present, now absent | `high` if critical provider, else `medium` |
| `added` | Newly present, **unknown** provider | `high` — `"Unknown script detected: …"` |
| `added` | Newly present, known provider | `medium` |
| `moved` | Same URL, `location` differs | `medium` |
| `plugin_changed` | Same URL, `wp_plugin` changed | `low` |
| `inline_changed` | Both inline, `inline_hash` differs | `medium` |

`_build_changed` returns at most one event per URL, checked in that order.

### 9.6 Suspicion heuristics

[apps/scripts/suspicion.py](../apps/scripts/suspicion.py) is **advisory, not a
verdict** — Digivault sees a URL and its load context, never the script body, so it
cannot prove intent. Reasons are always stored and displayed with the flag so nobody
has to trust a bare "suspicious" label. False positives are the expected failure mode
and are much cheaper than false negatives.

| Signal | Severity |
|---|---|
| `data:` / `javascript:` / `blob:` URI — payload carried inline | high |
| Obfuscation markers in the URL (`eval(`, `atob(`, `fromCharCode`, `unescape(`, `%3Cscript`) | high |
| SEO-spam keywords (viagra, cialis, casino, payday-loan, replica-watch, essay-writ, …) | high |
| Bare IPv4 address as host — avoids DNS blocklists and certificate scrutiny | high |
| Disposable / shortener host (bit.ly, tinyurl, t.co, 000webhostapp, herokuapp, pages.dev, workers.dev, repl.co, glitch.me, ngrok.io, trycloudflare.com, …) | high |
| Machine-generated-looking hostname label (`^[a-z0-9]{16,}$`) **off the site's own domain** | medium |

An `_ALLOWED` list of known-good hosts (Google, Facebook, Hotjar, Stripe, jsDelivr,
unpkg, cdnjs, HubSpot, Intercom, Clarity, Bing, DoubleClick, …) short-circuits the
host rules. Suspicion is **re-assessed on every ingest**, not just on create — a URL
can start benign and be swapped later, which is exactly the case worth catching.

### 9.7 Ingest endpoint

`POST /api/ingest/` — `AllowAny`, no authentication classes, `IngestThrottle`.

1. Reject `Content-Length > 1 MB` with **413** before parsing JSON.
2. `IngestPayloadSerializer` validation.
3. Unknown `site_id` → **404**, before queueing.
4. **Origin binding:** if `Origin` or `Referer` is present, its host (minus `www.`)
   must equal the registered domain's host. Mismatch → **403** plus a warning log.
   Absent headers are tolerated (beacons don't always carry them).
5. Queue `process_ingest_payload` and return **202 Accepted**.

The same origin-binding pattern is repeated by `/api/ingest/js-errors/`,
`/api/ingest/form-errors/`, `/api/ingest/form-submission/` and `/api/php-errors/`.

### 9.8 `process_ingest_payload`

The Celery task (`bind=True`, `max_retries=3`, `default_retry_delay=10`) runs the
whole body inside one `transaction.atomic`:

1. **Save the raw snapshot** — `ScriptSnapshot` stores `scripts_data` **unfiltered**,
   for audit.
2. **Find the previous snapshot** for the same normalised `page_url`.
3. **Filter both lists** through `_is_trackable` before diffing — self-hosted and
   utility-library changes are noise.
4. **Diff** the filtered lists.
5. **Upsert `Script` rows** keyed `(website, normalized_url)`. New rows record
   classification, location, async/defer/inline, inline hash, WP plugin/post, first
   page seen and suspicion. Existing rows are reactivated and refreshed —
   `src_url` (latest raw form), domain, suspicion, provider, category, location,
   async/defer, `wp_plugin` (only if non-empty) and `seen_on_pages` gains the page.
6. **Collect noise PKs *before* any deactivation.** Ordering matters: querying
   `is_active=True` after the global deactivation step would miss rows already
   deactivated there, leaving their changes unacknowledged and the status stuck at
   critical.
7. **Deactivate** `GLOBAL`-scoped scripts not in this snapshot.
8. **Deactivate noise scripts and auto-acknowledge their changes.**
9. **Persist `ScriptChange` rows with site-wide dedupe.** The diff runs per page, so
   one genuinely new global script would otherwise log an event per page. Dedupe
   matches on unacknowledged `(website, change_type, script)`, or on
   `(website, change_type, description)` when no script row resolved.
10. **Dispatch alerts** for changes created since this snapshot, delivering
    immediately when the matched rule's `delivery_mode == "immediate"`.
11. **Upsert detected forms** (§10).
12. **Update scope labels** (§9.9).
13. **Touch `last_seen_at`.**
14. **Recalculate health** — always, because noise cleanup may have shifted status
    even when no new trackable change occurred.

Any exception logs the traceback and calls `self.retry(exc=exc)`.

### 9.9 Scope classification

`_update_script_scopes()` counts distinct `page_url`s ever seen for the site, then
per active script:

| Distinct pages seen | Scope |
|---|---|
| ≤ 1 | `one_time` |
| Site has 1 page total, or seen on ≥ 80% of pages | `global` |
| Otherwise | `page_specific` |

A script newly becoming `one_time` **and** having `provider="unknown"` is forced back
to `review_status="pending"` — a one-off unknown script on a single page is the
classic injection signature.

### 9.10 Script review and acknowledgement

`Script.review_status` ∈ `pending` / `approved` / `blocked` / `ignored`.

- `PATCH /api/v1/websites/<id>/scripts/<pk>/review/`
- `POST /api/v1/websites/<id>/scripts/bulk-review/` — `{script_ids, review_status}`

Any verdict other than `pending` **acknowledges the script's open changes** and
recalculates health once. Without this, the HIGH "Unknown script detected" change
that drove the site to critical would survive triage and the dashboard would stay
stuck. Both write `SCRIPT_REVIEWED` audit rows.

- `POST /api/v1/changes/<pk>/acknowledge/` — single; already-acknowledged returns 200.
- `POST /api/v1/changes/bulk-acknowledge/` — `{change_ids}`. Counts are taken
  **before** the update, while the queryset still means "not yet acknowledged";
  re-querying afterwards would also pick up changes someone else had acknowledged.
  Each affected website is recalculated **once**, which avoids the race where the UI
  fires many parallel single-acknowledge requests, none seeing the others'
  uncommitted acks, leaving the site critical. One audit row is written **per
  website** rather than per batch, because a bulk ack can span sites and a single row
  would name only one — leaving the Activity Log's Website column empty and the
  site's own activity tab missing the acknowledgement.

### 9.11 Script read endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/websites/<id>/scripts/` | Active scripts; filters `category`, `provider` (icontains), `scope`, `location` |
| GET | `/api/v1/websites/<id>/changes/` | Per-site change log; filters `severity`, `change_type`, `unacknowledged=true` |
| GET | `/api/v1/changes/` | **Team-wide** change log, same filters. Replaced one request per website (60+ for a real agency) with a single query |
| GET | `/api/v1/websites/<id>/scripts/<pk>/timeline/` | One script's change history |
| GET | `/api/extension/lookup/?domain=…` | Public, `ExtensionThrottle`. Returns `registered`, `script_count`, `has_unknown` and **at most 10** sanitised entries (provider, category, `src_domain`, `is_inline`). Full `src` URLs are deliberately omitted so this cannot enumerate a team's private inventory |

### 9.12 Deduplication migration

[apps/scripts/dedup.py](../apps/scripts/dedup.py) backfills `normalized_url` and
merges duplicate rows (migration `0009`). The keeper is the earliest `created_at` per
`(website, normalized_url)`; it absorbs the union of `seen_on_pages`, the
highest-priority `review_status` (`approved` > `blocked` > `ignored` > `pending`),
`is_active` if any duplicate was active, and the most recently seen raw `src_url`.
`ScriptChange` FKs are repointed. Grouping happens before any write, because
backfilling `normalized_url` while duplicates still exist would trip the unique
constraint on re-runs. Migration `0010` then adds
`unique_together (website, normalized_url)`.

---

## 10. Forms, form submissions and form errors

### 10.1 Detection

`collectForms()` in the snippet finds three kinds:

1. **Native `<form>`** — every `input`/`textarea`/`select` that is not hidden,
   submit, button, reset or image, described as `{name, type, label, required}`.
   Labels come from `label[for=id]`.
2. **Div-based / JS forms** — inputs not inside any `<form>`. `formLikeContainer()`
   walks up at most 8 levels looking for `role="form"`, an id/class containing
   "form", or a container holding a submit-style control, falling back to the
   input's parent so unrelated inputs aren't merged into one giant group. A group is
   kept only if it has a submit control **or** ≥ 2 fields.
3. **Embedded third-party iframes** — matched by `src` against HubSpot, Typeform,
   Jotform, Mailchimp, Google Forms, Calendly, Wufoo and Zoho Forms. Fields inside a
   cross-origin iframe are unreadable by any in-page script, so only **presence and
   provider** are recorded.

### 10.2 `DetectedForm`

Unique `(website, page_url, fingerprint)`, so several forms on one page coexist and
re-sends update in place.

`compute_fingerprint()` hashes detection type, form id, name, action and the sorted
set of field names. **Volatile fields are excluded** — nonces, honeypots,
`_wpcf7*`, `g-recaptcha`, `h-captcha`, `ct_`, `ak_`, and hex-named anti-spam fields
(`^[0-9a-f]{12,}$`) — because they rotate per page load and would otherwise mint a
"new" form on every visit and inflate counts.

Also stored: `submission_count`, `last_submission_at` (distinct from `last_seen_at`,
which bumps on every pageview whether or not anyone submitted), `first_seen_at`.

### 10.3 Submission counting

The snippet's capturing `submit` listener calls `sendFormSubmission(form)` for native
forms only — embedded iframes never fire this event in the parent page. It describes
the form exactly as `collectForms()` does so the server can recompute the same
fingerprint.

`POST /api/ingest/form-submission/` increments `submission_count` and sets
`last_submission_at` **only if that fingerprint already exists on that page**,
avoiding phantom counts for forms never catalogued. Response: `{counted: bool}`, 202.
`F()` expressions are used so concurrent submissions don't lose counts.

### 10.4 Form error detection

Two client-side paths, both reading **only the plugin's own status text** — never
field values:

1. **Contact Form 7** fires `wpcf7mailfailed`, the highest-quality signal, carrying
   the API response message and form ID.
2. **Generic** — after any `submit`, a `MutationObserver` watches added nodes and
   character data for ~20 s. Candidate text must be 6–600 characters (status messages
   are short; a whole-page container is not one) and match a failure regex covering
   "submission failed", "failed to send", "could not be sent/send", "server error",
   "internal error", "error occurred", "try again later", "mail … fail", "smtp" and
   bare `50[0-4]`. `formSource()` infers the plugin from the form's class: Contact
   Form 7, WPForms, Elementor Forms, Gravity Forms, Ninja Forms, Forminator, HubSpot.

Client-side dedupe keys on `source|form_id|message` truncated to 200 chars.

### 10.5 Server-side filtering and sanitisation

`POST /api/ingest/form-errors/` applies
[apps/scripts/form_errors.py](../apps/scripts/form_errors.py):

- `is_important_form_error()` — stores only server-side failures. Pure user-validation
  noise ("is required", "invalid email", "too short", "captcha", …) is **acknowledged
  with 202 but never stored**, so probing the endpoint reveals nothing.
- `sanitize_page_url()` — replaces the values of `email`, `token`, `key`,
  `password`, `phone`, `code`, `auth` and `session` query params with `[hidden]`
  while keeping page identity intact.
- `sanitize_error_message()` — redacts email addresses, `password=`/`token=`/
  `secret=`/`key=`/`auth=` fragments, and digit runs of 7+ (phone numbers, order
  IDs), then truncates to 500 chars.

`FormSubmissionError` therefore holds **no PII at rest**. It also feeds the health
score, bounded to 7 days.

### 10.6 Form read endpoints

| Method | Path |
|---|---|
| GET | `/api/v1/websites/<id>/forms/` |
| GET | `/api/v1/forms/` (team-wide) |
| GET | `/api/v1/websites/<id>/form-errors/` |
| GET | `/api/v1/form-errors/` (team-wide) |

---

## 11. JavaScript error capture

### 11.1 Client side

The snippet attaches `addEventListener('error')` — **not** `window.onerror`, which
would clobber any handler the site already has — plus `unhandledrejection`.

Resource-load failures (`img`/`script`/`link`) surface on the same event with no
message and the element as target; these are filtered out, since they are not script
exceptions.

Two caps apply per page load: a client-side dedupe key of
`message|source|line` (250 chars) and a hard **limit of 10** errors. A script
erroring inside a loop can fire thousands of times, and the point is to learn that it
broke, not to relay every occurrence. Stack traces are truncated to the **first 5
frames** and 4000 characters.

### 11.2 Server side

`POST /api/ingest/js-errors/` → `JsError`, deduplicated on `(website, fingerprint)`
with a hit counter.

`is_reportable()` ([apps/scripts/js_errors.py](../apps/scripts/js_errors.py)) drops:

- Blank messages.
- Known-uninformative noise: `"Script error."` (what browsers report for any
  exception from a cross-origin script without CORS headers — no message, file or
  line, so storing it only adds noise), the two ResizeObserver loop messages, and
  "Non-Error promise rejection captured".
- Anything sourced from `chrome-extension://`, `moz-extension://`,
  `safari-extension://` or `safari-web-extension://` — a visitor's own extension
  throwing is not the site's bug.

Filtered errors return **202 without storing**, so probing reveals nothing.

`fingerprint()` normalises every digit run in the message to `#` (ids and timestamps
would otherwise make each occurrence unique), truncates to 300 chars, and hashes
`message|source_url|line_no` to 40 hex chars. It **deliberately excludes the column
number and the page URL**: the same bug fires at slightly different columns after a
re-minify, and on every page of the site, but it is still one bug to fix.

`browser_label()` returns only the family — Edge, Opera, Chrome, Firefox, Safari (in
that detection order, since Edge and Opera UAs also contain `Chrome/`) — because the
goal is spotting a browser-specific break, and a full UA string is a fingerprinting
surface with no purpose here.

On a repeat, `hits` is incremented with `F('hits') + 1` so concurrent hits don't lose
counts, `last_seen_at` is bumped, and `is_resolved` is forced back to `False` — a
"resolved" error still firing is not resolved.

`GET /api/v1/websites/<id>/js-errors/` lists them, most recently seen first.

---

## 12. Alerts and notifications

### 12.1 `AlertRule`

Team-level configuration. `website=None` makes a rule global; a per-website rule
**shadows** a global rule for the same channel.

| Field | Values |
|---|---|
| `name` | Human label; blank on legacy rows, UI derives one from channel/severity |
| `channel` | `in_app`, `email`, `clickup` (+ legacy `slack`) |
| `min_severity` | `high` (high only) / `medium` (medium & above) / `low` (all) |
| `change_types` | JSON list; **empty means all types** |
| `delivery_mode` | `immediate` / `hourly_digest` / `daily_digest` |
| `slack_webhook_url` | Legacy Slack destination |
| `is_active` | Toggle |

### 12.2 `AlertSuppression`

Mutes a known script on a website by `provider` or source `domain`, unique
`(website, match_type, match_value)`, with a `reason` and `created_by`. Checked
first in dispatch — a matching change produces **no notifications at all**.

Endpoints: `GET/POST /api/v1/websites/<id>/alert-suppressions/`,
`DELETE /api/v1/alert-suppressions/<pk>/`.

### 12.3 Matching

`AlertService.dispatch_for_change(change)`
([apps/alerts/services.py](../apps/alerts/services.py)):

1. If the change has a script and any suppression matches → return `[]`.
2. Collect active per-website rules and active global rules; global rules are
   dropped for any channel a per-website rule already covers.
3. For each remaining rule, gate on severity (`high`=3, `medium`=2, `low`=1;
   `actual >= required`) then on `change_types` (empty = all).
4. Create a `Notification` per match and return them.

Delivery is a separate Celery task per notification, so failures are isolated and
retryable.

### 12.4 `Notification`

`team`, `website`, nullable `script_change` (domain and performance alerts have
none), nullable `rule`, `channel`, `delivery_status`
(`pending`/`sent`/`failed`), `delivered_at`, `error_message`,
`digest_period_start`, `read`, `read_at`. Indexed on `(team, read, -created_at)` and
`(team, delivery_status)`.

Endpoints: `GET /api/v1/notifications/`,
`POST /api/v1/notifications/mark-read/`.

### 12.5 Delivery backends

[apps/alerts/delivery.py](../apps/alerts/delivery.py) — stateless classes selected by
`get_backend(channel)`:

| Channel | Behaviour |
|---|---|
| `email` | `EmailDelivery` — recipients are the team's **owners and managers**; body carries website, change type, severity, description and before/after values |
| `clickup` | `ClickUpDelivery` — reuses the team's active `NotificationChannel` rows of type `clickup`, so no extra config lives on the rule. `post_clickup()` routes to a Chat channel (v3 API) when `chat_url` is set, else comments on `task_id` (v2) |
| `slack` | `SlackDelivery` — posts a coloured attachment (`high` #ef4444, `medium` #f59e0b, `low` #94a3b8) to `rule.slack_webhook_url` |
| `in_app` | `InAppDelivery` — calls `push_notification()` to the Channels group |

### 12.6 Delivery task and digests

`alerts.deliver_notification` (`max_retries=3`, `default_retry_delay=30`) is
idempotent — it returns early if already `sent`. On success it sets `sent` +
`delivered_at`; on failure it records `failed` + a 500-char `error_message` and
re-raises for retry.

`alerts.send_digest(mode)` queues delivery for all `pending` notifications whose rule
has that `delivery_mode`. Beat runs it hourly at `:00` with `hourly_digest` and daily
at 08:00 UTC with `daily_digest`.

`alerts.purge_old_notifications(days=90)` deletes non-pending rows older than 90 days
in 1000-row chunks, Sundays at 02:45 UTC.

### 12.7 WebSocket delivery

`AlertConsumer` ([apps/alerts/consumers.py](../apps/alerts/consumers.py)) accepts a
JWT in three ways, in order:

1. `Sec-WebSocket-Protocol: bearer, <token>` — the browser-friendly path, since
   browsers can't set arbitrary WS headers. The `bearer` subprotocol is echoed on
   accept.
2. `Authorization: Bearer <token>` — non-browser clients.
3. `?token=<token>` — legacy fallback, noted in the code as leaking into logs.

Validation runs through `database_sync_to_async` so the event loop isn't blocked. On
success the connection joins `alerts_team_<team_id>` and receives a
`{"type": "connection_established"}` frame; on failure it closes with **4001**.
Client→server messages are ignored — the channel is push-only.

`push_notification()` is synchronous (callable from Celery via `async_to_sync`) and
sends `{id, channel, website{id,name,domain}, delivery_status, read, created_at}`
plus a `script_change` block when present. A missing channel layer logs a warning
rather than raising.

Routing: `path("ws/alerts/", AlertConsumer.as_asgi())`.

---

## 13. Uptime monitoring and notification channels

### 13.1 `Monitor`

Types: `http`, `ping`, `port`, `ssl`. Statuses: `up`, `down`, `degraded`, `paused`,
`pending`.

HTTP options: `expected_status_code` (default 200), `request_method`,
`request_headers` (JSON), `request_body`, `keyword` (response body must contain it).
Port option: `port`. Scheduling: `check_interval` ∈ {30 s, 1, 2, 5, 10, 15, 30 min,
1 h} default 300 s, `timeout` default 30 s, `retry_count` default 3 (consecutive
failures before an incident).

State: `status`, `is_active`, `consecutive_failures`, `is_alerting`,
`last_checked_at`, `last_response_time`, cached `uptime_24h` / `uptime_7d` /
`uptime_30d`. A nullable `website` FK links auto-provisioned monitors, which is what
lets uptime alerts route to the website's channel and powers the status-page card on
the website detail page.

`recalculate_uptime()` recomputes all three windows from `MonitorCheck` rows —
`None` when a window has no checks, else `round(up/total × 100, 2)` — and writes them
with a single `.update()`.

### 13.2 Checkers

[apps/monitors/checker.py](../apps/monitors/checker.py) — pure functions returning
`{status, response_time_ms, status_code, error_message}`.

| Function | Logic |
|---|---|
| `check_http` | Timed `urlopen` with `User-Agent: Digivault-Monitor/1.0`, reads the first 4096 bytes. Keyword miss → `down`. Code == expected → `up`; other 2xx/3xx → `degraded`; else `down` |
| `check_ping` | TCP/DNS-based (ICMP needs root): `gethostbyname` timing. `gaierror` → `down` with "DNS lookup failed" |
| `check_port` | `create_connection((host, port))`; `ConnectionRefusedError` → "Port N refused" |
| `check_ssl` | TLS handshake on 443, parses `notAfter`. Expired or ≤ 7 days → `down`; ≤ 30 days → `degraded`; else `up` |

`run_check(monitor)` dispatches by type; an unknown type returns `down`.

### 13.3 Scheduling and state machine

`monitors.run_due_checks` runs **every 30 seconds** from beat. It selects active,
non-paused monitors and queues `check_single_monitor` for each whose
`last_checked_at` is null or older than its `check_interval`.

`monitors.check_single_monitor` (`max_retries=0` — a retry would double-count) writes
a `MonitorCheck` row and then:

- **Result `up`:** notify only if `is_alerting` was set; reset
  `consecutive_failures=0`, `is_alerting=False`.
- **Result not `up`:** increment failures; fire an alert only when
  `new_failures >= retry_count` **and** `is_alerting` was not already set. This gives
  retry-before-alert and no duplicate alerts while a monitor stays down.

Then `recalculate_uptime()`. If the status **flipped** and the monitor has a website,
health is recalculated immediately — otherwise a site could sit at 100 while down —
but only on a flip, not on every 30-second check, to keep write volume flat.
Notification is suppressed when the previous status was `pending`.

### 13.4 Notification routing

`notify_status_change()` ([apps/monitors/notifications.py](../apps/monitors/notifications.py))
fires only for down, recovery (`down`/`degraded` → `up`) or degraded, and dedupes by
channel ID so one channel never gets two messages:

1. If the monitor has a website: a dedicated `uptime_notification_channel` **wins**
   over the general `notification_channel`, so downtime routes separately from
   content/script alerts. Only the website's **explicitly set** channel auto-fires
   here — the team-wide fallback is intentionally not used for uptime noise.
2. Explicit `MonitorNotificationRule` rows add channels with per-event flags
   (`notify_on_down` default true, `notify_on_recovery` default true,
   `notify_on_degraded` default false).

`resolve_channels(website)` is the shared resolver used by uptime, domain and SEO
alerts: the website's own channel if set and active, else all the team's active
channels.

### 13.5 `NotificationChannel`

Team-scoped, reusable. Types: `email`, `clickup`, `slack`. Config is JSON —
`{addresses: [...]}` for email, `{api_token, task_id}` or `{api_token, chat_url}` for
ClickUp, `{webhook_url}` for Slack.

`parse_clickup_chat()` extracts workspace and channel IDs from a ClickUp Chat link
such as `https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438`.

`POST /api/v1/notification-channels/<pk>/test/` sends a real test message and returns
success plus a message, so misconfiguration surfaces at setup rather than during an
incident.

### 13.6 Rollups and retention

`monitors.rollup_daily_uptime(target_date=None)` runs at 00:15 UTC for yesterday and
is **idempotent** — re-running upserts. Per monitor it aggregates
`checks_total`, `checks_up`, `checks_degraded`, `avg_response_time_ms` and
`uptime_pct` into `MonitorUptimeRollup` (unique `(monitor, date)`).

`monitors.purge_old_checks(days=35)` runs at 01:00 UTC in 1000-row chunks. The
default is 35 days rather than 30 to keep a safety margin over the 30-day uptime
window, so `recalculate_uptime()` still has full raw data; rollups hold older history.

### 13.7 Monitor endpoints

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/api/v1/monitors/` | Team-scoped list / create |
| GET | `/api/v1/monitors/uptime-trend/?days=90` | Team-wide daily trend. Routed **before** `<uuid:pk>` so "uptime-trend" isn't parsed as an ID. Points with no checks return `value: null` |
| GET/PATCH/DELETE | `/api/v1/monitors/<pk>/` | |
| GET | `/api/v1/monitors/<pk>/checks/` | Raw check history |
| POST | `/api/v1/monitors/<pk>/pause/` · `/resume/` | Audited |
| POST | `/api/v1/monitors/<pk>/check-now/` | Immediate check |
| GET/POST | `/api/v1/notification-channels/` | |
| GET/PATCH/DELETE | `/api/v1/notification-channels/<pk>/` | |
| POST | `/api/v1/notification-channels/<pk>/test/` | |
| GET/POST | `/api/v1/monitors/<pk>/notification-rules/` | |
| GET/PATCH/DELETE | `/api/v1/monitors/<pk>/notification-rules/<rule_pk>/` | |

---

## 14. Domain, SSL, hosting and mail intelligence

### 14.1 `DomainInfo`

One-to-one with `Website`, refreshed daily.

| Group | Fields |
|---|---|
| WHOIS | `registrar`, `registered_at`, `expires_at`, `nameservers`, `whois_privacy`, `auto_renew` |
| Hosting | `hosting_provider`, `hosting_ip`, `server_location`, `uses_cloudflare`, `hosting_expires_at` (**manually entered** — not discoverable via WHOIS or DNS) |
| Mail | `smtp_status` (ok/unreachable/no_mx/error), `mx_hosts`, `smtp_checked_at` |
| Email auth | `spf_status`/`spf_record`, `dmarc_status`/`dmarc_record`, `dkim_status`/`dkim_selector` |
| SSL | `ssl_issuer`, `ssl_expires_at`, `ssl_auto_renew` |
| Meta | `last_checked_at` |

Three properties — `domain_days_until_expiry`, `ssl_days_until_expiry`,
`hosting_days_until_expiry` — return `None` when the date is unset and clamp at 0.

Email-auth statuses describe **presence and syntax, not correctness**: proving an SPF
policy lists the right senders needs the sending infrastructure, which Digivault does
not know.

### 14.2 Checks

`DomainIntelligenceService.check(domain)`
([apps/domains/services.py](../apps/domains/services.py)) never raises. It normalises
the input (strips scheme, `www.`, port, path) then runs three independently
try/except'd stages:

- **WHOIS** via `python-whois`: registrar, creation and expiry dates (coping with
  list-or-scalar returns), lowercased nameservers. `whois_privacy` is inferred from
  "privacy", "proxy", "whoisguard" or "protect" in the registrar name.
  `uses_cloudflare` from `\.ns\.cloudflare\.com$` nameservers.
- **Hosting**: 18 provider patterns matched first against the nameserver string,
  then the resolved IP is reverse-DNS'd and matched again (reverse DNS wins as more
  specific). Unmatched → `"Unknown"`.
- **SSL**: TLS handshake on 443, issuer `organizationName`, `notAfter` parsed as
  `%b %d %H:%M:%S %Y %Z`. `ssl_auto_renew` is `True` for Let's Encrypt by convention.

`check_smtp(domain)` resolves MX by preference and probes up to the **first three**
hosts with an SMTP `NOOP` on port 25 → `ok` / `unreachable` / `no_mx` / `error`.

`check_email_auth(domain)` reads TXT records, **joining the 255-byte chunks** long
DMARC and SPF policies are split into — without this the record reads as truncated.
SPF is a `v=spf1` TXT on the apex; DMARC a `v=dmarc1` TXT at `_dmarc.<domain>`. DKIM
selectors are not discoverable, so it probes a known list —
`google`, `selector1`, `selector2`, `k1`, `s1`, `s2`, `zoho`, `default`, `dkim`,
covering Google Workspace, Microsoft 365, Mailchimp, SendGrid, Zoho and the common
self-hosted default — and records whichever answered. A missing selector is the
normal case and does not stop the loop.

### 14.3 Expiry alerts

Thresholds (days before expiry):

| Kind | Thresholds |
|---|---|
| Domain | 90, 60, 30, 14, 7, 3 |
| SSL | 90, 30, 7 |
| Hosting | 90, 60, 30, 14, 7, 3 |

`DomainAlert` is unique `(domain_info, alert_type, days_until_expiry)`, which alone
prevents duplicate sends.

`_deliver_unsent_alerts()` handles the multi-threshold problem: a domain already
close to expiry crosses 30/14/7 at once, and one message per threshold is noise.
Per alert type it delivers only the **most urgent** unsent alert and, on success,
marks the wider thresholds `sent` as covered by it.

`deliver_domain_alert()` sends to every channel from `resolve_channels(website)` via
email or ClickUp. If the team has no channels, or every send fails, the alert is
**left unsent** so a later domain check retries it. It is marked sent if it reached
at least one channel.

### 14.4 Tasks and endpoints

`domains.check_domain(website_id)` (`max_retries=2`, `default_retry_delay=60`) runs
the domain check, `update_or_create`s `DomainInfo`, layers on SMTP and email-auth
results with a separate `.update()`, creates and delivers expiry alerts, then
recalculates health.

`domains.check_all_domains` runs daily at **06:00 UTC** and queues a check for every
website **except `inactive`**. It notably does *not* skip `critical`: once status
started deriving from `health_score`, a site scoring below 60 would stop being
checked, its expiry data would freeze, and the expiry deductions could never
clear — `critical` means "needs attention", the last status that should stop being
checked.

Endpoints: `GET /api/v1/websites/<id>/domain/` and
`POST /api/v1/websites/<id>/domain/refresh/` (audited as `DOMAIN_REFRESHED`).

---

## 15. Performance and Core Web Vitals

### 15.1 Lab data — PageSpeed Insights

`PageSpeedService.check(url, strategy)`
([apps/performance/services.py](../apps/performance/services.py)) calls PSI v5 with
`category=performance`, adding `PAGESPEED_API_KEY` when configured, 60 s timeout. A
**429** is translated into an actionable message naming the env var and the key
signup URL rather than a bare HTTP error.

`PerformanceReport` stores `performance_score` (0–100), `fcp_ms`, `lcp_ms`,
`cls_score`, `tbt_ms`, `ttfb_ms`, `si_ms`, `tti_ms`, `inp_ms`, per-metric ratings for
FCP/LCP/CLS/TBT (`fast` ≥ 0.9, `average` ≥ 0.5, else `slow`), an `error` string and
`checked_at`. Indexed `(website, strategy, -checked_at)`.

Failures are **stored as rows with `error` set**, not swallowed — a run that failed is
itself a fact worth keeping.

### 15.2 Field data — Chrome UX Report

`CruxService.fetch(url)` derives the origin and POSTs to the CrUX API for six
metrics: LCP, FCP, CLS, INP, experimental TTFB and legacy FID. It stores p75 values
plus the good / needs-improvement / poor distribution densities for the four Core Web
Vitals.

Two HTTP codes get specific messages because both are common and confusing: **404**
means the origin lacks sufficient real-user traffic to appear in CrUX; **403** almost
always means the Chrome UX Report API is not enabled for the key's Google Cloud
project — it is a *separate* API from PageSpeed Insights and must be enabled on its
own, so the message links to the exact console page.

### 15.3 Trends and regression alerting

`weekly_trend(website, strategy, weeks=8)`
([apps/performance/trends.py](../apps/performance/trends.py)) averages scores per
Monday-anchored ISO week.

`detect_regression(website, strategy, drop_threshold=15)` compares the two most
recent scored reports and returns `{strategy, previous, current, drop}` when the
score fell by 15 or more.

`alert_on_regression()` creates an in-app `Notification` on a detected regression,
and is called from `check_website_performance` only when the run produced no error.

### 15.4 Endpoints and retention

| Method | Path |
|---|---|
| GET | `/api/v1/websites/<id>/performance/` |
| POST | `/api/v1/websites/<id>/performance/run/` |
| GET | `/api/v1/websites/<id>/performance/trends/` |
| GET | `/api/v1/websites/<id>/crux/` |
| POST | `/api/v1/websites/<id>/crux/run/` |

`performance.purge_old_reports(days=365)` deletes `PerformanceReport` rows older than
12 months in 1000-row chunks, Sundays at 02:00 UTC.

---

## 16. Known constraints, divergences and gaps

These are factual observations from the source, recorded so they are not mistaken for
intended behaviour.

### 16.1 Refresh-token blacklisting is configured but not installed

`SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"] = True` requires
`rest_framework_simplejwt.token_blacklist` in `INSTALLED_APPS`. It is **not present**
anywhere in `config/` or `requirements/`. Rotation therefore issues new refresh
tokens, but the old ones are **not** invalidated and remain valid for their full
7-day lifetime. Adding the app plus its migration would close this.

### 16.2 Ingest throttle rate contradicts its setting

`THROTTLE_INGEST` defaults to `10000/day`, but `IngestThrottle` sets
`rate = "2000/day"` as a class attribute. DRF's `SimpleRateThrottle.__init__` only
calls `get_rate()` when `rate` is falsy, so the class attribute wins and the setting
is dead. The effective limit is **2000/day per `site_id`**.

### 16.3 Access-cookie lifetime is shorter than the token

The JWT access token lives 15 minutes; the `ss_access` cookie is set with
`maxAge: 60 * 5` (5 minutes) in both the login route and `proxy.ts`. The cookie
expires first, so `proxy.ts` performs a silent refresh roughly every 5 minutes rather
than every 15. This is safe but triples refresh traffic.

### 16.4 `server_location` is never populated

`DomainInfo.server_location` is declared, serialized and rendered on the Access &
Domain tab, but no code writes it — `DomainCheckResult` has no corresponding field.
It always displays empty.

### 16.5 `DomainInfo.auto_renew` is never populated

Same shape: the field exists and is exposed, but `check_domain` does not pass it and
`DomainCheckResult.auto_renew` is never set by `_whois`. Only `ssl_auto_renew` is
derived (Let's Encrypt by convention).

### 16.6 Dead code retained deliberately

`_update_website_status()` in `apps/scripts/tasks.py` is now a thin delegate to
`recalculate_health_score()`, kept only because data migration `scripts/0007` and
several call sites reference it by name. `rotate_key()` in the vault is retained for
backward compatibility; new code should use `rotate_token()`.

### 16.7 Legacy enum members kept valid

`TeamMembership.Role` retains `editor` and `seo`; `AlertRule.Channel` and
`Notification.channel` retain `slack`. None are offered in the UI, but existing rows
must stay valid, so the choices remain.

### 16.8 Snippet cannot see inside cross-origin iframes

By design and by browser security, embedded third-party forms (HubSpot, Typeform,
Calendly, …) can only be recorded as presence + provider. Their fields, submissions
and errors are invisible to any in-page script, so `submission_count` never
increments for them.

### 16.9 Suspicion flags are heuristic

`apps/scripts/suspicion.py` reasons from a URL alone and cannot prove intent. Flags
must always be shown with their stored reasons; treating `is_suspicious` as a verdict
would misrepresent what the system knows.

### 16.10 Server-side Scan is homepage-only and script-only

`POST /api/v1/websites/<id>/scan/` fetches one page and extracts scripts only. Forms,
JS errors and deeper pages require the passive snippet. This is the most common
source of "why isn't X detected" confusion.

### 16.11 `_normalise` uses `lstrip` semantics for `www.`

`DomainIntelligenceService._normalise` guards with `startswith("www.")` before
calling `host.lstrip("www.")`. `lstrip` strips a *character set*, not a prefix, so a
host beginning with the letters `w`, `.` or `n` after `www.` could lose extra
characters (e.g. `www.wwwsite.com` → `site.com`). The guard limits exposure but the
call is still not prefix-stripping.

---

*Chapters 17–28 continue in [`digivault-srs-part2.md`](digivault-srs-part2.md).*
