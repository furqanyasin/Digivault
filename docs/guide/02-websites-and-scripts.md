# 2. Websites & Scripts

The core of Digivault: know exactly which third‑party scripts run on each client
site, and get alerted the moment that changes.

## Adding a website

1. **Websites → New website**. Enter a name and the domain (e.g. `clientsite.com`).
2. On save, Digivault automatically provisions an **uptime monitor** and a **public
   status page** for that site, and kicks off the first checks.

## Installing the tracking snippet (the most important step)

Each website has a one‑line snippet. **Until it's installed and a browser loads a
page, Digivault sees nothing.**

1. Open the website → **Setup** tab → copy the snippet. It looks like:
   ```html
   <script async src="https://digivault.digilatics.co/api/s.js" data-site="YOUR_SITE_ID"></script>
   ```
2. Paste it before `</body>` on **every page** of the client site (in WordPress:
   a header/footer code plugin, or your theme; in Elementor/Wix/etc.: the custom‑code
   area).
3. Click **Verify snippet** to confirm Digivault can see it on the homepage.

**Get 100% benefit:**
- Install it site‑wide, not just the homepage — page‑specific scripts (checkout,
  contact, landing pages) only get caught where the snippet runs.
- The snippet is tiny, loads `async`, and re‑checks on a delay + when popups open +
  for 30 s after load, so it catches scripts injected late by tag managers.

## The "Scan" button (one‑shot, no waiting)

Don't want to wait for traffic? On the website page, **Scan** fetches the homepage
server‑side and pulls its scripts immediately. Two things to know:

- Scan reads **scripts only** — never forms.
- Scan also **auto‑detects the CMS** (WordPress, Shopify, Wix, Webflow, Framer,
  Squarespace) and sets the platform, which controls the WordPress‑only tabs.

## Reading the script data

The top cards summarize the site; the tabs drill in:

- **Overview** — pending changes + top scripts.
- **Scripts (N)** — every active third‑party script, its **provider** and
  **category** (analytics, tag‑management, session‑recording, security…), where it
  loads, and how many pages it's on. Click a domain to see its individual files.
- **Change Log (N)** — the timeline of added / removed / modified scripts with a
  severity. Acknowledge changes to clear them.

Clicking the **Active scripts / Pending changes / Unknown scripts** cards jumps you
to the right tab.

## "Unknown scripts" and reviewing them

An **Unknown script** is one whose URL the classifier doesn't recognize (a script
it can't name). It's flagged so you can decide if it belongs.

1. Open the script → **Approve** (it's expected), **Block**, or **Ignore**.
2. Approving (or ignoring) **clears it from the "Unknown scripts" count** — the KPI
   shows only unknown scripts *still awaiting your review*.

**How it works:** "Unknown" = *unrecognized provider* **and** *not yet reviewed*.
Approving sets the review status, which removes it from the count immediately
(the page refreshes on approve). It stays cleared unless the script disappears and
later reappears.

**Get 100% benefit:** review unknowns promptly — an unexpected new script on a
checkout or login page is exactly the kind of supply‑chain change you want to catch.
GoHighLevel/`leadconnectorhq.com`, chat widgets, and pixels are common legitimate
"unknowns".

## Plugins tab (WordPress only)

When the site is WordPress and scripts load from `/wp-content/plugins/…`, a
**Plugins** tab lists the detected plugins. It only appears when there's something
to show.

## How detection works (so you trust it)

1. The snippet POSTs the page's scripts to the ingest API.
2. A raw **snapshot** is saved (kept 90 days), then a background job **diffs** the
   new script list against the previous one for that page.
3. New/removed/changed scripts become **change** records with a severity; alert
   rules then fire notifications.
4. A **classifier** names the provider/category from the URL.

## Gotchas

- **Forms show 0 but scripts work?** Scripts can arrive via the server‑side Scan;
  forms only come from the live snippet. Make sure the snippet is installed and a
  browser has loaded the page. See [Forms](03-forms-and-performance.md).
- **PPC / `noindex` landing pages:** `noindex` does **not** stop the snippet — it
  runs in real browsers regardless. Just make sure the snippet is on those pages.
- **Re‑added the same site?** Each site provisions one status page; duplicates were
  fixed, but you may need to re‑install the snippet if the `site_id` changed.
