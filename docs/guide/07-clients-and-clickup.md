# 7. Clients & ClickUp

## Clients

**What it is:** the CRM‑style record for each client you manage — the business behind
the websites.

Open **Clients**. Each client holds:

- Name, website URL, status, **assigned team member**
- **Hosting platform** and **hosting renewal date**
- **Contract renewal date**, support tier, monthly revenue
- Migration status / CSM confirmation, PPC‑ads flag, built‑by/maintained‑by‑Digi flags
- Domain access location, notes & comments

**Get 100% benefit:**
- Fill in **hosting + contract renewal dates** — they feed the
  [Renewal Center](06-uptime-domains-status-alerts.md#renewal-center-owners--managers)
  so renewals never lapse.
- Use **assigned to** so each client has a clear owner on the team.
- Link the client to its website(s) so script/uptime data and the business record sit
  together.

## ClickUp integration *(owners & managers)*

**What it is:** sync client records from a ClickUp list so you don't double‑enter
data.

### Connect it

1. **Settings → ClickUp Integration** (owners/managers only).
2. Paste your ClickUp **API token** (ClickUp → Settings → Apps → API Token).
3. **Test connection** to confirm, then **Save**. A green "Connected" badge confirms it.

### Use it

- Sync pulls ClickUp tasks into **Client** records (mapping fields like hosting
  platform, renewal dates, etc.), storing the ClickUp task id so updates stay linked.
- Re‑sync to refresh; the client shows when it was last synced.

**Get 100% benefit:** keep ClickUp as your source of truth for client metadata and let
Digivault mirror it — then the Renewal Center and client list stay current without
manual edits. Each department (team) connects its own ClickUp token, so Web and SEO
can point at different lists.

## Gotchas

- **ClickUp section missing?** It's owner/manager‑only and lives in **Settings**,
  which is hidden from developers.
- **Token invalid:** use **Test connection** — it tells you immediately if the token
  lacks access, rather than failing silently on the next sync.
- The token is stored per **team/department** — connect it separately in each.
