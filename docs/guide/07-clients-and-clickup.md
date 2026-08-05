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

## Web team channel *(owners & managers)*

**What it is:** one ClickUp Chat channel holding your whole web team. When a website
has a problem, Digivault posts it there and addresses the developer assigned to that
client — so nobody has to be watching a dashboard to find out.

What gets announced:

- **Uptime** — a site going down or degraded, and again when it recovers
- **Domain, SSL and hosting expiry** warnings
- **SEO regressions** — noindex appearing, robots.txt blocking, a sitemap vanishing,
  on‑page meta changing

Script changes are deliberately left out — a third‑party script diff on every page
load would drown the channel. Those keep their per‑website channels.

### Set it up

1. **Settings → ClickUp Integration**, below *Issue list*.
2. Click **Create web team channel**. Digivault makes a private ClickUp channel and
   adds everyone on the team it can find in your ClickUp workspace.
3. Already have a channel? Paste its link instead and **Save link**.

Leave it blank and nothing is posted.

### Who gets mentioned

The developer named in the client's **assigned to** field — so keeping that current is
what makes the mentions useful. A site with no client, or a client with nobody
assigned, still gets announced; the message just says *unassigned*.

Digivault matches your team to ClickUp **by email address**. Anyone whose ClickUp
email differs from their Digivault one shows up under *not found* after a sync — paste
their **ClickUp user ID** in the box next to their name and **Save & re‑sync**.

### Tasks alongside the message

If **Issue list** is set, each problem also opens a ClickUp task there, assigned to the
same developer, and the channel message links to it. Repeat alerts for the same ongoing
problem comment on that one task instead of piling up duplicates; when the problem
clears, the task is closed so the next occurrence starts a fresh one.

## Gotchas

- **ClickUp section missing?** It's owner/manager‑only and lives in **Settings**,
  which is hidden from developers.
- **Token invalid:** use **Test connection** — it tells you immediately if the token
  lacks access, rather than failing silently on the next sync.
- The token is stored per **team/department** — connect it separately in each.
- **Channel posts but nobody is pinged?** That member isn't matched to a ClickUp user
  — check the *not found* list after a re‑sync.
- **Nothing posted at all?** The channel link is blank, or the token was removed.
  Both are silent by design, so a half‑configured team never spams error logs.
- **"Create web team channel" greyed out?** Connect the API token first — the button
  needs it to read your workspace.
