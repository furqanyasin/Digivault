# 3. Forms & Performance

## Forms

**What it is:** the snippet detects forms on each page and flags failed
submissions — without ever reading what visitors type.

### The three kinds of forms it finds

| Type | Badge | What's captured |
|------|-------|-----------------|
| **Native** `<form>` | `native` | Full: id, name, action, method, all fields |
| **Div‑based / JS** | `div-based` | Fields + container id; no real action |
| **Embedded (iframe)** | `embedded — HubSpot` | Provider + presence only — fields are **unreadable** across an iframe |

Open a website → **Forms** tab. Each row shows the page, method, how it was detected,
its fields, and when it was last seen.

**Get 100% benefit:** the "Detected as" badge tells you *why* a form looks the way it
does. If a HubSpot/Typeform form shows no fields, that's expected — cross‑origin
iframes can't be read by any in‑page script; you still get "there's a HubSpot form
here."

### Failed‑submission detection (Form Errors)

When a visitor submits and it fails server‑side (mail not sent, SMTP down, 5xx), a
red **Form Errors** card appears under the forms list with the source, message, page
and time.

- It listens for Contact Form 7's failure events, and for any form watches the page
  for failure phrases ("submission failed", "failed to send", "server error", SMTP,
  500–504) for ~20 s after submit.
- **Privacy:** it never reads field values — only the plugin's own status text — and
  the server redacts any email/phone/secret that leaks into that text before storing.
- **Noise filter:** ordinary validation messages ("field is required", "invalid
  email") are ignored; only genuine server‑side failures are recorded.

**Get 100% benefit:** this is your early warning that a client's contact form has
silently stopped emailing leads. Check it after any hosting/SMTP change. To test:
break the form's mail config and submit — the failure shows within moments.

## Performance

**What it is:** Lighthouse lab scores + real‑user (CrUX) field data + an automatic,
prioritized **Optimization Plan**.

Open a website → **Performance** tab. Toggle **Mobile / Desktop**, then **Run check**.

### What you see

- **Performance Score** ring (0–100) and a trend chart across checks.
- **Core Web Vitals & Metrics** — FCP, LCP, CLS, TBT, TTFB, Speed Index, INP — each
  rated Fast / Average / Slow.
- **Optimization Plan** — the headline feature. Every metric beyond Google's
  thresholds becomes a **High** or **Medium** card with: current value → target, why
  it matters, and concrete WordPress/Elementor fixes. Cards are ordered by real score
  impact (TBT and LCP carry the most weight), so fixing top‑to‑bottom moves the score
  fastest. An all‑green site shows a "within targets" card.
- **Real User Metrics (CrUX)** — p75 field data from real Chrome users. Click
  **Fetch CrUX**.

**Get 100% benefit:**
- Work the Optimization Plan **in order** — the first card is the biggest score win.
- Use **Mobile** numbers for the score that matters (Google ranks on mobile).
- Run a check, apply fixes, run again — the trend chart shows whether you moved it.
- The plan's fixes map directly to cache‑plugin/Elementor settings (defer JS, remove
  unused CSS, WebP + preload hero, `font-display: swap`, CDN, full‑page cache).

### How it works

Lab scores come from Google PageSpeed Insights (Lighthouse). CrUX is real‑user field
data Google only publishes once a site has enough traffic — low‑traffic sites show
"—", which is normal; rely on the lab numbers there.

## Gotchas

- **LCP huge (e.g. 30 s) but TTFB tiny?** The server is fast — it's a heavy
  above‑the‑fold asset/slider. The Optimization Plan's first card tells you what to do.
- **CrUX all "—":** not a bug — the site is below Google's traffic threshold for field
  data.
- **Forms tab empty:** see the snippet/traffic notes in
  [Websites & Scripts](02-websites-and-scripts.md).
