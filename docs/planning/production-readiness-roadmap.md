# Digivault — Internal Production Readiness Roadmap

**Version:** 1.0
**Status:** Internal Launch Plan
**Date:** June 2026

---

## Executive Summary

Digivault already contains a strong foundation: monitoring, security, performance tracking, credential management, script monitoring, domain intelligence, status pages, team management, Chrome extension support, and client management.

**The goal is not to build additional features before launch.**

The goal is to ensure every existing feature is:

- Fully functional
- Properly tested
- Secure
- Scalable
- Production ready
- Useful for daily agency operations

This document defines the work required to launch Digivault internally with confidence.

---

## Internal Launch Objectives

### Primary Goal

Create a single platform where the agency can manage — from one dashboard:

- Client websites
- Credentials
- Monitoring
- Performance
- Security
- Domains
- SSL certificates
- Team collaboration
- Client reporting

---

## Feature Verification Matrix

### 1. Authentication & Team Management

**Existing features:** User registration · Login · JWT authentication · Refresh tokens · Team creation · Team invitations · Team switching · RBAC permissions · TOTP 2FA · Backup codes

**Required improvements**

*Security*
- Remove JWT storage from localStorage
- Use HttpOnly cookies only
- Implement CSRF protection
- Session audit logs
- Device tracking

*Validation*
- Verify all role permissions
- Verify team isolation
- Verify invitation expiry
- Verify 2FA recovery flow

> ✅ **Launch requirement:** All authentication flows tested and working

---

### 2. Website Management

**Existing features:** Website registration · Platform detection · Site tokens · Tags · Notes · Health score

**Required improvements — add Website Profile** storing:
- Hosting provider
- DNS provider
- CDN provider
- Maintenance plan
- Website owner
- Developer assigned
- Support contact

> ✅ **Launch requirement:** Website creation and management fully operational

---

### 3. Script Monitoring

**Existing features:** Script detection · Script diffing · Script classification · Script reviews · Form detection

**Required improvements**

*Monitoring enhancements*
- Script approval workflow
- Bulk approve
- Bulk ignore
- Historical script timeline
- Alert suppression rules

*Reporting*
- Monthly script changes report

> ✅ **Launch requirement:** New script detection verified

---

### 4. Credentials Vault

**Existing features:** Encrypted storage · Sharing · Audit logging · Autofill

**Required improvements**

*Security*
- MultiFernet key rotation
- Emergency recovery process
- Credential expiry tracking

*Management — add:*
- Last password change date
- Password strength indicator
- Expiring credentials dashboard

> ✅ **Launch requirement:** Credential encryption verified

---

### 5. Domain Intelligence

**Existing features:** WHOIS lookup · Domain expiry tracking · SSL monitoring · Hosting detection

**Required improvements**

*Add alerts at:* 90 / 60 / 30 / 14 / 7 / 3 days

*Add dashboard — Central Renewal Center* tracking:
- Domains
- SSL certificates
- Hosting renewals
- Plugin licenses

> ✅ **Launch requirement:** Renewal alerts operational

---

### 6. Uptime Monitoring

**Existing features:** HTTP monitoring · Ping monitoring · SSL monitoring · Port monitoring

**Required improvements**

*Performance — create rollups:* Daily · Weekly · Monthly

*Data retention:*
- Raw data — 30 days
- Aggregated data — 12 months

> ✅ **Launch requirement:** Monitoring alerts verified

---

### 7. Notifications System

**Existing features:** Email · Slack · In-App

**Required improvements**

*Complete SMS support* — implement Twilio or Vonage, **OR** remove the SMS option completely.

*Unify notification system* — all modules should support: Email · Slack · In-App · SMS

> ✅ **Launch requirement:** Notification delivery verified

---

### 8. Performance Monitoring

**Existing features:** PageSpeed Insights · CrUX data · Core Web Vitals

**Required improvements — Trend analysis:**
- Weekly trends
- Monthly trends
- Performance regression alerts

> ✅ **Launch requirement:** Performance reports operational

---

### 9. Security Monitoring

**Existing features:** WPScan integration · Vulnerability detection · PHP error collection

**Required improvements**

*Security dashboard* — display Critical / High / Medium / Low issues

*Security score components:*
- Vulnerabilities
- SSL status
- Script risk
- PHP errors

> ✅ **Launch requirement:** Vulnerability scans operational

---

### 10. Status Pages

**Existing features:** Public status pages · Uptime charts

**Required improvements — add:**
- Branding
- Custom domains
- Incident reports
- Maintenance windows

> ✅ **Launch requirement:** Public status pages working

---

### 11. Client Management

**Existing features:** Client profiles · ClickUp integration

**Required improvements — add:**
- Assigned websites
- Assigned team members
- Monthly revenue
- Support tier
- Contract renewal date

> ✅ **Launch requirement:** Client management operational

---

### 12. Reporting System *(new feature)*

Create automated reports.

**Monthly report includes:**
- Website overview
- Uptime
- Security
- Performance
- Domain status, SSL, expiry
- Script changes (added / removed)
- Recommendations (security / performance)

**Export formats:** PDF · CSV

> ✅ **Launch requirement:** Automated reporting operational

---

### 13. Audit & Compliance

**Existing features:** Activity logs · Credential logs

**Required improvements — add:**
- Export logs
- Search logs
- User activity reports

> ✅ **Launch requirement:** Audit logging verified

---

### 14. Chrome Extension

**Existing features:** Autofill · Credential capture · Script detection · Password generator

**Required improvements**

*Security*
- Reduce permissions
- Validate origins
- Improve token handling

*UX*
- Faster login detection
- Better site recognition

> ✅ **Launch requirement:** Extension tested on WordPress · Shopify · Webflow · Wix · Framer

---

## New Agency Features

### Website Health Center
Single dashboard showing: uptime · security · performance · domain status · SSL status · script monitoring · overall health score (0–100, updated automatically).

### Renewal Center
Track domains · SSL · hosting · plugin licenses. Display: Expiring Soon · Expired · Renewed.

### Backup Monitoring
Track backup status · last backup · backup provider · recovery verification.

### Screenshot Monitoring
Daily screenshots. Detect: layout changes · white screens · missing pages.

---

## Infrastructure Improvements

**Database**
- Data retention policies
- Table partitioning
- Archive tables
- Aggregated monitoring data

**Monitoring** — install Sentry · Flower · Prometheus · Grafana. Monitor: API errors · Celery tasks · database performance · worker health.

**Security** — MultiFernet · rate limiting · payload validation · API abuse detection · secret rotation.

---

## Internal Launch Checklist

### Critical
- [ ] JWT cleanup completed
- [ ] Retention policies implemented
- [ ] Rollup jobs implemented
- [ ] Sentry installed
- [ ] Celery monitoring enabled
- [ ] Endpoint security reviewed
- [ ] Database backups configured
- [ ] SSL configured
- [ ] Monitoring verified

### Functional
- [ ] Website management tested
- [ ] Credential vault tested
- [ ] Script monitoring tested
- [ ] Uptime monitoring tested
- [ ] Performance monitoring tested
- [ ] Security scanning tested
- [ ] Notifications tested
- [ ] Status pages tested
- [ ] Chrome extension tested

### Reporting
- [ ] Monthly reports generated
- [ ] PDF export working
- [ ] CSV export working

### Operational
- [ ] Team onboarding documented
- [ ] Disaster recovery documented
- [ ] Key rotation documented
- [ ] Backup restoration tested

---

## Final Internal Launch Definition

Digivault is not just a monitoring platform. Digivault should become the agency's **centralized operations platform** for:

- Website management
- Security monitoring
- Performance monitoring
- Credential management
- Domain management
- Client management
- Reporting
- Team collaboration

**All existing features must be verified, tested, secured, monitored, and documented before expanding into new product areas.**
