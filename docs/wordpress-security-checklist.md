# WordPress Website Security Checklist

*With Why It Matters & How To Do It — written simply for the whole team*

Every task below includes a plain-language reason it matters and a simple way to actually do it. No technical background required — if a step needs a specialist (e.g. server config), that's noted.

---

## 🔴 Critical — Do First

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Update WordPress Core** | Old versions of WordPress often have known security holes. Hackers actively scan the internet looking for sites still running outdated versions. | Go to Dashboard > Updates in wp-admin and click "Update Now." Always take a backup first (see Backup section). |
| **Update Themes & Plugins** | Just like WordPress itself, outdated plugins and themes are one of the most common ways sites get hacked. | Go to Dashboard > Updates, update everything, then click through the site to make sure nothing broke. |
| **Remove Vulnerable Software** | Some plugins/themes get abandoned or have public vulnerabilities that will never be fixed — keeping them is like leaving a door unlocked. | Check plugins against a vulnerability database (e.g. WPScan) and delete or replace any flagged ones. |
| **Remove Unused Plugins & Themes** | Even inactive plugins/themes can still be used as an entry point by attackers, and they add clutter. | Go to Plugins/Themes, delete (not just deactivate) anything you no longer use. |
| **Malware Scan** | Malware can hide inside files or the database without any obvious signs, quietly stealing data or spamming visitors. | Run a full scan with a security plugin (e.g. Wordfence, Sucuri) or ask your host to run a server-side scan. |
| **File Integrity Check** | This shows if any core, theme, or plugin file has been secretly changed by an attacker. | Use a security plugin's file-integrity feature, or compare files against a fresh copy from WordPress.org/plugin repo. |
| **Admin User Audit** | Old or unknown admin accounts are a common way attackers keep hidden access to a hacked site. | Go to Users, review every Administrator account, and delete or downgrade any that shouldn't be there. |
| **Enable 2FA** | Passwords alone can be guessed, phished, or leaked. A second step blocks most automated attacks. | Install a 2FA plugin (or use one built into your security plugin) and require it for all admin-level users. |
| **Change Privileged Passwords** | If a password was ever exposed (old breach, shared insecurely), rotating it closes that door. | Update WordPress admin, hosting panel, SFTP/SSH, and database passwords using a password manager to generate strong ones. |
| **Security Plugin/Firewall** | A firewall blocks malicious traffic before it reaches your site, and ongoing scanning catches problems early. | Install a reputable plugin (Wordfence, Sucuri, iThemes Security) and turn on firewall, scanning, and login protection. |
| **Verify SSL/HTTPS** | Without HTTPS, data (including login details) can be intercepted between the visitor and the server. | Confirm a valid SSL certificate is installed and force HTTPS site-wide (in Settings > General and via redirects). |

---

## 🟠 Server & File Security

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Review File Permissions** | Overly open permissions let attackers (or other sites on shared hosting) modify your files. | Set folders to 755 and files to 644 (wp-config.php to 600 where possible); check with your host if unsure. |
| **Secure wp-config.php** | This file holds your database credentials and secret keys — it's a top target for attackers. | Move it above the web root if your host allows it, restrict access via .htaccess, and check for any lines you didn't add. |
| **Disable File Editing** | The built-in code editor lets anyone with admin access edit live site files — a common tool used after a break-in. | Add `define('DISALLOW_FILE_EDIT', true);` to wp-config.php. |
| **Audit .htaccess** | Attackers often insert hidden redirect or rewrite rules here to send visitors to spam or malware sites. | Open the file via SFTP and review every rule; remove anything you don't recognize and compare to a clean backup. |
| **Protect Uploads Directory** | The uploads folder should only ever hold media — PHP files there are almost always a sign of a hacked site. | Search wp-content/uploads for .php files and remove any found; block PHP execution in that folder (see below). |
| **Review Server Logs** | Logs reveal attack patterns (repeated login tries, scanning bots) before they succeed. | Check access and error logs in your hosting control panel weekly, or set up automated log alerts. |
| **Review Cron Jobs** | Attackers sometimes plant scheduled tasks that quietly reinfect the site after cleanup. | Check WordPress cron via a plugin (e.g. WP Crontrol) and server-level cron jobs in your hosting panel. |
| **Disable PHP Execution Where Appropriate** | This stops uploaded malicious scripts from ever being able to run, even if one slips through. | Add a small .htaccess rule (or host setting) that blocks PHP execution inside wp-content/uploads. |
| **Secure SFTP/SSH Access** | Weak or shared SFTP/SSH credentials are a direct route to every file on the server. | Use SSH keys instead of passwords where possible, and remove accounts for anyone who no longer needs access. |

---

## 🟡 Database Security & Cleanup

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Database Backup** | A safety net — if a change goes wrong, you can undo it instead of losing data permanently. | Export the database (via hosting panel, plugin, or command line) before any major change and store it safely. |
| **Database Cleanup** | Spam, old revisions, and leftover plugin data slow the site down and can hide malicious entries. | Use a plugin (e.g. WP-Optimize) or run SQL cleanup queries to remove clutter; always back up first. |
| **Review Database Users** | Extra or overly powerful database accounts are another way attackers can access your data. | Check database users in your hosting/phpMyAdmin panel and remove any that aren't needed. |
| **Check for Malicious Database Entries** | Some malware hides inside post content, options, or user tables instead of files, so a file scan alone can miss it. | Search the database for suspicious script tags, unknown admin users, or unfamiliar option entries. |
| **Limit Database Access** | The fewer people/systems that can reach the database directly, the smaller the risk of it being exposed. | Restrict database access to only the web server and trusted admins; avoid sharing raw credentials over chat/email. |

---

## 🔵 Backup & Recovery

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Automated Backups** | Manual backups get forgotten. Automation guarantees a recent copy always exists. | Set up a backup plugin or hosting-level backup on a daily or weekly schedule, depending on how often the site changes. |
| **Off-Site Backups** | If the server itself is compromised or fails, backups stored on the same server are useless. | Send backups to cloud storage (e.g. Google Drive, Dropbox, S3) separate from the hosting account. |
| **Multiple Backup Versions** | If a problem isn't noticed right away, you need an older restore point to go back to. | Keep at least 3–5 recent backups instead of only overwriting the last one. |
| **Test Restoration** | A backup you've never restored might not actually work when you need it. | Periodically restore a backup to a staging/test site to confirm it works end-to-end. |
| **Keep Clean Backups** | If every backup is made after an infection, you have nothing safe to roll back to. | Keep at least one verified backup from before any known issue, and re-verify backups after cleaning an infection. |
| **Backup Before Updates** | Updates occasionally break sites; a fresh backup means you can undo the change quickly. | Take a full backup immediately before updating WordPress core, themes, or plugins. |

---

## 🟣 Login & Access Security

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Strong Password Policy** | Weak, reused passwords are one of the easiest ways accounts get taken over. | Require long, unique passwords for every privileged account, ideally generated and stored in a password manager. |
| **2FA for Admins** | Same reasoning as above — even a stolen password isn't enough to log in with 2FA active. | Enforce 2FA for every user with an Administrator or Editor role. |
| **Limit Login Attempts** | Without a limit, bots can try thousands of password guesses automatically (brute-force attacks). | Use a plugin or firewall rule that locks out an IP after several failed login attempts. |
| **Monitor Failed Logins** | A spike in failed logins is often the first sign someone is trying to break in. | Turn on login-attempt logging/alerts in your security plugin and check it regularly. |
| **Least-Privilege Access** | Giving everyone Admin access means one compromised account can take down the whole site. | Assign the lowest WordPress role that still lets each person do their job (Author, Editor, etc.). |
| **Remove Former Team Members** | Old accounts left active after someone leaves are an unnecessary and often-forgotten risk. | Immediately delete or deactivate WordPress, hosting, and SFTP accounts when someone's access ends. |
| **Review Application/API Keys** | Unused keys and tokens are still valid ways into connected services if leaked or forgotten. | List all API keys/integrations in use and revoke any that are no longer needed. |

---

## 🟢 Website/Application Security

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Security Headers** | These headers tell browsers how to treat your site more safely, blocking several common attack types. | Add headers like HSTS, X-Content-Type-Options, and Referrer-Policy via .htaccess, server config, or a security plugin. |
| **Review REST/API Exposure** | The WordPress REST API can accidentally expose user data (like usernames) if left unrestricted. | Check which REST endpoints are public and restrict or disable ones that reveal more than necessary. |
| **Disable XML-RPC if Not Required** | XML-RPC is frequently abused for brute-force and DDoS-style attacks, and most sites don't need it. | Disable it via a security plugin or by blocking xmlrpc.php in .htaccess, unless you rely on it (e.g. Jetpack). |
| **Protect Sensitive Files** | Config, backup, and log files can contain passwords or other data that should never be public. | Block direct browser access to these file types using .htaccess rules or server configuration. |
| **Check Redirects** | Hackers often insert hidden redirects that send your visitors to spam or scam sites. | Browse the site from different pages/devices and check for any unexpected redirects; review .htaccess and plugin settings. |
| **Check Admin URLs** | The default /wp-admin login page is the first thing attackers try, making it a constant target. | Consider a plugin that changes the login URL, and add extra protection (like IP restriction) where practical. |
| **Review Third-Party Integrations** | Connected forms, payment systems, and analytics tools can be a hidden way data leaks or attackers get in. | List every integration in use, confirm it's still needed, and remove or update anything outdated. |

---

## 🧹 Performance & Maintenance

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Audit Website Storage** | Unused files pile up over time, taking up space and sometimes hiding old vulnerable code. | Check disk usage in your hosting panel and clear out old media, logs, and backups you don't need. |
| **Clean Media Library** | Duplicate and unused images slow down the site and backups without adding any value. | Use a media-cleanup plugin to find and safely remove unused/duplicate files. |
| **Clean Cache Files** | Old or corrupted cache files can cause outdated or broken pages to show visitors. | Clear the cache through your caching plugin or hosting panel after major changes. |
| **Review Plugin Stack** | Every extra plugin is one more piece of code that could have a vulnerability — fewer plugins means less risk. | List all active plugins and remove ones that overlap in function or are rarely used. |
| **Check PHP Version** | Old PHP versions no longer receive security patches, leaving the server itself exposed. | Check the current PHP version in your hosting panel and upgrade to a currently supported version. |
| **Fix PHP Errors** | Repeated errors can point to compatibility issues, misconfigurations, or even signs of tampering. | Review the PHP error log and resolve recurring warnings, ideally in a staging environment first. |
| **Check Rewrite Rules** | Broken or malicious rewrite rules can cause pages to fail or secretly redirect visitors. | Check Settings > Permalinks and review .htaccess rewrite rules for anything unexpected. |
| **Monitor Server Resources** | Sudden spikes in CPU, RAM, or database load can mean an attack or malware running in the background. | Check hosting dashboards regularly, or set up alerts for unusual resource usage. |

---

## 🔍 Ongoing Security Monitoring

| Task | Why We Need It | How We Implement It |
|---|---|---|
| **Scheduled Malware Scans** | Automatic, regular scans catch new infections quickly instead of relying on someone noticing something is wrong. | Set your security plugin to scan daily or weekly and email results automatically. |
| **File Change Monitoring** | Immediate alerts on file changes let you catch a hack in progress instead of finding out weeks later. | Enable file-change monitoring in your security plugin and set it to notify you by email/Slack. |
| **Login Monitoring** | Ongoing visibility into who's logging in (and failing to) helps catch break-in attempts early. | Turn on login logging in your security plugin and review it on a regular schedule. |
| **Security Alerts** | Being notified the moment something critical happens lets you react before real damage is done. | Enable notification settings in your security plugin for critical events and vulnerability disclosures. |
| **Monitor Google/Search Console** | Google often flags hacked sites before the owner even notices, protecting search visitors. | Check Google Search Console regularly for security issues, manual actions, or unexpected indexed pages. |
| **Review Hosting Logs** | Hosting-level logs show activity that WordPress itself can't see, like server-wide attack attempts. | Periodically download and review access/error/security logs from your hosting control panel. |
| **Vulnerability Monitoring** | New vulnerabilities are discovered constantly, even in plugins you already trust. | Subscribe to a vulnerability feed (e.g. WPScan, Patchstack) or use a plugin that checks automatically. |

---

## 📋 Monthly WordPress Security Checklist (Quick Reference)

Run through this short list every month for every active site. Each line maps back to a fuller item above if you need the "why" and "how" again.

- [ ] WordPress updated
- [ ] Plugins updated
- [ ] Themes updated
- [ ] Vulnerable plugins removed
- [ ] Malware scan completed
- [ ] Admin users reviewed
- [ ] 2FA verified
- [ ] Backups verified
- [ ] Restore test performed periodically
- [ ] Security logs reviewed
- [ ] PHP errors reviewed
- [ ] Disk/storage usage checked
- [ ] Database cleaned
- [ ] SSL verified
- [ ] Security plugin/firewall checked
- [ ] .htaccess and critical files checked
- [ ] Former user access removed
- [ ] Security vulnerabilities reviewed

---

## ⭐ Recommended Standard for Our Team

Turn this checklist into a Security QA review with three simple statuses so anyone on the team can read the result at a glance:

- ✅ **Pass** — no action needed
- ⚠️ **Needs Attention** — schedule a fix
- ❌ **Critical** — fix immediately

Have a developer run through the full checklist **before launch**, **after major migrations**, **after any security incident**, and **monthly** for every active client website. This also fits directly into a team website-monitoring dashboard.
