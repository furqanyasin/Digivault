# 4. Security & Site Health

These tabs surface risk on each website. The WordPress‑specific ones only appear for
sites detected as WordPress, and only when they have data.

## Security (vulnerability scan)

**What it is:** a WordPress vulnerability scan (powered by the WPScan database) that
flags known CVEs in the site's core, plugins, and themes.

- Open a website → **Security** tab → run a scan (also kicked off by the main **Scan**).
- Findings are listed by severity (critical / high / medium / low) with the affected
  component and a reference.

**Get 100% benefit:** scan after you detect a new/changed plugin in the Change Log —
that's when freshly‑introduced vulnerabilities appear. Pair this with the Plugins tab
to know exactly what's installed.

**Requires:** a WPScan API key configured on the server (`WPSCAN_API_KEY`). Without
it, the scan is skipped.

## PHP Errors (WordPress)

**What it is:** a log of server‑side PHP errors (fatals, warnings) reported from the
site. The **PHP Errors** tab appears only for WordPress sites that actually have
errors.

- Errors are sanitized server‑side (emails/secrets/long digit runs redacted) and the
  ingest endpoint is rate‑limited and origin‑bound so only the real site can post.

**Note:** PHP errors require a small WordPress companion plugin on the site to send
them (the receiving endpoint exists in Stacks Monitor). If you haven't installed that
plugin, this tab stays hidden — which is expected.

## Site Events (WordPress)

**What it is:** a feed of notable WordPress events — plugin/core updates, logins,
setting changes — for an audit trail of what changed on the site and when. Same as
PHP Errors, it's fed by the WordPress companion plugin and the tab appears only when
events exist.

## CMS / platform detection

When you **Scan** a site, Stacks Monitor detects the platform from the page's
`generator` meta tag, response headers, and HTML fingerprints — WordPress, Shopify,
Wix, Webflow, Framer, Squarespace, or "other".

**Why it matters:** the platform controls which tabs show. WordPress‑only tabs
(**Plugins, PHP Errors, Site Events**) are hidden for non‑WordPress sites because
they don't apply.

**Get 100% benefit:** after adding or migrating a site, hit **Scan** once so the
platform is set correctly and the right tabs appear. Existing sites default to
"other" until their first scan — so a known WordPress site won't show its WP tabs
until you scan it.

## Gotchas

- **WP tabs missing on a WordPress site?** Run **Scan** to detect the platform; the
  tabs also require content (a detected plugin / an error / an event) before they show.
- **Security tab empty?** Confirm the WPScan key is set and the site is WordPress.
