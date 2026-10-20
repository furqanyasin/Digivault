# Phase 2 — Scripts UX Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Active/Inactive status, Approve/Block actions, and a review filter directly in the Scripts tab; delete the duplicate Tracking tab; make script approval improve the health score.

**Architecture:** `scripts-tab.tsx` (already a client component grouping scripts by domain) gains a Status column, an aggregated Review column with row-level Approve/Block/Undo actions (looping the existing per-script PATCH `/api/websites/{id}/scripts/{sid}/review` endpoint over the group), and a client-side filter bar (All/Pending/Approved/Blocked). The website page passes inactive scripts too so Inactive rows are visible. `Website.recalculate_health_score` gains a deduction for active scripts still pending review, so approving raises the score.

**Tech Stack:** Next.js 16 client component, Django model method + pytest.

## Global Constraints

- `pytest --create-db` after model changes (none here — method only).
- `npm run build` must pass; no new lint errors in touched files.
- Commits on `phase-0-hardening`.

---

### Task 1: Health score — pending-review deduction

**Files:**
- Modify: `apps/websites/models.py` (`recalculate_health_score`)
- Test: `tests/websites/test_health_score.py` (extend)

**Interfaces:**
- Produces: active, non-internal scripts with `review_status="pending"` deduct 2 points each, capped at 10. Approving/blocking/ignoring removes the deduction.

- [ ] Step 1: Failing test — website with 3 pending active scripts scores 6 lower than after approving them (94 vs 100 baseline).
- [ ] Step 2: Implement deduction inside `recalculate_health_score` before final clamp:

```python
from apps.scripts.models import Script
pending_review = (
    Script.objects.filter(website=self, is_active=True, review_status="pending")
    .exclude(src_domain__in=internal)
    .count()
)
deductions += min(pending_review * 2, 10)
```

- [ ] Step 3: `pytest tests/websites/test_health_score.py -v` → PASS.
- [ ] Step 4: Commit `feat(health): unreviewed active scripts deduct from health score`.

### Task 2: Scripts tab — status badge, review column, filter

**Files:**
- Modify: `frontend/src/components/scripts-tab.tsx`, `frontend/src/app/(dashboard)/websites/[id]/page.tsx`

**Interfaces:**
- Consumes: existing PATCH review endpoint; `Script.is_active`, `Script.review_status` (already in the API payload).
- Produces: `ScriptsTab` accepts all display-worthy scripts (active + inactive); groups aggregate — Status = Active if any member active; Review = blocked if any blocked, approved if all approved, ignored if all ignored, else pending.

- [ ] Step 1: page.tsx — `scriptsForTab` includes inactive scripts (same internal/unknown filtering, without `is_active` requirement); tab badge keeps the active count.
- [ ] Step 2: scripts-tab.tsx — add filter state (`all | pending | approved | blocked`), filter bar buttons with counts, Status column (green dot Active / red dot Inactive), Review column showing aggregate chip + Approve/Block buttons that PATCH every script in the group then `router.refresh()`.
- [ ] Step 3: `npm run build` → PASS.
- [ ] Step 4: Commit `feat(scripts-ui): status badge, approve/block actions, review filter in Scripts tab`.

### Task 3: Remove Tracking tab

**Files:**
- Modify: `frontend/src/app/(dashboard)/websites/[id]/page.tsx` (TabsTrigger line 271, TabsContent ~630, import)
- Delete: `frontend/src/components/tracking-tab.tsx`

- [ ] Step 1: Remove trigger, content block, import; delete component file. Redirect nothing — `?tab=tracking` deep links fall back to defaultValue handling (verify `tab` default when value unknown → Tabs shows nothing; map `tracking` → `scripts` in the `tab` computation).
- [ ] Step 2: `npm run build` → PASS; grep for remaining `tracking-tab`/`TrackingTab` references.
- [ ] Step 3: Commit `feat(scripts-ui): remove Tracking tab — status now lives in Scripts tab`.
