# Digivault Extension — User Guide

The Digivault Chrome extension gives your team instant visibility into third-party scripts on any client website, plus a built-in password manager for saved credentials — all without leaving the browser.

---

## Installation

1. Open **Chrome** and go to `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select the `extension/` folder from this repo
4. The Digivault shield icon appears in your toolbar

> Once the extension is on the Chrome Web Store, step 2–3 will be replaced by a single "Add to Chrome" click.

---

## First-time setup — Log in

Before the password manager and autofill features work, you need to sign in once:

1. Click the **⚙ settings icon** in the extension popup (or right-click the toolbar icon → **Options**)
2. Enter your **Digivault email and password** and click **Log in**
3. You'll see "Logged in as you@example.com" — done

You stay logged in until you click **Log out** or your session expires (7 days).

> The extension and the web app share the same account — one login covers both.

---

## Feature 1 — Script badge on every tab

**What it does:** As soon as a page finishes loading, the extension checks whether that site is registered in Digivault. If it is, a badge appears on the extension icon showing how many third-party scripts are running.

| Badge colour | Meaning |
|---|---|
| **Green** | All scripts are from known providers |
| **Orange** | One or more scripts are from an unknown provider |
| No badge | Site is not registered in Digivault |

**Why it matters:** You can spot a newly-added or rogue script on a client site the moment you visit it — no need to open the dashboard.

---

## Feature 2 — Popup script list

**What it does:** Click the extension icon on any registered site to see a breakdown of all detected scripts — provider name, category, and source domain.

```
Digivault                              ⚙
─────────────────────────────────────────
  12 scripts detected    [1 unknown]

  Google Analytics     analytics    google-analytics.com
  Google Tag Manager   tag mgmt     googletagmanager.com
  Intercom             chat         widget.intercom.io
  unknown              unknown      cdn.mystery-vendor.io
  …and 8 more — see dashboard
                          Open dashboard →
```

**Why it matters:**
- Instantly see what's running on a client site during a site visit or audit
- The orange "unknown" badge flags scripts that Digivault hasn't classified — these are worth investigating
- Click **Open dashboard →** to jump straight to the full script history for that site

---

## Feature 3 — Password autofill

**What it does:** When you visit a login page for a site that has saved credentials in Digivault, a small green shield icon appears inside the username field. Click it to see your saved credentials and fill them in with one click.

**How to use it:**

1. Navigate to any login page (e.g. a client's WordPress admin, CMS, or tool)
2. A **green shield icon** appears inside the username/email field
3. Click the shield → a dropdown lists all saved credentials for this site
4. Click any credential → username and password are filled in automatically
5. Submit the login form as normal

**Keyboard navigation:** Use `↑` / `↓` to move through the dropdown, `Escape` to close it.

**Why it matters:**
- No more searching for passwords in spreadsheets, sticky notes, or chat messages
- Credentials are stored encrypted in Digivault's vault — the extension never stores plaintext passwords locally
- Every credential access is audit-logged (who filled what, when, from which IP)
- The "Viewer" role can use autofill but cannot reveal or copy the raw password

> To save credentials for a site, go to the Digivault dashboard → that website → **Credentials → Add**.

---

## Feature 4 — Auto-login to the Digivault web app

**What it does:** If you are already signed into the extension and you navigate to `https://digivault.digilatics.co/login`, the extension automatically logs you into the web app and redirects you to the dashboard — no password re-entry.

**How it works:**
1. Visit `https://digivault.digilatics.co/login`
2. The extension detects the login page
3. A secure one-time token is exchanged in the background (expires in 60 seconds)
4. You land directly on `/dashboard`

**Why it matters:** One login (in the extension options) gets you into both the extension and the web app. Switch between browser tabs and the dashboard without ever typing your password again.

---

## Feature 5 — Auth status in the popup

**What it does:** When you open the extension popup while on the Digivault website (`digivault.digilatics.co`), it shows your account status instead of the script list.

**Logged in:**
```
Digivault                              ⚙
─────────────────────────────────────
  you@example.com

  [ Open Dashboard → ]
  [ Sign out of extension ]
```

**Not logged in:**
```
Digivault                              ⚙
─────────────────────────────────────────
  Sign in to the extension to enable
  autofill on this site.

  [ Open Settings ]
```

---

## Managing credentials (dashboard)

The extension only **uses** credentials — it doesn't create them. To add, edit, or delete:

1. Open the Digivault dashboard → **Websites** → select a site
2. Go to the **Credentials** tab
3. Click **Add credential** → fill in label, type, login URL, username, password
4. Save — the credential is immediately available in the extension autofill

**Credential types** you can save: WordPress, cPanel, hosting panel, FTP/SFTP, database, email, DNS/domain, custom.

---

## Roles and permissions

| Action | Viewer | Developer | Manager | Owner |
|---|---|---|---|---|
| See script badge / popup | ✅ | ✅ | ✅ | ✅ |
| Use autofill (fills fields) | ✅ | ✅ | ✅ | ✅ |
| Reveal raw password | ❌ | ✅ | ✅ | ✅ |
| Add / edit credentials | ❌ | ✅ | ✅ | ✅ |
| View audit log | ❌ | ❌ | ✅ | ✅ |

---

## Settings

Open the extension options page (⚙ icon → Settings):

| Setting | Default | When to change |
|---|---|---|
| **Account** | — | Log in / log out |
| **API Server URL** | `https://digivault.digilatics.co` | Only if using a self-hosted or staging server |

---

## Troubleshooting

**"Could not reach server"** on login
→ Check the Server URL in Settings. If running locally, set it to `http://localhost:8000`.

**Badge not showing on a registered site**
→ Reload the tab. If still missing, check that the site's domain in the dashboard exactly matches (e.g. `example.com` not `www.example.com`).

**Autofill icon not appearing**
→ The page must have a visible password field with a preceding text/email field. Some login pages load forms dynamically — wait a moment and try again. Also confirm you are logged into the extension.

**Auto-login not redirecting**
→ The one-time code expires in 60 seconds. If the page loaded slowly, try visiting `/login` again.

**Extension errors after an update**
→ After reloading the extension in `chrome://extensions`, refresh any open tabs — the old content script loses its connection and must be reloaded with the page.
