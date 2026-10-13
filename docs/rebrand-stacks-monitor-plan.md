# Rebrand Plan: Digivault to Stacks Monitor

| Item | Old | New |
|---|---|---|
| Product name | Digivault | Stacks Monitor |
| Domain | digivault.digilatics.co | stacksmonitor.com |
| Company / owner | Digilatics (office) | Independent (own launch) |
| GitHub repo | furqanyasin/Digivault | furqanyasin/stacks-monitor (proposed) |

Status: **plan only, nothing changed yet.** Created 2026-10-14.

---

## 1. Inventory (what exists today)

Scan of all 1036 tracked files, case-insensitive.

| Term | Hits | Files | Notes |
|---|---|---|---|
| `digivault` (all spellings) | 836 | 185 | ~45% are in `docs/` |
| `digilatics` (office brand) | 285 | 82 | domain, emails, test fixtures, UI labels |
| `scdb` (old server folder name) | 70 | 8 | deploy docs and paths |
| `scriptsentry` (oldest name) | 6 | 3 | docs only |
| `website-a11y` (office GitHub org) | 5 | 1 | `docs/deploy.md` |

### 1.1 Spelling variants and their replacement

| Old form | Where | New form |
|---|---|---|
| `Digivault` | UI text, emails, comments | `Stacks Monitor` |
| `DIGIVAULT` | PDF report header | `STACKS MONITOR` |
| `DigiVault` | a few docs | `Stacks Monitor` |
| `digivault` (identifier) | DB name/user, WP REST namespace, CSV filenames, tags | `stacksmonitor` |
| `digivault-*` (kebab) | extension folder, icon file, pm2 process, zip | `stacksmonitor-*` |
| `digivault_hub` | Celery app name, cache key prefix | `stacksmonitor` |
| `X-Digivault-Site/Timestamp/Signature` | WP snippet to API headers | `X-StacksMonitor-*` (see Phase 5) |
| `HTTP_X_DIGIVAULT_*` | Django `request.META` reads | `HTTP_X_STACKSMONITOR_*` |
| `DIGIVAULT_EXTENSION_AUTH/READY/LOGOUT` | web app to extension messages | `STACKSMONITOR_EXTENSION_*` |
| `Digivault-Uptime/1.0`, `Digivault-Monitor`, `Digivault-Scanner/1.0`, `Digivault-Heartbeat/1.0`, `Digivault/1.0` | outbound User-Agents | `StacksMonitor-Uptime/1.0`, `StacksMonitor-Monitor`, etc. |
| `data-digivault-ui` | extension DOM marker | `data-stacksmonitor-ui` |
| `digivault.digilatics.co` | default URLs, bot page link | `stacksmonitor.com` |
| `cdn.digivault.digilatics.co` | fallback snippet URL (never had DNS) | `https://stacksmonitor.com/api` |
| `alerts@` / `noreply@digivault.digilatics.co` | email defaults | `alerts@stacksmonitor.com` / `noreply@stacksmonitor.com` |
| `digilaticsvps.digilatics.co` | internal-host list | remove |
| `/home/digilatics-digivault/...`, `/var/backups/digivault` | server paths | new paths on the new server |

### 1.2 Things that must NOT be renamed

| Item | Why |
|---|---|
| Migration **filenames**, e.g. `apps/clients/migrations/0002_add_website_built_maintained_by_digi.py` | Django tracks migrations by filename. Renaming one breaks `migrate`. |
| Old migration **contents** | History. Only add new migrations. |
| `dv_` / `dvc2_` / `DVC2_` / `dv-` prefixes (WP snippet functions, options, table, cron hooks, extension storage keys, CSS classes) | Internal, never shown to users. They live inside WordPress sites and browsers that already run the code. Renaming them orphans tables, options, cron jobs and saved extension settings. Zero user benefit. |
| Encryption keys (`VAULT_ENCRYPTION_KEYS`) | Not tied to the name (checked, no name-based salt). Leave alone. |

---

## 2. Decision 0 (answer before any work)

**Is Stacks Monitor a fresh launch, or a migration of the running office server?**

| | Track A: Fresh launch (recommended) | Track B: Migrate the office server |
|---|---|---|
| Server | New VPS | Same CloudPanel box |
| Database | New, empty | Office DB with client data |
| Client sites | None yet | Office clients already run the old snippet |
| Backward compat needed | No | Yes, a lot (Phase 5) |
| Risk | Low | High |

Why Track A is recommended:

- The office keeps `digilatics.co`. Old snippets and WP plugins on client sites point there, not to you.
- Office client data (credentials vault, client contacts) belongs to the office. It must not be copied into your product.
- Confirm in writing that you are allowed to reuse this code commercially, since it was built for the office.

The rest of this plan assumes **Track A**. Track B extra steps are marked **[Track B]**.

---

## 3. Safety rules for every phase

1. Work on a branch: `rebrand/stacks-monitor`. Never on `main`.
2. One phase = one commit (or one small PR). Easy to revert one piece.
3. Before Phase 1, tag the current state: `git tag pre-rebrand`.
4. After each phase run the full gate:
   - `pytest` (backend)
   - `cd frontend && npm run lint && npm run build`
   - `python manage.py check` and `python manage.py makemigrations --check --dry-run`
5. Use search-and-replace per phase, then read every diff. No blind repo-wide replace.
6. Do not change behaviour and naming in the same commit.

---

## 4. Phases

### Phase 0: Prep

| Step | Action |
|---|---|
| 0.1 | Make sure `main` is clean and CI is green. |
| 0.2 | `git tag pre-rebrand` and push the tag. |
| 0.3 | Create branch `rebrand/stacks-monitor`. |
| 0.4 | Run the full gate once, save the result as the baseline. |
| 0.5 | Decide which extension folder is current (see Phase 6). |

### Phase 1: Central brand constants

Today the name and domain are hardcoded in ~60 code places. Put them in one place first, so the rename becomes a one-line change and stays that way.

| Step | File | Change |
|---|---|---|
| 1.1 | `config/settings/base.py` | Add `PRODUCT_NAME = env("PRODUCT_NAME", default="Stacks Monitor")`, `PRODUCT_URL = env("PRODUCT_URL", default="https://stacksmonitor.com")`, `BOT_INFO_URL = f"{PRODUCT_URL}/bot"`. |
| 1.2 | `frontend/src/lib/brand.ts` (new) | `export const PRODUCT_NAME = "Stacks Monitor"` and `PRODUCT_URL`. |
| 1.3 | Backend code that builds subjects like `"[Digivault] ..."` | Use `settings.PRODUCT_NAME`. |

Tests to update: anything asserting the literal `"Digivault"` string.

### Phase 2: Backend user-facing text

Emails, alerts, PDF, 2FA. Low risk, all display text.

| File | What changes |
|---|---|
| `apps/accounts/views.py` | invite / account-created / password-reset emails (lines ~624-1020), default ClickUp list name `"Digivault — Web Team"` (1251), description (1259) |
| `apps/accounts/totp_views.py` | TOTP `issuer = "Digivault"` (122), message (446) |
| `apps/alerts/delivery.py` | `[Digivault]` subjects, fallback from-email, footer, dashboard text |
| `apps/credentials/access.py`, `notify.py`, `views.py` | subjects, messages, CSV export filename `digivault-vault-export.csv` |
| `apps/domains/notifications.py` | subject, body, fallback from-email |
| `apps/monitors/notifications.py`, `views.py` | subjects, test notification text, Slack text, firewall instructions text |
| `apps/scripts/notifications.py` | subject, body, fallback from-email |
| `apps/site_health/notifications.py`, `tasks.py` | `[Digivault]` prefix (note `notifications.py:48` strips that exact prefix, keep both in sync) |
| `apps/reports/builder.py` | CSV header `Digivault Report`, PDF header `DIGIVAULT`, footer, PDF title/author |
| `apps/integrations/*` | docstrings and comments only |
| `apps/websites/management/commands/*.py` | `digivault-demo` tag, export filename |
| All other `apps/**` comments/docstrings | Replace wording (no logic) |

**2FA note:** changing the TOTP issuer only affects new enrollments. Fine for Track A. **[Track B]** existing users keep seeing "Digivault" in their authenticator app until they re-enroll; that is harmless.

### Phase 3: Frontend UI

| File | What changes |
|---|---|
| `frontend/src/app/layout.tsx` | `<title>` metadata |
| `frontend/src/app/(dashboard)/layout.tsx` | sidebar logo `/digivault-icon.svg`, alt text, brand text |
| `frontend/public/digivault-icon.svg` | rename to `stacksmonitor-icon.svg`, ideally a new logo |
| `frontend/src/app/(auth)/login/page.tsx` | card description |
| `frontend/src/app/bot/page.tsx` | page title, description, headings |
| `frontend/src/components/chat-widget.tsx` | assistant greeting and title |
| `frontend/src/components/settings-client.tsx` | default list name and help text |
| `frontend/src/components/credentials-vault-client.tsx`, `src/app/api/credentials/export/route.ts` | CSV filenames |
| `frontend/src/components/forms-tab.tsx`, `form-detail-dialog.tsx`, `sync-form-recipients-button.tsx`, `wp-connect-card.tsx` | help text |
| `frontend/src/app/(dashboard)/websites/[id]/page.tsx` | help text |
| `frontend/package.json` | `"name": "frontend"` can stay, or `stacksmonitor-frontend` |
| Favicon / OG image | add new brand assets |

### Phase 4: Domain and URLs

| File | Change |
|---|---|
| `config/settings/base.py:658` | `DEFAULT_FROM_EMAIL` default to `Stacks Monitor <noreply@stacksmonitor.com>` |
| `config/settings/production.py:48` | `SNIPPET_CDN_URL` default to `https://stacksmonitor.com/api` |
| `apps/websites/models.py:390,409` | fallback `cdn.digivault...` to `settings.SNIPPET_CDN_URL` only |
| `apps/common/outbound.py:69-70` | UA URL `+https://stacksmonitor.com/bot` |
| `apps/monitors/checker.py:40`, `serializers.py:155`, `views.py:70` | bot URL from `settings.BOT_INFO_URL` |
| `apps/websites/views.py:849,1031` | bot URL |
| `apps/scripts/tasks.py:45-55` | internal hosts: keep reading `SNIPPET_CDN_URL`, drop hardcoded `digivault.digilatics.co`, `cdn.digivault...`, `digilaticsvps...` |
| `apps/scripts/classifier.py:35-36` | own-snippet rule: `stacksmonitor\.com` |
| `frontend/Dockerfile:10` | `NEXT_PUBLIC_API_URL` default |
| `frontend/src/app/(dashboard)/alerts/page.tsx:46`, `dashboard/page.tsx:185`, `websites/[id]/page.tsx:238` | `INTERNAL_DOMAINS` list (duplicated 3 times, move to `lib/brand.ts`) |
| `.env.example`, `.env.production.example` | hosts, CORS, URLs, from-email |

**[Track B]** keep the old hosts in the internal-host lists too, or the old snippet shows up as a third-party script.

### Phase 5: Protocol identifiers (most sensitive)

These are contracts between your server and code running elsewhere (WordPress sites, browsers, client firewalls).

| Identifier | Producer | Consumer | Track A action | [Track B] action |
|---|---|---|---|---|
| `X-Digivault-Site/Timestamp/Signature` headers | WP snippet `wp_sso_snippet.py:653-655` | `apps/site_health/views.py:320,353-363` | Rename both sides together. Update tests in `tests/site_health/test_wp_*`. | Server reads new header, falls back to old one. Keep fallback until all sites update snippet. |
| WP REST namespace `digivault/v1` (`/sso`, `/forms`) | WP snippet `register_rest_route` (187, 192) | `apps/websites/views.py:639`, `apps/websites/wp_forms.py:62` | Rename to `stacksmonitor/v1` both sides. | Snippet registers both namespaces. Server calls the new one, retries old on 404. |
| WP table `{prefix}digivault_events` (`wp_sso_snippet.py:57`) | WP snippet | WP snippet | Rename to `stacksmonitor_events` (fresh installs only). | Keep the old name. |
| Snippet `<script src=".../api/s.js">` | `Website.snippet_html` | client pages | Automatic via `SNIPPET_CDN_URL`. | Old domain must keep serving or redirecting `/api/s.js` and `/api/ingest/`. Needs office cooperation. |
| User-Agents (`Digivault-Uptime`, `Digivault-Monitor`, `Digivault-Scanner`, `Digivault-Heartbeat`, `Digivault/1.0`) | `apps/common/outbound.py`, `apps/site_health/tasks.py:163`, `apps/websites/tasks.py:300`, `views.py:917`, `wp_sso_snippet.py:707`, `apps/heatmap/capture.py` | client firewalls (SiteGround, Cloudflare rules) | Rename. Keep the two-token design from `outbound.py:57-63`: product token `StacksMonitor-Uptime/1.0` plus a separate allowlist token. Update firewall rule text in `apps/monitors/views.py:139,659-687` and `tests/common/test_outbound.py`, `tests/monitors/test_blocked_fix.py`, `test_checker_http.py`. | Send both old and new tokens until clients update firewall rules. |
| Extension messages `DIGIVAULT_EXTENSION_AUTH/READY/LOGOUT` | `frontend/src/components/extension-auth-bridge.tsx`, `logout-button.tsx` | extension `content.js` | Rename both sides in the same release. | Web app sends both names for one release. |
| `data-digivault-ui` attribute | extension `content.js` | extension `content.js` | Rename. | Same. |

Tip: before this phase, add one test per contract that asserts producer and consumer use the same constant (for example, import the header name from one module in both PHP builder and view).

### Phase 6: Browser extension

Two copies exist: `extension/` and `digivault-extension/` (they differ), plus `digivault-extension.zip` and `digivault-extension-old.zip` committed.

| Step | Action |
|---|---|
| 6.1 | Diff both folders and confirm which one is the shipped version (`digivault-extension/` looks newer: it has the edit-dialog guard and update-password mode). |
| 6.2 | Keep only that one, as `extension/`. Delete the other folder and both zips from git. |
| 6.3 | `manifest.json`: `name` to `Stacks Monitor`, bump `version` (e.g. `2.0.0`), update `description`. |
| 6.4 | `background.js`, `options/options.js`, `popup/popup.js`, `content.js`: default server URL to `https://stacksmonitor.com`, all UI strings. |
| 6.5 | `options.html`, `popup.html`: titles, brand text, placeholder URL. |
| 6.6 | New icons (`icon16/48/128.png`, `logo.svg`). |
| 6.7 | `.dockerignore`: update the extension paths. |
| 6.8 | Build the zip in CI or a script, do not commit it. Add `*.zip` to `.gitignore`. |
| 6.9 | Publish as a **new** Chrome Web Store item under your own developer account. |

### Phase 7: Infrastructure identifiers

| File | Change |
|---|---|
| `docker-compose.yml`, `docker-compose.production.yml`, `docker-compose.production.cloudpanel.yml` | `POSTGRES_DB/USER: stacksmonitor`, health check user, `NEXT_PUBLIC_API_URL` |
| `.github/workflows/ci.yml:42-64` | Postgres DB/user/password and `DATABASE_URL` |
| `.env.example`, `.env.production.example` | `DATABASE_URL` |
| `config/celery.py:10` | `Celery("stacksmonitor")` (task names come from module paths, not this name, so it is safe) |
| `config/settings/base.py:168` | cache `KEY_PREFIX: "stacksmonitor"` |
| `deploy.sh` | example hosts (13-15), `pm2 restart stacksmonitor-frontend` (99), health-check URL (109) |
| `backup-db.sh` | backup dir, file name pattern, `pg_dump -U stacksmonitor ... stacksmonitor`, rclone remote example |
| `nginx/nginx.conf` | `server_name`, cert paths |

**[Track B] warnings:**

- Do not rename the live Postgres DB/user in place. Keep `digivault` there, only change new environments.
- Changing the cache prefix drops all cache: throttle counters, cached egress IP, and any cache locks reset once. Deploy at a quiet time.
- The pm2 process must be re-created under the new name, or `deploy.sh` fails at `pm2 restart`.

### Phase 8: Remove office-specific content

| Item | Where | Change |
|---|---|---|
| "Website built / maintained by Digilatics" labels | `frontend/src/app/(dashboard)/clients/new/page.tsx:156,168`, `client-detail-client.tsx:211,214`, `frontend/src/lib/client-fields.ts:13` | "Built by us" / "Maintained by us", or remove if not useful for an agency-neutral product |
| Model fields `website_built_by_digi`, `website_maintained_by_digi` | `apps/clients/models.py:84-85`, serializers, views, chat intents, seed data, frontend (12 files) | Optional: `RenameField` migration to `website_built_by_us` / `website_maintained_by_us`, then update API + frontend in the same commit. Do it as its own commit. |
| Seed demo data | `seed_demo_data.py:223` ("Digilatics GoDaddy account") | neutral text |
| Test fixtures | `tests/**` using `digilatics.com`, `website@digilatics.com`, `digilatics.clickup.com/...`, `junaid@digivault.io`, team "Digilatics" | `example.com`, `clickup.example`, generic names |
| Office ClickUp URL in comment | `apps/integrations/clickup.py:25` | example URL |
| Comments naming real office client sites | `apps/common/ingest_cors.py:9`, `apps/scripts/migrations/0017_*.py:6` (leave migration as is) | neutral wording in non-migration files |
| `.gitignore:55,63` | office file names | remove |
| `WordPress_Security_Checklist.md` (root) | check content for office references | keep or move to `docs/` |

### Phase 9: Documentation

| Group | Files | Action |
|---|---|---|
| Live docs | `docs/deploy.md`, `docs/platform-guide.md`, `docs/extension.md`, `docs/extension-user-guide.md`, `docs/guide/*`, `docs/runbooks/*`, `docs/security-architecture-slides.md` | Rewrite for Stacks Monitor and the new server. `deploy.md` needs a full rewrite (new host, user, paths, repo, deploy key). |
| SRS | `docs/digivault-srs.md`, `docs/digivault-srs-part2.md` | Rename to `docs/srs.md`, `docs/srs-part2.md`, update text and links. |
| Planning | `docs/planning/*`, `docs/phases/*` | Update product name. |
| Historical | `docs/superpowers/plans/*`, `docs/superpowers/specs/*` | Move to `docs/archive/` with a one-line note that the product was called Digivault. Do not edit history line by line. |
| New | `README.md` (root, none today) | Short product README for Stacks Monitor. |

### Phase 10: Repo and local folder

| Step | Action |
|---|---|
| 10.1 | Merge the branch after the final check (Phase 12). |
| 10.2 | GitHub: rename repo `Digivault` to `stacks-monitor`. GitHub redirects the old URL. |
| 10.3 | `git remote set-url origin https://github.com/furqanyasin/stacks-monitor.git` |
| 10.4 | Rename local folder `D:\all-tools\Digivault` to `D:\all-tools\stacks-monitor` (close VS Code first). |

### Phase 11: Launch on stacksmonitor.com

| Step | Action |
|---|---|
| 11.1 | New VPS. Point DNS `stacksmonitor.com` (and `www`) to it. |
| 11.2 | SSL certificate (Let's Encrypt). |
| 11.3 | Fresh `.env.production`: new `SECRET_KEY`, **new** `VAULT_ENCRYPTION_KEYS`, new DB password, `ALLOWED_HOSTS=stacksmonitor.com`, `CORS_ALLOWED_ORIGINS=https://stacksmonitor.com`, `SNIPPET_CDN_URL=https://stacksmonitor.com/api`, `FRONTEND_URL=https://stacksmonitor.com`, `NEXT_PUBLIC_API_URL=https://stacksmonitor.com`. Never reuse office secrets. |
| 11.4 | Email: verify `stacksmonitor.com` in Brevo (SPF, DKIM, DMARC). Set `DEFAULT_FROM_EMAIL=Stacks Monitor <noreply@stacksmonitor.com>`. |
| 11.5 | Set `MONITOR_EGRESS_IPS` to the new server IP (bot page shows it). |
| 11.6 | Your own accounts for ClickUp, Slack, PageSpeed, WPScan API keys. |
| 11.7 | New GitHub deploy key, new backup bucket (`stacksmonitor-backups`). |
| 11.8 | Run `./deploy.sh`, create the first superuser. |
| 11.9 | Publish the extension (Phase 6.9). |

### Phase 12: Final verification

| Check | Command / how | Pass when |
|---|---|---|
| No old name in code | `git grep -i -E "digi[ _-]?vault\|digilatics" -- . ':!docs/archive' ':!**/migrations/**'` | empty, except intentionally kept items from section 1.2 |
| Backend tests | `pytest` | all green |
| Migrations | `python manage.py makemigrations --check --dry-run` | no changes (or only the planned RenameField) |
| Frontend | `npm run lint && npm run build` | clean |
| Snippet | `curl https://stacksmonitor.com/api/s.js` | serves `snippet_version` |
| Emails | send invite, password reset, test alert | from-address and text say Stacks Monitor |
| 2FA | enroll a new user | authenticator shows "Stacks Monitor" |
| PDF/CSV report | download one | header says Stacks Monitor |
| WP Connect | install snippet on a test WP site | SSO login, forms sync, activity push all work |
| Extension | install, log in via web app | auto-login, autofill, save prompt work |
| Bot page | open `/bot` | new name, new IP, new UA string |
| Uptime | add a monitor | UA seen in target logs is `StacksMonitor-...` |

---

## 5. Suggested commit order

1. `chore: add central brand constants` (Phase 1)
2. `chore(backend): rename user-facing text to Stacks Monitor` (Phase 2)
3. `chore(frontend): rename UI to Stacks Monitor` (Phase 3)
4. `chore: move default domain to stacksmonitor.com` (Phase 4)
5. `refactor: rename protocol identifiers (headers, WP namespace, UA, extension messages)` (Phase 5)
6. `chore(extension): single extension folder, rebranded` (Phase 6)
7. `chore(infra): rename DB, celery, cache, pm2, nginx identifiers` (Phase 7)
8. `chore: remove office-specific labels and fixtures` (Phase 8)
9. `refactor(clients): rename built/maintained-by fields` (Phase 8, optional)
10. `docs: rebrand docs, archive historical plans` (Phase 9)

Each commit must pass the full gate on its own.

---

## 6. Rollback

| Situation | Action |
|---|---|
| A phase breaks tests | `git revert <commit>` for that phase only |
| Whole rebrand needs to go | `git reset --hard pre-rebrand` on the branch (main is untouched until merge) |
| Bad production deploy | redeploy the previous commit. Track A has no old data to corrupt. |

---

## 7. Open questions

1. Track A (fresh launch) or Track B (migrate office server)?
2. Which extension folder is the shipped one?
3. Rename `website_built_by_digi` fields, or only the labels?
4. New logo and icons ready, or use a text placeholder for now?
5. Final GitHub repo name: `stacks-monitor`?
