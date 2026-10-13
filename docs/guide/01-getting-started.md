# 1. Getting Started

## Logging in

1. Go to your Stacks Monitor URL and sign in with your email + password.
2. **Two‑factor authentication is mandatory.** On first login you'll be sent to
   set up 2FA (see below) before you can use the app.
3. After login you land on the **Dashboard** — a roll‑up of every site's status,
   pending changes, monitors, and risk.

## Set up 2FA (everyone, including developers)

1. Open **My Account** in the sidebar (visible to every role).
2. Under **Two‑Factor Authentication**, click **Set up 2FA**.
3. Scan the QR code with Google Authenticator / Authy / 1Password, enter the 6‑digit
   code to confirm, and **save your backup codes** somewhere safe.
4. Later you can **regenerate backup codes** or **disable 2FA** from the same page.

**Get 100% benefit:** store backup codes in your password manager the moment they're
shown — they're the only way back in if you lose your phone. Each code works once.

## Navigation & who sees what

The sidebar adapts to your role:

| Item | Who sees it |
|------|-------------|
| Dashboard, Clients, Websites, Monitors, Status Pages, Alerts, Reports, Credentials | Everyone |
| Activity Log | Everyone (members see only their own actions) |
| My Account | Everyone |
| **Renewal Center, Team, Settings** | **Owners & Managers only** |

If a developer opens a manager‑only URL directly, they get a polite "access
restricted" notice instead of the page.

## Teams = Departments

A **team is a department**. Two teams share *nothing* — separate clients, websites,
credentials, monitors and reports. This is how you run, say, a **Web Department** and
an **SEO Department** side by side.

- The **team switcher** (bottom‑left) shows the department you're acting in.
- If you belong to more than one department, use it to switch; the whole app
  re‑scopes instantly.
- Owners can create a new department from the switcher → **New department**.

See [Team, Roles & Departments](09-team-roles-departments.md) for the full setup.

## First‑run checklist for an owner

1. Create your departments (e.g. *Web*, *SEO*) from the team switcher.
2. In each department, open **Team → invite** your people with the right role.
3. Add **Clients** (or sync them from ClickUp in **Settings**).
4. Add **Websites** and install the tracking snippet (next chapter).
5. Set up **Monitors**, **Alerts**, and a **Status Page** if clients want one.
6. Store logins in the **Credentials Vault** and share selectively.

## Gotchas

- **No data yet?** Detection is passive — a website shows nothing until its snippet
  fires (a real browser loads a page that has it) or you run a one‑off **Scan**.
- **Invited users don't create their own department** — they join yours. Only
  self‑registration spins up a brand‑new team.
