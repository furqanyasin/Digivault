# Dashboard VIP Sections + Health Score v2 — Design

**Date:** 2026-07-29
**Branch:** `phase-0-hardening`

## Problem

Five related complaints about the Dashboard (Home) page:

1. There is no way to mark a website as important. High-value client sites are
   buried among the rest.
2. The dashboard shows the first 6 websites ordered by `name`. Sites with real
   problems are not surfaced; a healthy site alphabetically first takes a slot
   from a site that is down.
3. The health score "is not working well" — see the defect list below.
4. Critical alert counts render in muted grey, identical to every other caption.
5. The "Fleet health" card duplicates what the Renewal Center page (already
   titled "Renewal Center" at `/renewals`) owns, and its button reads
   "Run fleet audit" — which audits nothing; it is a link.

## Health score defects

`Website.recalculate_health_score()` (apps/websites/models.py:118) deducts only
for: pending script changes, domain expiry, SSL expiry, open vulnerabilities,
and unreviewed active scripts. The concrete consequences:

| # | Defect | Consequence |
|---|--------|-------------|
| 1 | Monitors are never read | A site that is hard-down scores 100. Nothing recalculates when a monitor flips state. |
| 2 | `FormSubmissionError` costs nothing | The dashboard paints "N broken" as destructive while the score stays clean. |
| 3 | Stale `last_seen_at` costs nothing | The snippet stopped reporting — we are blind — but the last happy score persists. |
| 4 | Hosting expiry ignored | Domain and SSL deduct; hosting does not, though the Renewal Center tracks all three. |
| 5 | `status` and `health_score` are computed independently | `_update_website_status()` (apps/scripts/tasks.py:399) sets `status` from the worst open *script change only*. The dashboard colours the score by `status`, so a 42-score site renders emerald. |
| 6 | Time decay is stale | Expiry deductions refresh only when a domain check runs; there is no periodic recalculation. |
| 7 | Two divergent formulas | `_security_score()` (apps/websites/health.py:16) scores the same vulnerability and SSL inputs with different weights. |

## Scope

In scope: `is_vip` flag on Website, health score v2, status derived from score,
dashboard restructuring, red critical alerts, Renewal Center rename.

Out of scope: changing Renewal Center page behaviour, alert rule changes,
performance-score integration into health (data is too sparse per site),
per-client VIP tiers.

## Design

### 1. VIP designation

New field on `Website`:

```python
is_vip = models.BooleanField(
    default=False,
    help_text="Surface this site in the dashboard's VIP section.",
)
```

Indexed via the existing composite pattern: add `models.Index(fields=["team", "is_vip"])`.

Rejected alternatives:
- **Derive from `Client`** — no tier field exists, and VIP-ness is per-site (a
  client can have one flagship site and five brochure sites).
- **Use the existing `tags` JSONField** — not efficiently queryable, and
  typo-prone (`vip` vs `VIP` vs `Vip`).

Exposed as a writable field on `WebsiteSerializer` (it is a user setting, not
derived state) and added to the frontend `Website` interface. Toggleable from
the website detail page settings area.

### 2. Health score v2

Extend `recalculate_health_score()` with four new deduction groups. Existing
deductions are unchanged so current tests stay meaningful.

**Uptime (new)** — read monitors attached to this website:
- Any monitor `down`: −30
- Else any monitor `degraded`: −12
- Worst `uptime_30d` below 95%: −15; below 99%: −5 (whichever tier applies, not both)

**Broken forms (new)** — `FormSubmissionError` in the last 7 days: −6 each, cap −18.
Bounded to 7 days so a fixed form recovers its score rather than being punished
by history.

**Reporting gap (new)** — only for sites that have reported at least once
(`last_seen_at` is not null; a brand-new site is not penalised for having no
traffic yet):
- `last_seen_at` older than 30 days: −20
- older than 7 days: −10

**Hosting expiry (new)** — mirrors the domain tier on `domain_info.hosting_expires_at`:
- ≤7 days: −20
- ≤30 days: −8

Total deductions still clamp to `[0, 100]`.

### 3. Status: the worse of urgency and score band

> **Revised during implementation.** The original plan made status a *pure*
> function of the score. Implementing it showed that wrong: one unacknowledged
> high-severity script change costs 10 points, so a site with an injected
> unknown script scored 90 and read `active` — the exact event this product
> exists to catch, averaged away. Severity does not survive being summed.

`status` and `health_score` answer different questions and both are kept:

- `health_score` — cumulative, "how healthy overall".
- `status` — "how urgent is the worst open issue".

`recalculate_health_score()` collects urgency flags alongside the deductions and
takes the worse of the flags and the score band:

- `critical` if any of: open critical/high script change, a monitor `down`,
  domain/SSL/hosting expiring within 7 days, **or** score < 60.
- `warning` if any of: open medium change, a monitor `degraded`, a broken form in
  the last 7 days, an expiry within 30 days, a reporting gap, **or** score < 85.
- otherwise `active`.

The score band is what stops a badge reading `active` beside a score of 42; the
flags are what stop a single high-severity issue being averaged away. Both
guarantees are required, which is why neither field is derived from the other.

`inactive` is left alone — it is a manual/lifecycle state, not a health verdict,
so a website already marked `inactive` is not overwritten.

**Required companion fix.** `domains.check_all_domains` (apps/domains/tasks.py:130)
enqueues daily domain checks only for websites whose status is `active` or
`warning`. Under the new rule, any site scoring below 60 becomes `critical` and
would stop receiving domain checks — so its domain/SSL data goes stale, and the
expiry deductions freeze at whatever they were. A site could never recover. The
filter must change to exclude only `inactive`:

```python
Website.objects.exclude(status=Website.Status.INACTIVE)
```

This is the correct intent anyway — `critical` means "needs attention", which is
the last status that should stop being checked.

This makes the badge and the number impossible to contradict, and removes the
need for the frontend to colour by `status` while displaying `health_score`.
`recalculate_health_score()` becomes the single writer of both fields, so it
updates them in one `Website.objects.filter(pk=...).update(...)` call.

### 4. Recalculation triggers

Existing call sites (script acknowledge, domain check, security scan, ingest)
are kept. Two additions:

- **Monitor state change** — in `monitors.run_due_checks`, when a check flips a
  monitor's status and the monitor has a `website_id`, recalculate that website.
  Only on flip, not every 30-second check, to keep the write volume flat.
- **Daily sweep** — new Celery Beat entry `websites.recalculate_all_health`
  running daily (after the 06:00 domain check, at 06:30 UTC) so time-based
  decay is real rather than dependent on some other task firing.

### 5. Reconcile `_security_score()`'s SSL window only

> **Narrowed during implementation.** The original plan was to make the security
> sub-score adopt overall health's vulnerability weights too. That is wrong:
> overall health caps vuln deductions at −24 because vulns are one of eight
> inputs, whereas this score has three. Flattening them gave the security score a
> **floor of 31**, so a site with ten critical vulnerabilities still looked
> survivable. Steeper vuln weights on a security-only score are correct, not a
> disagreement.

What genuinely disagreed was the SSL window: `_security_score` deducted a flat 15
for anything inside 14 days, while `recalculate_health_score()` used 7/14/30-day
tiers — so the same certificate produced contradictory readings. Only that is
changed: both now use the same tiers (≤7d −20, ≤14d −12, ≤30d −5). The
vulnerability and PHP-error weights stay as they were.

### 6. Dashboard restructuring

Order of sections on `/dashboard`, top to bottom:

1. **Stats row** (unchanged, 4 cards) — the "Active alerts" caption renders
   `N critical` in red (`text-red-600 font-semibold`) when `highRisk.length > 0`,
   muted otherwise.
2. **VIP Websites** — up to 3 sites where `is_vip`, sorted worst-score-first.
   Header links to `/websites?vip=1`. When the team has no VIP sites, the section
   renders a short empty state explaining how to flag one (rather than being
   hidden, which would leave the feature undiscoverable).
3. **Needs Attention** — up to 3 **non-VIP**, non-`inactive` sites whose `status`
   is `warning` or `critical` (or whose score is below 85), sorted
   worst-score-first. Hidden entirely when empty — "nothing needs attention" is
   better said by absence, and the VIP section already anchors the layout.

   Driven by `status`, not by a score threshold. A `health_score < 85` filter was
   tried first and silently skipped a site with two broken contact forms: it
   scores 88. Since `status` is now the "worst open issue" verdict, it is the
   right signal; the score band is kept only as a floor.
4. **Recent activity + Renewal Center** (the existing 2-column row).
5. **Your Sites** grid (unchanged, 6-card cap).

VIP and Needs Attention reuse a single extracted `SiteHealthCard` component —
the existing inline card markup in `dashboard/page.tsx` lifted into
`frontend/src/components/site-health-card.tsx`. Both new sections and the
existing grid render it, so the three stay visually identical. The card's
health colour is driven by `health_score` thresholds (85/60), matching
`health-score-info.tsx`, not by `status`.

Selection happens client-side from the already-fetched `websites` array — no new
API request. The dashboard already fetches all websites via `api.getAll`.

### 7. Renewal Center rename

In `dashboard/page.tsx`: card heading "Fleet health" → "Renewal Center", button
label "Run fleet audit" → "Open Renewal Center". The card's contents and its
`/renewals` link are unchanged. The `/renewals` page itself already carries the
"Renewal Center" title, so this only removes the naming mismatch.

### 8. Keep the rubric honest

`frontend/src/components/health-score-info.tsx` carries a `RUBRIC` constant
documented as mirroring the model. It must gain the four new groups (uptime,
broken forms, reporting gap, hosting expiry) or the explanation panel becomes a
lie. The status-derivation paragraph in that component also needs rewriting —
it currently explains the old "worst open change" rule.

## Testing

`tests/websites/test_health_score.py` already covers the existing deductions and
is the natural home for the new ones. Written test-first:

- Monitor `down` on an attached monitor deducts 30; `degraded` deducts 12; a
  monitor with no `website` link deducts nothing.
- `uptime_30d` at 94% deducts 15; at 98% deducts 5; at 99.9% deducts nothing.
- Three `FormSubmissionError` rows in the last 7 days deduct 18; four also
  deduct 18 (cap); one 8 days old deducts nothing.
- `last_seen_at` 10 days ago deducts 10; 40 days ago deducts 20; `None` deducts
  nothing.
- Hosting expiring in 5 days deducts 20; in 20 days deducts 8.
- Status derivation: score 55 → `critical`, 70 → `warning`, 95 → `active`; a
  site already `inactive` stays `inactive`.
- Deductions clamp: a site with every problem scores 0, never negative.

Existing `_update_website_status` assertions in `tests/scripts/` will need
updating — status is no longer a function of change severity alone. That is
expected and is the point of the change.

New: `tests/monitors/` assertion that a monitor status flip triggers a website
recalculation.

Run with `--create-db` after the migration, per the project test conventions.

## Migration

Single migration adding `is_vip` (default `False`, no backfill needed) plus the
`["team", "is_vip"]` index.

Health scores for existing sites will shift the first time each is recalculated.
The daily sweep picks them all up within 24 hours of deploy; no data migration
is needed and none should be added — recalculation is cheap and idempotent.

## Risks

- **Scores will drop across the board.** Sites that were silently at 100 while
  down or blind will fall. This is the correction being asked for, but it will
  look like a regression to anyone watching the numbers. Worth a note in the
  release summary.
- **Status flips.** Deriving status from score means some sites currently
  `active` become `warning` or `critical`. Audited for status-keyed logic:
  `apps/websites/health.py:83` and `apps/reports/builder.py:165` only read it
  through to output (harmless), and `apps/domains/tasks.py:130` gates the daily
  domain check — fixed above. No alert rule keys on website status.
- **Status becomes lossy.** Today `critical` tells you "there is an
  unacknowledged high-severity script change". Afterwards it means "score below
  60", which could be downtime, expiry, or forms. The specific reason is still
  available on the website detail page, but the badge alone says less. Accepted:
  a badge that agrees with the number is worth more than a badge that encodes one
  cause.
