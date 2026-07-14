// Shared option lists + tooltip copy for the client forms (new + detail).

export const HOSTING_OPTIONS = [
  { value: "_unknown", label: "Unknown" }, { value: "wpengine", label: "WPEngine" },
  { value: "siteground", label: "SiteGround" }, { value: "cloudways", label: "Cloudways" },
  { value: "bluehost", label: "Bluehost" }, { value: "godaddy", label: "GoDaddy" },
  { value: "squarespace", label: "Squarespace" }, { value: "wix", label: "Wix" },
  { value: "shopify", label: "Shopify" }, { value: "other", label: "Other" },
];

export const HOSTING_TOOLTIP =
  "Where the site is hosted — pick the provider, or “Other” to type one that isn't " +
  "listed. Applies whether Digilatics provides the hosting or the client owns it; " +
  "record how we get in under “Website access level” (e.g. Delegate access when the " +
  "client grants us access through the provider). Drives renewal reminders and the " +
  "hosting column across the app.";

export const STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "offboarded", label: "Offboarded" },
];

export const TIER_OPTIONS = [
  { value: "_none", label: "None" },
  { value: "gold", label: "Gold" },
  { value: "silver", label: "Silver" },
  { value: "bronze", label: "Bronze" },
];

export const ACCESS_LEVEL_OPTIONS = [
  { value: "_unknown", label: "Unknown" },
  { value: "full_admin", label: "Full admin" },
  { value: "delegate", label: "Delegate access" },
  { value: "none", label: "No access" },
];

export const ACCESS_LEVEL_TOOLTIP =
  "How we can get into the client's website/hosting. Full admin = our own admin " +
  "account. Delegate = access granted through the provider's delegate/collaborator " +
  "feature (e.g. GoDaddy Delegate, Cloudflare member) — no shared passwords. " +
  "No access = client manages it themselves.";

export const DEPARTMENT_OPTIONS = [
  { value: "seo", label: "SEO" },
  { value: "ads", label: "Ads" },
  { value: "dev", label: "Development" },
  { value: "content", label: "Content" },
];
