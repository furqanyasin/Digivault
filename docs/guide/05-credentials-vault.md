# 5. Credentials Vault

**What it is:** an encrypted store for client logins (WordPress, cPanel, hosting,
domain registrars, Cloudflare, FTP, etc.) with LastPass‑style **granular sharing**
and one‑click **autofill** via the browser extension.

## Where to find it

**Credentials** in the sidebar (the global vault), or a website's **Vault** card /
credentials section for that site's logins.

## Adding a credential

1. **Credentials → New item** (or **Add** in a section).
2. Choose a type (WordPress, cPanel, GoDaddy, Cloudflare, FTP…), label, login URL,
   username, password, and optional notes.
3. Save. Username/password/notes are stored **encrypted** (AES‑256). Plaintext is
   never written to the database or logs.

The vault cards show the site's **favicon** so they're easy to scan visually.

## Revealing & copying

- Click a credential → **Reveal**. Username/password/notes are decrypted on demand,
  and **every reveal is logged** (who, when) for audit.
- Copy buttons put values on your clipboard without showing them.

## Sharing (the LastPass‑style part)

By default:
- **Owners & Managers see every credential** in the team.
- **Developers / Editors / SEO** see **only** the credentials shared with them.

To share one credential:

1. Click the **Share** icon on a credential.
2. Pick the team members (developers/editors/SEO) to share with.
3. Toggle **"Allow Recipient to View Password"**:
   - **On** — they can reveal the full password.
   - **Off** — they can **autofill** the login via the extension but the password
     stays hidden in the dashboard (shown as "hidden by share settings").
4. **Share.** The **Existing shares** list shows who has access; revoke anytime with
   the ✕.

To share a whole site's logins at once, use the **site‑level share** (shares every
credential under that website with the chosen people).

**Get 100% benefit:**
- Give each developer only the clients they work on — least privilege by default.
- Use **"view password off"** for junior staff or contractors: they can log in via
  autofill without ever seeing the raw password.
- Owners/managers don't need a share — they already see everything, so they're not
  listed under Existing shares.

**Honest limit:** "view password off" is a workflow guardrail, not unbreakable.
Autofill must place the real password into the login page to fill it, so a
technically‑savvy person could extract it from the page. It reliably stops casual
viewing/copying inside Stacks Monitor — which is what "hide password" does everywhere.

## Browser extension & autofill

The Chrome extension detects login pages and autofills the matching vault credential.

- It looks up credentials for the current domain, then fetches the password through
  the reveal API specifically for autofill — so even "view password off" shares can
  log in.
- It can also capture a new login you type and offer to save it to the vault.

See [Browser extension](09-team-roles-departments.md#browser-extension) for install
notes.

## How it works

- Encryption uses **Fernet AES‑256**; the key lives only in a server environment
  variable, supports rotation, and detects tampering.
- Who can **modify/share** a credential: owners, managers, and the credential's
  creator. Who can **see** it: owners/managers (all) + anyone it's shared with.
- Reveal is blocked for the read‑only Viewer role.

## Gotchas

- **A developer can't see a credential you added?** Share it with them — members only
  see shares, by design.
- **Autofill not filling?** Confirm the extension is installed and signed in, and that
  the site's domain matches the credential's domain.
