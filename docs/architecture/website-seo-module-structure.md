# Stacks Monitor — Website & SEO Module Structure

**Goal:** reorganize the product around **two primary modules — Website and SEO** —
so every feature has an obvious home, the SEO side can grow into a full product,
and adding future features is drop-in rather than a refactor.

---

## 1. Principles

1. **Two product modules, one platform.** *Website* (operations/monitoring) and
   *SEO* (search visibility). A client site appears in **both** — each module
   shows its own lens on the same site.
2. **Shared services stay shared.** Clients, Credentials, Alerts, Reports, Team,
   Audit are cross-cutting — they're not duplicated per module, they're consumed
   by both.
3. **Module registry, not hard-coding.** Each module declares its sections,
   per-site tabs, feature keys and nav entries in one place. Navigation,
   permissions and dashboards are *derived* from that registry, so a future
   feature is added by registering it — no nav/permission surgery.
4. **No backend rewrite.** Django apps stay as-is; "module" is a grouping at the
   presentation + permission layer. (Mapping in §6.)

---

## 2. Current feature inventory → module mapping

| Feature (today) | Backend app | Module |
|---|---|---|
| Script monitoring, change log, classifier | `scripts` | **Website** |
| Forms detection | `scripts` | **Website** |
| Tracking snippet / ingest | `scripts` | **Website** |
| Uptime monitors | `monitors` | **Website** |
| Status pages | `status_pages` | **Website** |
| Domain / SSL / hosting / DNS / mail | `domains` | **Website** |
| Renewal Center (domain/SSL/hosting/contract) | `domains`,`clients` | **Website** |
| Performance (Lighthouse + CrUX) | `performance` | **Website (primary)** + surfaced in SEO |
| Security: vulnerability scan | `site_health` | **Website** |
| Security: HTTP header grading | `site_health` | **Website** |
| **SEO audit** (robots, sitemap, indexability, on-page meta/title/H1/canonical) | `site_health` (`seo_checker`, `SeoReport`) | **SEO** |
| Credential Vault + extension | `credentials` | **Shared** |
| Clients registry | `clients` | **Shared** |
| Alerts & notification channels | `alerts`,`monitors` | **Shared** |
| Reports (PDF/CSV) | `reports` | **Shared** (Website + SEO sections) |
| Team / roles / 2FA | `accounts` | **Global** |
| Activity log | `audit` | **Global** |

---

## 3. Website module

The operational health of a site. Sections:

- **Website Dashboard** — portfolio health, sites with issues, pending changes,
  high-risk, monitors down, upcoming renewals.
- **Sites** → per-site tabs:
  - Overview · Scripts · Forms · Tracking · Access & Domain · Performance ·
    Security · Change Log · Setup
- **Uptime** — monitors + public status pages.
- **Renewals** — domain / SSL / hosting / contract.
- **Reports** — website report (scripts, performance, security, domain).

Future-ready slots: more monitor types (cron/heartbeat, API), more integrations
(host APIs), backup monitoring, malware scanning.

---

## 4. SEO module

Today this is the per-site technical/on-page audit; the module is designed to
grow into a full SEO product.

**Now (already built):**
- **SEO Audit** per site — robots.txt, sitemap, indexability (noindex),
  on-page meta/title/H1/canonical, with change events (meta changed, noindex
  detected, robots blocks all, sitemap missing).
- **Core Web Vitals** — reuse the `performance` data through an SEO lens
  (LCP/INP/CLS pass-fail), since CWV is a ranking factor.

**Roadmap slots (future updates — register as they're built):**
- Keyword rank tracking (per keyword, per site, history).
- Backlink monitoring.
- Competitor tracking.
- Content / meta manager (bulk titles & descriptions).
- Technical SEO crawler (broken links, redirects, schema/structured data).
- SEO scorecard + SEO Reports (PDF/CSV).

SEO module sections: **SEO Dashboard** (scores across sites), **Sites** (per-site
audit), and roadmap sections added as registered features.

---

## 5. Navigation & UX

Sidebar gains a **module switcher** at the top (Website ▸ / SEO ▸), then the nav
below shows only that module's sections. A **Global** group (Clients, Credentials,
Alerts, Reports, Team, Activity Log, Settings) stays visible in both.

```
┌─────────────────────────────┐
│  [ Website ▾ ]  ← switcher  │
├─────────────────────────────┤
│  Website                    │
│   • Dashboard               │
│   • Sites                   │
│   • Uptime & Status         │
│   • Renewals                │
│   • Reports                 │
├─────────────────────────────┤
│  Shared                     │
│   • Clients                 │
│   • Credentials             │
│   • Alerts                  │
│   • Activity Log            │
└─────────────────────────────┘
```

Switching to **SEO** swaps the top group to SEO sections; Shared/Global stay.
A client site opened from either module deep-links into that module's view of it.

---

## 6. Backend architecture (no rewrite)

- Keep existing apps. Add a thin **module registry** (e.g. `apps/common/modules.py`)
  that declares:
  ```python
  MODULES = {
    "website": {"label": "Website", "features": [...], "nav": [...]},
    "seo":     {"label": "SEO",     "features": [...], "nav": [...]},
  }
  ```
  Each feature entry maps a key → label, route, backend app, required role.
- Nav, the custom-access checklist, and module dashboards all read this registry —
  one edit to add a feature everywhere.
- **Per-website module enablement** (optional, future): a `Website.modules`
  field (e.g. `["website","seo"]`) so a site can opt into Website monitoring, SEO,
  or both. Defaults to both; lets you sell/enable them independently later.

---

## 7. Permissions & roles (ties into custom access)

This reorg makes the access model we just shipped cleaner:

- Group the existing **feature keys by module**. The custom-access checklist then
  shows two sections — *Website features* and *SEO features*.
- Reintroduce intent of the retired **SEO role** as a **module grant**: an "SEO"
  member = custom access to the SEO module's features only; a "Website" member =
  Website features. No special-case roles — just module-scoped feature_access.
- Managers/owners see all modules; custom members see the modules/features granted.

---

## 8. Phased rollout (low-risk, incremental)

1. **Phase 1 — Navigation grouping (no data change).** Introduce the module
   switcher + registry; group existing sections under Website / SEO / Shared.
   Pure IA; everything keeps working.
2. **Phase 2 — Module-scoped permissions.** Group feature keys by module in the
   custom-access UI; module-level grants.
3. **Phase 3 — Module dashboards.** Dedicated Website and SEO overview pages
   (scores/issues per module).
4. **Phase 4 — Grow SEO.** Build roadmap SEO features (keywords, backlinks,
   crawler, SEO reports), each registered into the SEO module.
5. **Phase 5 (optional) — Per-website module enablement & packaging.**

---

## 9. Open decisions

- **Performance & Security headers** primary home = Website, but should they also
  appear in the SEO module (CWV + headers affect SEO)? *Recommended: surface
  read-only in SEO, owned by Website.*
- **Reports**: one unified report vs separate Website report and SEO report.
  *Recommended: shared engine, two templates.*
- **Nav style**: top module switcher (recommended) vs two always-expanded groups.
