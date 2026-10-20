---
marp: true
title: Stacks Monitor Security Architecture
paginate: true
theme: default
---
fonts set krny hian
<!--
Presentable deck. Render with Marp:
  npx @marp-team/marp-cli docs/security-architecture-slides.md -o security.pdf
  npx @marp-team/marp-cli docs/security-architecture-slides.md --pptx -o security.pptx
Every claim maps to real code — file references are in the speaker notes.
-->

# Securing Stacks Monitor
### Defense‑in‑Depth across every layer

Stacks Monitor stores agency clients' credentials, hosting access, and site data —
so security is **layered**, not bolted on. No single control is trusted alone.

**The five layers**
1. Identity & Access
2. Multi‑Tenant Data Isolation
3. Data‑at‑Rest Encryption (Credential Vault)
4. Transport & Application Hardening
5. Auditability & Monitoring

<!-- Backend: Django 5.1 + DRF. Frontend: Next.js. This deck covers how the
project's own code and data are protected. -->

---

# Layer 1 — Identity & Access

**Authentication**
- **JWT (HS256)** — short‑lived access tokens (**15 min**), refresh tokens (**7 days**)
- **Refresh‑token rotation** + **blacklist‑after‑rotation** → a stolen refresh token can't be reused
- Tokens delivered to the browser as cookies; sent to the API as `Bearer`
- **Two‑factor auth (TOTP)** with backup codes — verification is rate‑limited (10/min)
- Django **password validators**: min length, common‑password, numeric‑only, user‑similarity

**Authorization**
- API defaults to `IsAuthenticated` — endpoints are closed by default
- `IsTeamMember` + `RolePermission` enforce a role hierarchy:
  **viewer → developer → manager → owner**

<!-- config/settings/base.py (SIMPLE_JWT, AUTH_PASSWORD_VALIDATORS),
apps/accounts/totp_views.py, apps/common/permissions.py -->

---

# Layer 2 — Multi‑Tenant Data Isolation

Every resource — websites, scripts, credentials, monitors, clients — belongs to a **Team**.

- The logged‑in user has an **`active_team`**; it scopes everything they can see.
- **`TeamScopedMixin`** automatically applies `.for_team(active_team)` to *every*
  queryset — isolation is enforced centrally, not re‑implemented per view.
- Backed by `TeamScopedQuerySet.for_team()` on the models themselves → **defense‑in‑depth**.
- Cross‑team access returns **empty / 404**, never another team's data.
- All records use **UUID primary keys** — IDs aren't guessable or enumerable.

> One missed filter can't leak data: the mixin closes the queryset, the manager
> closes the model, and the permission closes the endpoint.

<!-- apps/common/mixins.py, apps/common/querysets.py -->

---

# Layer 3 — Data‑at‑Rest Encryption (Credential Vault)

Client logins and secrets are **encrypted before they touch the database**.

- **Fernet (AES‑128‑CBC + HMAC‑SHA256)** authenticated encryption for every stored credential
- Encryption keys live **only in environment variables** — never in the DB, code, or logs
- **Key rotation** via `MultiFernet`: new key encrypts, all keys decrypt; a management
  command re‑encrypts existing data, then the old key is dropped
- **Tamper detection** — any modified ciphertext raises `InvalidToken` instead of returning data
- App secrets (`DJANGO_SECRET_KEY`, DB/Redis URLs, API keys) are env‑injected and
  **separated per environment** (`.env` dev vs `.env.production`)
- **Data minimization** — raw script snapshots auto‑purged after **90 days**

<!-- apps/credentials/encryption.py, rotate_vault_keys management command -->

---

# Layer 4 — Transport & Application Hardening

**In transit**
- HTTPS terminated at **nginx**; Django trusts `X‑Forwarded‑Proto`
- **HSTS** — 1 year, `includeSubDomains`, `preload`
- **Secure + CSRF cookies**, `X‑Frame‑Options: DENY`, `X‑Content‑Type‑Options: nosniff`
- **CORS allow‑list** — production refuses to boot with a `localhost` origin

**At the edge of the app**
- **Rate limiting / throttling** per audience: anon `100/day`, user `5000/day`,
  ingest `10000/day`, browser extension `300/hour`, TOTP `10/min`
- **Centralized exception handler** + response envelope → consistent errors,
  **no stack traces or internals leaked** to clients

<!-- config/settings/production.py, REST_FRAMEWORK throttles,
apps/common/exceptions.py, apps/common/renderers.py -->

---

# Layer 5 — Auditability & Monitoring

**You can't secure what you can't see.**

- **Immutable audit log (`ActivityLog`)** records every significant action —
  logins, credential views/shares, script reviews, client edits, imports/exports
- Each entry captures **actor, action, resource, and timestamp**
- Powers per‑user activity views and incident investigation

**Security features we also ship to clients**
- **Security‑header grading** (HSTS, CSP, X‑Frame‑Options, …) with fix guidance
- **Vulnerability scanning** of detected plugins/themes
- **Third‑party script change detection** — alerts on tampering / supply‑chain risk

> Result: layered controls protect Stacks Monitor's **own code and data**, and the
> platform turns that same rigor outward to harden the client sites it monitors.

<!-- apps/audit/models.py, apps/site_health (headers + vuln scan),
apps/scripts (diff engine) -->
