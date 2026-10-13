const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public data: unknown,
    message?: string
  ) {
    super(message ?? `HTTP ${status}`);
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  accessToken?: string
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };

  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    throw new ApiError(res.status, data);
  }

  if (res.status === 204) return undefined as T;
  const envelope = await res.json();
  // Django uses a custom renderer: { data: ..., errors: [], meta: {} }
  return (envelope?.data !== undefined ? envelope.data : envelope) as T;
}

/** One page plus the paginator metadata, for callers that need `next`. */
async function requestPage<T>(
  path: string,
  accessToken?: string
): Promise<{ data: T[]; next: string | null }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

  const res = await fetch(`${API_BASE}${path}`, { method: "GET", headers });
  if (!res.ok) {
    let data: unknown;
    try { data = await res.json(); } catch { data = null; }
    throw new ApiError(res.status, data);
  }
  const envelope = await res.json();
  const data = (envelope?.data !== undefined ? envelope.data : envelope) as T[];
  return { data: Array.isArray(data) ? data : [], next: envelope?.meta?.next ?? null };
}

/** What `api.get` resolves to when it is handed a list type — a string, so that
 * every use of the result is a compile error.
 *
 * Every list endpoint paginates at 25 and the pagination metadata lives in the
 * envelope's `meta`, so `data` comes back as a bare array either way: a
 * truncated read and a complete one are byte-identical in shape. No error, no
 * clue, no runtime check possible — the only place this can be caught is the
 * type system.
 *
 * It had to be. `getAll` existed and was documented, and twenty-four call sites
 * still used `get` for a list: notifications, alert rules, clients, the audit
 * log, the expiring-SSL/domain/hosting tables, team members, monitor checks,
 * status-page monitors. For an agency past twenty-five of anything, each of
 * those pages was quietly wrong.
 */
type ListEndpointsNeedGetAll =
  "api.get() reads page one only — use api.getAll() for a list endpoint";

export const api = {
  /** Fetch a single object.
   *
   * Passing an array type is rejected at compile time; see
   * `ListEndpointsNeedGetAll`. Use `getAll` for anything that returns a list.
   */
  get: <T>(path: string, token?: string) =>
    request<T extends readonly unknown[] ? ListEndpointsNeedGetAll : T>(
      path,
      { method: "GET" },
      token
    ),

  /** Fetch every page of a paginated list endpoint.
   *
   * `T` is the *element* type: `getAll<Website>(...)` resolves to `Website[]`.
   *
   * List endpoints page at 25 (StandardPagination), so a plain get() silently
   * truncates once a team passes 25 websites — the count and the grid both go
   * wrong with no error. Follows meta.next until exhausted.
   */
  getAll: async <T>(path: string, token?: string): Promise<T[]> => {
    const out: T[] = [];
    // Ask for the largest page the API allows (StandardPagination.max_page_size)
    // so the common case is a single round trip instead of one per 25 rows.
    const sep = path.includes("?") ? "&" : "?";
    let url: string | null = `${path}${sep}page_size=100`;
    // Hard stop so a malformed `next` can't spin forever.
    for (let i = 0; url && i < 50; i++) {
      const page: { data: T[]; next: string | null } = await requestPage<T>(url, token);
      out.push(...page.data);
      // `next` comes back absolute; strip the origin so API_BASE still applies.
      url = page.next ? page.next.replace(/^https?:\/\/[^/]+/, "") : null;
    }
    return out;
  },

  post: <T>(path: string, body: unknown, token?: string) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }, token),

  patch: <T>(path: string, body: unknown, token?: string) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }, token),

  put: <T>(path: string, body: unknown, token?: string) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }, token),

  delete: <T>(path: string, token?: string) =>
    request<T>(path, { method: "DELETE" }, token),
};

// ---- typed endpoints -------------------------------------------------------

export interface TokenPair {
  access: string;
  refresh: string;
}

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  timezone: string;
  active_team: string | null;
  created_at: string;
}

export interface Team {
  id: string;
  name: string;
  slug: string;
  plan: string;
  my_role?: string | null;
  // Effective feature keys for the requesting user — every role except owner is
  // gated by these, not just "custom". Drives nav and dashboard gating.
  my_features?: string[];
}

export interface Website {
  id: string;
  name: string;
  domain: string;
  platform: string;
  site_id: string;
  status: string;
  health_score: number;
  is_vip: boolean;
  /** Whether the snippet collects click / move / scroll behaviour for this
   *  site. Opt-in per site — off means the ingest answers 204 and stores
   *  nothing. Optional: the frontend deploys separately from the backend, so a
   *  frontend that ships first must still render. */
  heatmap_enabled?: boolean;
  notes: string;
  tags: string[];
  script_count: number;
  unknown_script_count: number;
  snippet_html: string;
  last_seen_at: string | null;
  snippet_status?: "not_installed" | "installed" | "stale";
  snippet_first_seen_at?: string | null;
  snippet_last_seen_at?: string | null;
  client: string | null;
  client_name: string | null;
  /** Hosting renewal typed on the owning client. Authoritative for hosting
   *  expiry — WHOIS and DNS cannot discover it. */
  client_hosting_renewal_date: string | null;
  notification_channel: string | null;
  notification_channel_name: string | null;
  uptime_notification_channel: string | null;
  uptime_notification_channel_name: string | null;
  wp_sso_configured: boolean;
  /** WP Connect snippet version this site last reported. 0 = never reported. */
  wp_connect_version?: number;
  /** Snippet rollout state, for the re-paste campaign. Optional: the frontend
   *  deploys separately from the backend, so a frontend that ships first must
   *  still render. */
  wp_connect_status?: "current" | "outdated" | "stale" | "absent";
  /** WP Connect heartbeat (apps/monitors/evidence.py): last report from the
   *  site, and the status it got loading its own homepage. Optional, as above. */
  wp_connect_last_ack?: string | null;
  wp_connect_loopback_status?: number | null;
  wp_connect_loopback_at?: string | null;
  status_page: { slug: string; name: string; status: string; monitor_count: number } | null;
  uptime_30d: number | null;
  ssl_days_until_expiry: number | null;
  created_at: string;
  updated_at: string;
}

export interface Script {
  id: string;
  src_url: string;
  canonical_url?: string;
  src_domain: string;
  provider: string;
  /** The vendor the provider belongs to — "Google" for Google Analytics 4,
   *  Google Tag Manager and Google Ads alike. Optional: an older backend
   *  omits it, so read it through providerLabel(). */
  provider_family?: string;
  /** Whether this script belongs on the tracking inventory (analytics, ads,
   *  tag managers, session recording, call tracking, chat, CRM, payment) as
   *  opposed to JS libraries, CDNs, fonts, players and widgets. Optional for
   *  the same deploy-skew reason — read it through isTrackedScript(). */
  is_tracked?: boolean;
  category: string;
  location: string;
  scope: string;
  is_async: boolean;
  is_defer: boolean;
  is_inline: boolean;
  wp_plugin: string;
  seen_on_pages: string[];
  is_active: boolean;
  review_status: "pending" | "approved" | "blocked" | "ignored";
  /** Heuristic injected-code flag set on ingest. Advisory — `suspicion_reasons`
   *  carries the justification and must be shown with it. */
  is_suspicious: boolean;
  suspicion_severity: string;
  suspicion_reasons: string[];
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
}

export interface ScriptChange {
  id: string;
  website: string;
  /** Attribution for the team-wide /changes/ list, which mixes sites. */
  website_name: string;
  change_type: string;
  severity: string;
  description: string;
  old_value: string | null;
  new_value: string | null;
  script: Script;
  is_acknowledged: boolean;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  acknowledged_by_email: string | null;
  created_at: string;
}

/** Mirrors NotificationSerializer. The delivery state is `delivery_status` —
 *  there is no `status` field, and reading one silently rendered a blank cell
 *  in the history table. */
export interface Notification {
  id: string;
  website: string | null;
  website_name: string;
  channel: string;
  delivery_status: string;
  delivered_at: string | null;
  change_description: string;
  change_severity: string;
  read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface AlertRule {
  id: string;
  name: string;
  website: string | null;
  website_domain: string;
  channel: string;
  min_severity: "critical" | "high" | "medium" | "low";
  change_types: string[];
  delivery_mode: "immediate" | "hourly_digest" | "daily_digest";
  is_active: boolean;
}

export interface Credential {
  id: string;
  website_id: string | null;
  website_name: string | null;
  // Optional: a backend that predates client folders / authenticator codes
  // omits them, and the frontend deploys separately.
  client_id?: string | null;
  client_name?: string | null;
  /** The vault folder it is filed in (user-made, LastPass-style). */
  folder_id?: string | null;
  folder_name?: string | null;
  /** One of the client departments ("seo", "dev", ...), or "" for unfiled. */
  department?: string;
  /** An authenticator secret is stored; the code comes from /totp. */
  has_totp?: boolean;
  /** Set while someone has reported the login as not working. */
  broken?: { at: string; by_email: string | null; note: string } | null;
  credential_type: string;
  label: string;
  login_url: string;
  created_at: string;
  updated_at: string;
}

/** A vault folder. `groups` is present for the owner only: who it is shared with. */
export interface VaultFolder {
  id: string;
  name: string;
  /** Credentials in it that the caller can see. */
  credential_count: number;
  groups: { grant_id: string; sub_team: string; sub_team_name: string; can_view_password: boolean }[] | null;
  /** People it is shared with directly. Present for managers and owners only. */
  members?: { user_id: string; name: string; email: string; can_view_password: boolean }[] | null;
  created_at?: string;
}

/** The current authenticator code for a credential. The secret never leaves the server. */
export interface TotpCode {
  code: string;
  period: number;
  expires_in: number;
}

export interface RevealedCredential {
  username: string;
  password: string;
  notes: string;
  password_hidden: boolean;
}

export interface CredentialShare {
  id: string;
  user_id: string;
  email: string;
  name: string;
  role: string;
  shared_by_email: string | null;
  can_view_password: boolean;
  /** Set on a temporary share (e.g. from an approved access request). */
  expires_at?: string | null;
  created_at: string;
}

export interface DomainInfo {
  id: string;
  registrar: string | null;
  registered_at: string | null;
  expires_at: string | null;
  domain_days_until_expiry: number | null;
  nameservers: string[];
  whois_privacy: boolean;
  auto_renew: boolean;
  hosting_provider: string | null;
  hosting_ip: string | null;
  server_location: string | null;
  hosting_expires_at: string | null;
  hosting_days_until_expiry: number | null;
  smtp_status: string | null;
  mx_hosts: string[];
  smtp_checked_at: string | null;
  /** Email authentication. Status is pass | missing | error — "error" means the
   *  DNS lookup failed, which is not the same as a domain having no policy. */
  spf_status: string;
  spf_record: string;
  dmarc_status: string;
  dmarc_record: string;
  dkim_status: string;
  dkim_selector: string;
  ssl_issuer: string | null;
  ssl_expires_at: string | null;
  ssl_days_until_expiry: number | null;
  ssl_auto_renew: boolean;
  uses_cloudflare: boolean;
  last_checked_at: string | null;
}

export interface TeamMember {
  id: string;
  user: {
    id: string;
    email: string;
    first_name: string;
    last_name: string;
    timezone: string;
  };
  role: string;
  feature_access: string[];
  effective_features: string[];
  totp_enabled: boolean;
  // Credential-access group. Optional because the frontend deploys separately
  // from the backend, so a build that ships first must still render.
  sub_team?: string | null;
  sub_team_name?: string | null;
  // A team can hold several owners; this marks the one `Team.owner` points at,
  // who cannot be demoted or removed. Optional for the same deploy-skew reason
  // as the fields above — an older backend simply omits it, and every member
  // then reads as a co-owner, which is the safe way round: the backend refuses
  // the call regardless.
  is_primary_owner?: boolean;
  created_at: string;
}

/** A named group of people inside a team, e.g. "Web Team". Governs credential
 *  access only: role and feature_access are unaffected by group membership. */
export interface SubTeam {
  id: string;
  name: string;
  description?: string;
  member_count?: number;
  created_at?: string;
}

/** A grant giving one SubTeam access to credentials. `scope` is "all" for a
 *  standing rule over the whole vault, "type" for every credential of one
 *  credential_type, or "credential" for a single one. `can_view_password`
 *  defaults to false server-side: the group can autofill but the dashboard
 *  hides the password. */
export interface CredentialGroupGrant {
  id: string;
  sub_team: string;
  sub_team_name?: string;
  scope: "all" | "type" | "credential";
  credential_type?: string;
  credential?: string | null;
  credential_label?: string | null;
  can_view_password: boolean;
  granted_by_email?: string | null;
  created_at?: string;
}

export interface TeamInvitation {
  id: string;
  email: string;
  role: string;
  invited_by: string;
  accepted: boolean;
  token: string;
  created_at: string;
  accept_url?: string;
}

export interface Monitor {
  id: string;
  name: string;
  url: string;
  monitor_type: "http" | "ping" | "port" | "ssl";
  expected_status_code: number;
  request_method: string;
  request_headers: Record<string, string>;
  keyword: string;
  port: number | null;
  check_interval: number;
  timeout: number;
  retry_count: number;
  /**
   * "blocked" means a named WAF answered instead of the site: we learned
   * nothing about the origin, so it is neither up nor down. Treat it as a
   * coverage gap to fix (see block_info), never as an outage.
   */
  status: "up" | "down" | "degraded" | "blocked" | "paused" | "pending";
  is_active: boolean;
  last_checked_at: string | null;
  last_response_time: number | null;
  recent_statuses: string[];
  uptime_24h: number | null;
  uptime_7d: number | null;
  uptime_30d: number | null;
  tags: string[];
  notes: string;
  /**
   * Who produced the current status because a firewall blocks our own check:
   * "google" (PageSpeed), "site" (WP Connect heartbeat), "visitors" (tracking
   * snippet). "" or absent for our own check.
   */
  last_checked_via?: string;
  /** Present only while status === "blocked": who is blocking us, and the fix. */
  block_info: {
    message: string;
    since: string;
    consecutive_blocks: number;
    help_url: string;
    /** Optional: the backend deploys separately and may not send these yet. */
    reason?: "firewall" | "visitors";
    vendor?: string;
    has_heartbeat?: boolean;
    has_snippet?: boolean;
    second_opinion_enabled?: boolean;
  } | null;
  /** Set for auto-provisioned monitors; null for standalone ones. */
  website: string | null;
  created_at: string;
  updated_at: string;
}

export interface PerformanceReport {
  id: string;
  url: string;
  strategy: "mobile" | "desktop";
  performance_score: number | null;
  fcp_ms: number | null;
  lcp_ms: number | null;
  cls_score: number | null;
  tbt_ms: number | null;
  ttfb_ms: number | null;
  si_ms: number | null;
  tti_ms: number | null;
  inp_ms: number | null;
  fcp_rating: "fast" | "average" | "slow" | "";
  lcp_rating: "fast" | "average" | "slow" | "";
  cls_rating: "fast" | "average" | "slow" | "";
  tbt_rating: "fast" | "average" | "slow" | "";
  error: string;
  checked_at: string;
}

export interface NotificationChannel {
  id: string;
  name: string;
  channel_type: "email" | "clickup";
  config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MonitorNotificationRule {
  id: string;
  monitor: string;
  channel: NotificationChannel;
  notify_on_down: boolean;
  notify_on_recovery: boolean;
  notify_on_degraded: boolean;
  created_at: string;
}

export interface MonitorCheck {
  id: string;
  status: "up" | "down" | "degraded" | "blocked";
  response_time_ms: number | null;
  status_code: number | null;
  error_message: string;
  /** "google" when Google checked it because a firewall blocks our IP. */
  checked_via?: string;
  checked_at: string;
}

export interface DetectedForm {
  id: string;
  page_url: string;
  form_id: string;
  form_name: string;
  form_action: string;
  form_method: string;
  detection_type: "native" | "dom" | "embedded";
  provider: string;
  /** Where this form delivers. Read from the page markup or from the site's own
   *  WordPress form plugin — see recipient_source. */
  recipients: { to: string[]; cc: string[]; bcc: string[] };
  /** Derived server-side from recipients.to[0]. Kept for compatibility with a
   *  frontend deployed ahead of the backend; prefer recipients. */
  recipient_email: string;
  /** How the recipient was learned, weakest to strongest. The page markup is
   *  only a proxy for a form's configuration; `wp_api` (the site's own plugin
   *  REST API, read with a vaulted Application Password) and `wordpress` (the
   *  WP Connect snippet) are the configuration itself. Blank when there is no
   *  recipient.
   *
   *  `wp_api` was missing here while being the only value the live sweep
   *  writes, so the UI's `=== "wordpress"` test never matched and every address
   *  actually read out of WordPress was labelled as coming from the markup. */
  recipient_source: "" | "page" | "wp_api" | "wordpress";
  is_managed: boolean;
  submission_count: number;
  last_submission_at: string | null;
  fields: { name: string; type: string; label: string; required: boolean }[];
  first_seen_at: string;
  last_seen_at: string;
}

export interface FormSubmissionError {
  id: string;
  /** Attribution for the team-wide /form-errors/ list, which mixes sites. */
  website: string;
  website_name: string;
  source: string;
  form_id: string;
  page_url: string;
  message: string;
  created_at: string;
}

export interface PhpError {
  id: string;
  level: "fatal" | "error" | "warning" | "notice" | "deprecated" | "info";
  message: string;
  file: string;
  line: number | null;
  url: string;
  captured_at: string;
}

export interface SiteEvent {
  id: string;
  event_type: string;
  summary: string;
  details: Record<string, unknown>;
  actor: string;
  severity: "info" | "warning" | "critical";
  occurred_at: string;
  created_at: string;
  /** How this was detected. "wp_connect" events carry an actor; "passive" ones
   *  are inferred from asset versions and never can. All optional — the
   *  frontend deploys separately, so a frontend ahead of the backend must
   *  still render. */
  source?: "passive" | "wp_connect" | "manual";
  category?: string;
  actor_ip?: string | null;
  actor_wp_id?: number | null;
  object_type?: string;
  object_id?: string;
}

/** One entry on the incident-correlation timeline. */
export interface TimelineEntry {
  kind: "site_event" | "php_error" | "monitor_check" | "script_change";
  at: string;
  title: string;
  severity?: string;
  category?: string;
  actor?: string;
  actor_ip?: string | null;
  source?: string;
  status?: string;
  status_code?: number | null;
  error_message?: string;
  change_type?: string;
  file?: string;
  line?: number | null;
}

export interface Timeline {
  around: string;
  window_minutes: number;
  entries: TimelineEntry[];
}

export interface VulnerabilityReport {
  id: string;
  component_type: "plugin" | "theme" | "core";
  component_name: string;
  component_version: string;
  cve_ids: string[];
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  description: string;
  fixed_in_version: string;
  source: string;
  references: string[];
  created_at: string;
}

export interface SiteScanState {
  last_scanned_at: string | null;
  scan_status: "never" | "running" | "done" | "failed";
  wp_version: string;
  wp_latest_version: string;
  wp_update_available: boolean;
  plugins_detected: string[];
  error: string;
}

export interface SecurityHeaderCheck {
  name: string;
  key: string;
  present: boolean;
  status: "pass" | "warn" | "fail";
  value: string;
  recommendation: string;
  weight: number;
}

export interface SecurityHeaderReport {
  last_checked_at: string | null;
  check_status: "never" | "running" | "done" | "failed";
  error: string;
  final_url: string;
  status_code: number | null;
  score: number;
  grade: string;
  headers: SecurityHeaderCheck[];
  pass_count: number;
  warn_count: number;
  fail_count: number;
}

export interface CruxReport {
  id: string;
  origin: string;
  lcp_p75_ms: number | null;
  fcp_p75_ms: number | null;
  cls_p75: number | null;
  inp_p75_ms: number | null;
  ttfb_p75_ms: number | null;
  fid_p75_ms: number | null;
  lcp_good: number | null;
  lcp_ni: number | null;
  lcp_poor: number | null;
  fcp_good: number | null;
  fcp_ni: number | null;
  fcp_poor: number | null;
  cls_good: number | null;
  cls_ni: number | null;
  cls_poor: number | null;
  inp_good: number | null;
  inp_ni: number | null;
  inp_poor: number | null;
  error: string;
  fetched_at: string;
}

export interface StatusPage {
  id: string;
  name: string;
  slug: string;
  description: string;
  allow_indexing: boolean;
  overall_status: "operational" | "degraded" | "outage";
  created_at: string;
  updated_at: string;
}

export interface StatusPageMonitor {
  id: string;
  monitor_id?: string;
  monitor_detail: Monitor;
  display_name: string;
  display_order: number;
  effective_name: string;
}

export interface UptimeBar {
  date: string;
  status: "up" | "down" | "degraded" | "no-data";
  down_minutes: number;
  degraded_minutes: number;
}

export interface PublicMonitor {
  id: string;
  name: string;
  status: "up" | "down" | "degraded" | "paused" | "pending";
  uptime_90d: number | null;
  uptime_bars: UptimeBar[];
  last_checked_at: string | null;
  last_response_time: number | null;
}

export interface PublicIncident {
  id: string;
  title: string;
  body: string;
  status: "investigating" | "identified" | "monitoring" | "resolved";
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface PublicMaintenance {
  id: string;
  title: string;
  message: string;
  scheduled_start: string;
  scheduled_end: string;
  is_active: boolean;
  created_at: string;
}

export interface PublicStatusPage {
  id: string;
  name: string;
  slug: string;
  description: string;
  allow_indexing: boolean;
  logo_url: string;
  brand_color: string;
  overall_status: "operational" | "degraded" | "outage";
  monitors: PublicMonitor[];
  incidents: PublicIncident[];
  maintenance: PublicMaintenance[];
  updated_at: string;
}

export const authApi = {
  refresh: (refresh: string) =>
    api.post<{ access: string }>("/api/v1/auth/token/refresh/", { refresh }),

  me: (token: string) => api.get<User>("/api/v1/auth/me/", token),
};

export const websitesApi = {
  list: (token: string) => api.getAll<Website>("/api/v1/websites/", token),
  create: (token: string, data: Partial<Website>) =>
    api.post<Website>("/api/v1/websites/", data, token),
  get: (token: string, id: string) =>
    api.get<Website>(`/api/v1/websites/${id}/`, token),
  update: (token: string, id: string, data: Partial<Website>) =>
    api.patch<Website>(`/api/v1/websites/${id}/`, data, token),
  delete: (token: string, id: string) =>
    api.delete(`/api/v1/websites/${id}/`, token),
};

export const scriptsApi = {
  list: (token: string, websiteId: string) =>
    api.getAll<Script>(`/api/v1/websites/${websiteId}/scripts/`, token),
  changes: (token: string, scriptId: string) =>
    api.getAll<ScriptChange>(`/api/v1/scripts/${scriptId}/changes/`, token),
  acknowledge: (token: string, changeId: string) =>
    api.post(`/api/v1/changes/${changeId}/acknowledge/`, {}, token),
};

export const alertsApi = {
  rules: (token: string) => api.getAll<AlertRule>("/api/v1/alert-rules/", token),
  createRule: (token: string, data: Partial<AlertRule>) =>
    api.post<AlertRule>("/api/v1/alert-rules/", data, token),
  notifications: (token: string) =>
    api.getAll<Notification>("/api/v1/notifications/", token),
};

export const statusPagesApi = {
  list: (token: string) => api.getAll<StatusPage>("/api/v1/status-pages/", token),
  create: (token: string, data: { name: string; slug: string; description?: string; allow_indexing?: boolean }) =>
    api.post<StatusPage>("/api/v1/status-pages/", data, token),
  get: (token: string, id: string) =>
    api.get<StatusPage>(`/api/v1/status-pages/${id}/`, token),
  update: (token: string, id: string, data: Partial<StatusPage>) =>
    api.patch<StatusPage>(`/api/v1/status-pages/${id}/`, data, token),
  delete: (token: string, id: string) =>
    api.delete(`/api/v1/status-pages/${id}/`, token),
  listMonitors: (token: string, pageId: string) =>
    api.getAll<StatusPageMonitor>(`/api/v1/status-pages/${pageId}/monitors/`, token),
  addMonitor: (token: string, pageId: string, data: { monitor_id: string; display_name?: string; display_order?: number }) =>
    api.post<StatusPageMonitor>(`/api/v1/status-pages/${pageId}/monitors/`, data, token),
  removeMonitor: (token: string, pageId: string, entryId: string) =>
    api.delete(`/api/v1/status-pages/${pageId}/monitors/${entryId}/`, token),
};
