# 8. Reports

**What it is:** client‑ready PDF or CSV reports summarizing a website's script
changes, security posture, and recommendations over a period — the artifact you send
the client to prove the value of your monitoring.

## Generating a report

1. Open **Reports**.
2. In **Generate a report**, pick the **website**, a **date range** (From/To), and a
   **format** (PDF or CSV).
3. **Generate.** It builds synchronously and appears in **Generated reports** with a
   status of *done* (or *failed* with the reason).

## Working with reports

- **Download** — pulls the PDF/CSV.
- **Delete** — removes the report and its stored file (with a confirm). Use it to
  clear old or mistaken runs.

**What's inside a report:** the period's script changes (added/removed/modified by
severity), a security summary, and prioritized recommendations — formatted for a
non‑technical client in PDF, or as raw rows in CSV for your own analysis.

**Get 100% benefit:**
- Send a **monthly PDF** to each client — it turns invisible background monitoring
  into a visible deliverable and supports retainers.
- Use **CSV** when you want to pivot the data yourself or feed another tool.
- Generate right after acknowledging a month's changes so the report reflects a clean,
  reviewed state.

## Gotchas

- **"failed" status:** open the row — the error explains why (e.g. no data in range).
  Widen the date range or run a Scan/let traffic accumulate first.
- Reports are **per website** — generate one per client site.
