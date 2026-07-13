=== Digivault Connect ===
Contributors: digilatics
Tags: sso, login, agency, admin
Requires at least: 6.0
Tested up to: 6.7
Requires PHP: 7.4
Stable tag: 1.0.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

One-click, role-mapped login into wp-admin from the Digivault agency dashboard. No shared passwords.

== Description ==

Digivault Connect lets your agency's team members log into this site's wp-admin
directly from the Digivault dashboard with a single click.

* Login links are signed with a per-site shared secret (HMAC-SHA256).
* Every link is single-use and expires after two minutes.
* Digivault roles map to WordPress roles (owners/managers → administrator,
  developers → editor) — new team members never need this site's passwords.
* Configuration is a single field: paste the shared secret generated in the
  Digivault dashboard under Settings → Digivault Connect.

== Installation ==

1. Upload the `digivault-connect` folder to `/wp-content/plugins/`.
2. Activate the plugin through the Plugins menu.
3. In the Digivault dashboard, open the website's Access tab and generate the
   WP Admin login secret.
4. Paste the secret under Settings → Digivault Connect and save.

== Frequently Asked Questions ==

= What happens if the secret leaks? =

Generate a new secret in Digivault and paste it here — all previously issued
links become invalid immediately.

= Does this phone home? =

No. The plugin makes no outbound requests; it only validates signed links that
arrive at its REST endpoint.

== Changelog ==

= 1.0.0 =
* Initial release: HMAC-signed single-use SSO endpoint + settings page.
