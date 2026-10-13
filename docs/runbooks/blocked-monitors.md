# Runbook — sites whose firewall blocks our monitor

**Why:** SiteGround's anti-bot (and similar host firewalls) challenge our one
monitoring IP with an HTTP 202 captcha page. It judges the IP's reputation, so
no user agent or setting on our side clears it, and SiteGround has no customer
allowlist. Every other vendor (ManageWP, MainWP, mySites.guru) answers with a
support ticket per hosting account.

**What we do instead:** when our check comes back `blocked`, evidence that
never comes from our IP decides up or down (`apps/monitors/evidence.py`):

1. The WP Connect snippet's heartbeat. Every 5 minutes it loads the site's
   homepage from the site's own server and posts the result out to us. A
   firewall in front of the site sees neither request. Up, or down on a 5xx.
2. Real visitors. The tracking snippet posted from a browser in the last 10
   minutes. Up.
3. Google PageSpeed, if neither of those has anything fresh.

Only with none of the three is the check recorded as `blocked`. Silence is
never read as down.

## Turning it on

Do these after the deploy that ships migration `websites/0018`.

1. **Check the Google fallback works.** `PAGESPEED_API_KEY` must be set in
   `.env.production`. Without it, step 3 never answers. A blocked monitor's
   page says "Google second opinions are not configured" when it is missing.
2. **Re-paste WP Connect on every blocked WordPress site.** The heartbeat only
   exists in the current snippet. Websites list → any site badged
   **Re-paste snippet** → **Setup** tab → **WP Connect** → **Show snippet** →
   Copy → replace the old snippet in the client's WPCode / Code Snippets
   (replace it, do not add a second copy). Show snippet keeps the current
   secret; only **New secret** rotates it. Managers and owners only. Uptime → Monitors → "Blocked sites" lists blocked
   sites with no heartbeat yet, by firewall.
3. **Confirm it took.** Within about 10 minutes of the next visit to the site
   the badge clears, and the monitor reads **Up · via Site heartbeat**.

## Low-traffic sites

WordPress cron only runs when the site gets a request, and SiteGround's cache
can serve visitors without running PHP at all. A quiet site therefore sends
no heartbeat and falls back to Google. To give it a steady heartbeat, add a
real cron job on the hosting account (SiteGround: Site Tools → Devs → Cron
Jobs) that runs WordPress cron with PHP every 5 minutes, using the site's own
path from Site Tools:

```
php /home/customer/www/<domain>/public_html/wp-cron.php
```

Run it through `php`, not `wget`/`curl` against the site's URL: a web
request from the host can meet the same anti-bot challenge.

## Still blocked after all of this

A site with a heartbeat that still reads `blocked` means WordPress has gone
quiet: cron is not firing, or PHP is failing before WordPress loads. Look at
the site, not at the firewall. The SiteGround support ticket in the "Blocked
sites" panel is now the last resort, for sites that are not WordPress.
