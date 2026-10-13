# Stacks Monitor Delivery Phases

This directory breaks the [Production Readiness Roadmap](../planning/production-readiness-roadmap.md) into detailed, implementation-ready phases. Each phase file lists tasks, the exact files touched, acceptance criteria, and a test plan.

| Phase | Theme | Blocks launch? | File |
|-------|-------|----------------|------|
| **0** | Pre-launch hardening | ✅ Yes | [phase-0-hardening.md](phase-0-hardening.md) — 🟢 functionally complete (0.6b test cleanup tracked) |
| **1** | Close functional gaps | Partially | [phase-1-functional-gaps.md](phase-1-functional-gaps.md) |
| **2** | Reporting & agency dashboards | Partially | [phase-2-reporting-dashboards.md](phase-2-reporting-dashboards.md) |
| **3** | New monitoring subsystems | No | [phase-3-new-subsystems.md](phase-3-new-subsystems.md) |
| **4** | Scale, observability & monetization | No | [phase-4-scale-monetization.md](phase-4-scale-monetization.md) |

## How to use these

1. Each task has a checkbox. Tick it when the acceptance criteria pass.
2. Every backend change is **test-first** (TDD): write the failing test, then implement. Tests live under `tests/<app>/`.
3. Run `pytest` (and `pytest --cov=apps` for coverage) before marking a task done.
4. Frontend changes follow Next.js 16 conventions — read `frontend/node_modules/next/dist/docs/` before touching App Router code.

## Status legend

- ⬜ Not started · 🟡 In progress · ✅ Done · ⏸ Blocked

## Definition of "launch ready"

All of Phase 0 complete + Phase 1 items 1–2 + the full [Internal Launch Checklist](../planning/production-readiness-roadmap.md#internal-launch-checklist).
