# 9. Team, Roles & Departments

This chapter covers running people and departments, your personal account, and the
audit trail.

## Departments (= Teams)

A **team is a department**. Each is a fully isolated workspace — its own clients,
websites, credentials, monitors, reports. This is how you run a **Web Department** and
an **SEO Department** that share nothing.

### Create a department *(owner)*

1. Open the **team switcher** (bottom‑left).
2. **New department** → type a name (e.g. "SEO Department") → confirm. You're switched
   into it as its owner.
3. Repeat for each department.

### Switch departments

Anyone in more than one department uses the switcher to change the active department;
the entire app re‑scopes instantly. People in a single department just see that one.

## Team members & roles *(owners & managers)*

Open **Team**. You can invite members, change roles, and remove members.

### Roles

| Role | Tier | Access |
|------|------|--------|
| **Owner** | 4 | Everything; can't be removed/downgraded by others |
| **Manager** | 3 | Manage members, settings, ClickUp, renewals; sees all credentials & full activity log |
| **Developer** | 2 (member) | Sees only shared credentials; works the team's sites; no team/settings |
| **Editor** | 2 (member) | Same as Developer — label for content/SEO editors |
| **SEO** | 2 (member) | Same as Developer — label for SEO‑team members |
| **Viewer** | 1 | Read‑only; cannot reveal credentials |

Developer, Editor, and SEO are **the same access level** — three labels so a person's
role reads correctly for their job. (If you later need them to differ, that's a small
change.)

### Inviting into a department

1. Switch into the right department.
2. **Team → invite** with the member's email and the role you want.
3. They receive an invitation and **join that department** — they don't create their
   own. A person can be invited into multiple departments with a different role in
   each (e.g. *Manager* in Web, *SEO* in SEO).

**Get 100% benefit:**
- Set up departments once, then invite everyone into the right one — least privilege
  from day one.
- Use **Manager** for department leads (so they handle members + settings) and
  **Developer/Editor/SEO** for the people doing the work.
- Role rules are enforced: you can't assign a role higher than your own, or modify
  someone above you.

## My Account *(everyone)*

Open **My Account** to manage your own:

- **Profile** — name, email, your role, active department.
- **Two‑Factor Authentication** — set up, disable, or regenerate backup codes.

This is where developers (who don't see Settings) manage their own security.

## Activity Log

**What it is:** an audit trail of actions — credential reveals, script
acknowledgements, member changes, settings edits, and more.

- **Members** (developer/editor/SEO) see **only their own** actions.
- **Owners & Managers** see the **whole department's** log and can filter by user,
  action, type, date, or text — and export to CSV.

**Get 100% benefit:** when something looks off ("who revealed that password / changed
that setting?"), managers filter the log by user or action to get the answer. Logs are
retained and old ones purged automatically.

## Settings *(owners & managers)*

Holds the **ClickUp integration** and team configuration (see
[Clients & ClickUp](07-clients-and-clickup.md)). Hidden from developers; they manage
their own security in **My Account** instead.

## Browser extension

The Chrome extension complements the vault:

- **Autofills** client logins on their sites from the vault (works even for
  "view‑password‑off" shares).
- **Captures** new logins you type and offers to save them.
- Detects scripts on the page you're viewing.

Install it, sign in (it hands off your session securely), and it scopes to your active
department like the web app.

## Gotchas

- **Can't see Team/Settings/Renewal?** Those are owner/manager‑only by design.
- **A teammate sees the wrong clients?** Check which **department** they're in — data
  is per department.
- **Need someone in both Web and SEO?** Invite them into each; they switch with the
  team switcher.
