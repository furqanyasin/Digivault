"""Script Intelligence Engine — classifies third-party script URLs.

Each entry is (pattern, provider_name, category).  Patterns are matched
against the full src URL in order; the first match wins.  The list is
ordered most-specific first so broad CDN patterns don't shadow specific ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from apps.scripts.models import Script

# ---------------------------------------------------------------------------
# Provider library
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ProviderEntry:
    pattern: re.Pattern
    provider: str
    category: str


def _e(pattern: str, provider: str, category: str) -> _ProviderEntry:
    return _ProviderEntry(re.compile(pattern, re.IGNORECASE), provider, category)


_C = Script.Category  # alias for brevity

# Order: most specific patterns first; unknown catch-all is applied separately.
_LIBRARY: tuple[_ProviderEntry, ...] = (
    # ---- Digivault ----------------------------------------------------------
    _e(r"cdn\.digivault\.digilatics\.co", "Digivault", _C.PERFORMANCE),

    # ---- Analytics ----------------------------------------------------------
    _e(r"google-analytics\.com/analytics\.js", "Google Universal Analytics", _C.ANALYTICS),
    _e(r"google-analytics\.com/gtag/js", "Google Analytics 4", _C.ANALYTICS),
    _e(r"googletagmanager\.com/gtag/js", "Google Analytics 4", _C.ANALYTICS),
    _e(r"ssl\.google-analytics\.com", "Google Universal Analytics", _C.ANALYTICS),
    _e(r"google-analytics\.com/ga\.js", "Google Universal Analytics", _C.ANALYTICS),
    _e(r"google-analytics\.com/urchin\.js", "Google Universal Analytics", _C.ANALYTICS),
    _e(r"js\.hs-analytics\.net", "HubSpot Analytics", _C.ANALYTICS),
    _e(r"cdn\.heapanalytics\.com", "Heap Analytics", _C.ANALYTICS),
    _e(r"cdn\.amplitude\.com", "Amplitude", _C.ANALYTICS),
    _e(r"cdn\.mixpanel\.com", "Mixpanel", _C.ANALYTICS),
    _e(r"cdn\.segment\.com/analytics\.js", "Segment", _C.ANALYTICS),
    _e(r"cdn\.segment\.io", "Segment", _C.ANALYTICS),
    _e(r"plausible\.io/js", "Plausible Analytics", _C.ANALYTICS),
    _e(r"cdn\.usefathom\.com", "Fathom Analytics", _C.ANALYTICS),
    _e(r"matomo\.js|piwik\.js", "Matomo", _C.ANALYTICS),
    _e(r"js\.piwikpro\.com", "Piwik PRO", _C.ANALYTICS),
    _e(r"mc\.yandex\.ru/metrika", "Yandex Metrica", _C.ANALYTICS),
    _e(r"cdn\.woopra\.com", "Woopra", _C.ANALYTICS),
    _e(r"static\.woopra\.com", "Woopra", _C.ANALYTICS),
    _e(r"clicky\.com/js", "Clicky", _C.ANALYTICS),
    _e(r"gosquared\.com/tracker", "GoSquared", _C.ANALYTICS),
    _e(r"cdn\.countly\.com", "Countly", _C.ANALYTICS),
    _e(r"cdn\.simpleanalytics\.io", "Simple Analytics", _C.ANALYTICS),
    _e(r"simpleanalyticscdn\.com", "Simple Analytics", _C.ANALYTICS),
    _e(r"omtrdc\.net|sc\.omtrdc\.net", "Adobe Analytics", _C.ANALYTICS),
    _e(r"2o7\.net", "Adobe Analytics", _C.ANALYTICS),
    _e(r"cdn\.evgnet\.com|tag\.crsspxl\.com", "Conversant", _C.ANALYTICS),
    _e(r"chartbeat\.com/js", "Chartbeat", _C.ANALYTICS),
    _e(r"static\.chartbeat\.com", "Chartbeat", _C.ANALYTICS),
    _e(r"cdn\.parsely\.com|pixel\.parsely\.com", "Parse.ly", _C.ANALYTICS),
    _e(r"d\.comscore\.com|sb\.scorecardresearch\.com", "comScore", _C.ANALYTICS),
    _e(r"js\.api\.here\.com", "HERE Analytics", _C.ANALYTICS),
    _e(r"cdn\.getinsights\.io", "Insights.io", _C.ANALYTICS),
    _e(r"js\.driftt\.com/include", "Drift Analytics", _C.ANALYTICS),
    _e(r"app\.posthog\.com/static", "PostHog", _C.ANALYTICS),
    _e(r"eu\.posthog\.com/static", "PostHog", _C.ANALYTICS),
    _e(r"js\.logr-ingest\.com", "Logrocket", _C.ANALYTICS),
    _e(r"cdn\.logrocket\.io", "Logrocket", _C.ANALYTICS),
    _e(r"cdn\.lr-intake\.com", "Logrocket", _C.ANALYTICS),
    _e(r"d2wy8f7a9ursnm\.cloudfront\.net", "Bugsnag", _C.ANALYTICS),
    _e(r"d2lmu4ou0ub9x\.cloudfront\.net", "Bugsnag", _C.ANALYTICS),
    _e(r"browser\.sentry-cdn\.com", "Sentry", _C.ANALYTICS),
    _e(r"js\.sentry-cdn\.com", "Sentry", _C.ANALYTICS),
    _e(r"cdn\.rollbar\.com", "Rollbar", _C.ANALYTICS),
    _e(r"cdn\.raygun\.io", "Raygun", _C.ANALYTICS),

    # ---- Tag Management -----------------------------------------------------
    _e(r"googletagmanager\.com/gtm\.js", "Google Tag Manager", _C.TAG_MANAGEMENT),
    _e(r"googletagmanager\.com/ns\.html", "Google Tag Manager", _C.TAG_MANAGEMENT),
    _e(r"www\.googletagservices\.com", "Google Publisher Tags", _C.TAG_MANAGEMENT),
    _e(r"tags\.tiqcdn\.com", "Tealium iQ", _C.TAG_MANAGEMENT),
    _e(r"assets\.adobedtm\.com", "Adobe Launch", _C.TAG_MANAGEMENT),
    _e(r"launch-cdn\.adobe\.com", "Adobe Launch", _C.TAG_MANAGEMENT),
    _e(r"jssdkcdns\.mparticle\.com", "mParticle", _C.TAG_MANAGEMENT),
    _e(r"cdn\.optimizely\.com", "Optimizely", _C.TAG_MANAGEMENT),
    _e(r"js\.optimizely\.com", "Optimizely", _C.TAG_MANAGEMENT),
    _e(r"cdn\.monetate\.net|se\.monetate\.net", "Monetate", _C.TAG_MANAGEMENT),
    _e(r"cdn\.eventsource\.com", "Segment Connections", _C.TAG_MANAGEMENT),
    _e(r"cdn\.rudderstack\.com|cdn\.rudderlabs\.com", "RudderStack", _C.TAG_MANAGEMENT),
    _e(r"js\.hs-banner\.com", "HubSpot Cookie Banner", _C.TAG_MANAGEMENT),

    # ---- A/B Testing & Personalisation --------------------------------------
    _e(r"cdn\.optimizely\.com/public/[0-9]", "Optimizely Web", _C.ANALYTICS),
    _e(r"cdn\.convertexperiments\.com", "Convert Experiments", _C.ANALYTICS),
    _e(r"vwo\.com/j/opt|dev\.visualwebsiteoptimizer\.com", "VWO", _C.ANALYTICS),
    _e(r"cdn\.abtasty\.com", "AB Tasty", _C.ANALYTICS),
    _e(r"app\.split\.io/sdk", "Split.io", _C.ANALYTICS),
    _e(r"cdn\.kameleoon\.com|kameleoon\.eu", "Kameleoon", _C.ANALYTICS),
    _e(r"dynamic\.yahoo\.com", "Yahoo Gemini", _C.ANALYTICS),
    _e(r"jnn-pa\.googleapis\.com", "Google Publisher Tag", _C.ADVERTISING),
    _e(r"www\.googleoptimize\.com|optimize\.google\.com", "Google Optimize", _C.ANALYTICS),
    _e(r"accounts\.google\.com/gsi", "Google Identity Services", _C.SECURITY),
    _e(r"apis\.google\.com/js/api", "Google API Client", _C.PERFORMANCE),
    _e(r"www\.gstatic\.com/firebasejs", "Firebase", _C.ANALYTICS),
    _e(r"firebaseapp\.com/__/firebase", "Firebase", _C.ANALYTICS),

    # ---- Advertising & Conversion -------------------------------------------
    _e(r"js\.hsadspixel\.net", "HubSpot Ads Pixel", _C.ADVERTISING),
    _e(r"connect\.facebook\.net", "Meta Pixel", _C.ADVERTISING),
    _e(r"fbevents\.js", "Meta Pixel", _C.ADVERTISING),
    _e(r"bat\.bing\.com/bat\.js", "Microsoft Bing UET", _C.ADVERTISING),
    _e(r"uetq|bingads\.com", "Microsoft Bing UET", _C.ADVERTISING),
    _e(r"snap\.licdn\.com", "LinkedIn Insight Tag", _C.ADVERTISING),
    _e(r"analytics\.tiktok\.com", "TikTok Pixel", _C.ADVERTISING),
    _e(r"static\.ads-twitter\.com", "Twitter/X Pixel", _C.ADVERTISING),
    _e(r"ct\.pinterest\.com", "Pinterest Tag", _C.ADVERTISING),
    _e(r"sc-static\.net/s2s\.js", "Snapchat Pixel", _C.ADVERTISING),
    _e(r"cdn\.branch\.io", "Branch", _C.ADVERTISING),
    _e(r"d\.adroll\.com", "AdRoll", _C.ADVERTISING),
    _e(r"s\.adroll\.com", "AdRoll", _C.ADVERTISING),
    _e(r"static\.criteo\.net", "Criteo", _C.ADVERTISING),
    _e(r"www\.googleadservices\.com/pagead/conversion", "Google Ads", _C.ADVERTISING),
    _e(r"googleads\.g\.doubleclick\.net", "Google Ads", _C.ADVERTISING),
    _e(r"google\.com/pagead", "Google AdSense", _C.ADVERTISING),
    _e(r"googlesyndication\.com", "Google AdSense", _C.ADVERTISING),
    _e(r"reddit\.com/ads/", "Reddit Ads Pixel", _C.ADVERTISING),
    _e(r"rdt\.js|redditstatic\.com", "Reddit Ads Pixel", _C.ADVERTISING),
    _e(r"static\.quora\.com/qevents\.js", "Quora Pixel", _C.ADVERTISING),
    _e(r"cdn\.amazon-adsystem\.com", "Amazon Attribution", _C.ADVERTISING),
    _e(r"widgets\.outbrain\.com", "Outbrain", _C.ADVERTISING),
    _e(r"cdn\.taboola\.com|trc\.taboola\.com", "Taboola", _C.ADVERTISING),
    _e(r"secure\.adnxs\.com|acdn\.adnxs\.com", "AppNexus / Xandr", _C.ADVERTISING),
    _e(r"cm\.g\.doubleclick\.net|securepubads\.g\.doubleclick\.net", "DV360 / DoubleClick", _C.ADVERTISING),
    _e(r"cdn\.adsafeprotected\.com", "DoubleVerify", _C.ADVERTISING),
    _e(r"s\.adnimation\.com|cdn\.sovrn\.com", "Sovrn", _C.ADVERTISING),
    _e(r"cdn\.jsdelivr\.net/npm/@sentry/tracing", "Sentry Tracing", _C.ANALYTICS),
    _e(r"static\.klaviyostatic\.com", "Klaviyo", _C.CRM),
    _e(r"cdn\.carbonads\.com|srv\.carbonads\.com", "Carbon Ads", _C.ADVERTISING),
    _e(r"pagead2\.googlesyndication\.com", "Google AdSense", _C.ADVERTISING),
    _e(r"partner\.googleadservices\.com", "Google Ads", _C.ADVERTISING),
    _e(r"cdn\.demdex\.net", "Adobe Audience Manager", _C.ADVERTISING),
    _e(r"tags\.bluekai\.com", "Oracle BlueKai", _C.ADVERTISING),
    _e(r"pixel\.mathtag\.com|sync\.mathtag\.com", "MediaMath", _C.ADVERTISING),
    _e(r"cdn\.tribalfusion\.com", "Exponential", _C.ADVERTISING),
    _e(r"secure\.quantserve\.com", "Quantcast", _C.ADVERTISING),
    _e(r"edge\.quantserve\.com", "Quantcast", _C.ADVERTISING),
    _e(r"cdn\.zemanta\.com", "Zemanta", _C.ADVERTISING),

    # ---- Session Recording / Heatmaps ---------------------------------------
    _e(r"static\.hotjar\.com", "Hotjar", _C.SESSION_RECORDING),
    _e(r"script\.hotjar\.com", "Hotjar", _C.SESSION_RECORDING),
    # www.clarity.ms/tag/<id> is the per-account tag; scripts.clarity.ms serves
    # the recorder library the tag then loads. Both halves are Clarity.
    _e(r"clarity\.ms/tag|scripts\.clarity\.ms", "Microsoft Clarity", _C.SESSION_RECORDING),
    _e(r"edge\.fullstory\.com", "FullStory", _C.SESSION_RECORDING),
    _e(r"rs\.fullstory\.com", "FullStory", _C.SESSION_RECORDING),
    _e(r"luckyorange\.com|luckyorange\.net", "Lucky Orange", _C.SESSION_RECORDING),
    _e(r"crazyegg\.com/pages/scripts", "Crazy Egg", _C.SESSION_RECORDING),
    _e(r"mouseflow\.com", "Mouseflow", _C.SESSION_RECORDING),
    _e(r"cdn\.smartlook\.com", "Smartlook", _C.SESSION_RECORDING),
    _e(r"rec\.smartlook\.com", "Smartlook", _C.SESSION_RECORDING),
    _e(r"inspectlet\.com", "Inspectlet", _C.SESSION_RECORDING),
    _e(r"cdn\.contentsquare\.net", "Contentsquare", _C.SESSION_RECORDING),
    _e(r"tag\.contentsquare\.net", "Contentsquare", _C.SESSION_RECORDING),
    _e(r"cdn\.quantummetric\.com", "Quantum Metric", _C.SESSION_RECORDING),
    _e(r"cdn\.glassboxdigital\.io", "Glassbox", _C.SESSION_RECORDING),
    _e(r"cdn\.sessioncam\.com", "SessionCam", _C.SESSION_RECORDING),
    _e(r"cdn\.decibelinsight\.net", "Decibel Insight", _C.SESSION_RECORDING),
    _e(r"cdn\.dynatrace\.com|rum\.dyntraces\.com", "Dynatrace RUM", _C.SESSION_RECORDING),
    _e(r"dynatrace-cdn\.com/api/rum", "Dynatrace RUM", _C.SESSION_RECORDING),
    _e(r"cdn\.appdynamics\.com", "AppDynamics RUM", _C.SESSION_RECORDING),
    _e(r"cdn\.newrelic\.com|js-agent\.newrelic\.com", "New Relic Browser", _C.SESSION_RECORDING),
    _e(r"cdn\.usabilla\.com", "Usabilla", _C.SESSION_RECORDING),
    _e(r"script\.usabilla\.com", "Usabilla", _C.SESSION_RECORDING),
    _e(r"cdn\.getfeedback\.com", "GetFeedback", _C.SESSION_RECORDING),

    # ---- Call & Conversion Tracking -----------------------------------------
    _e(r"whatconverts\.com", "WhatConverts", _C.CALL_TRACKING),
    _e(r"ksrndkehqnwntyxlhgto\.com", "WhatConverts", _C.CALL_TRACKING),
    _e(r"scripts\.iconnode\.com", "Iconnode", _C.CALL_TRACKING),
    _e(r"cdn\.callrail\.com", "CallRail", _C.CALL_TRACKING),
    _e(r"callrail\.com/js", "CallRail", _C.CALL_TRACKING),
    _e(r"scripts\.calltrackingmetrics\.com", "CallTrackingMetrics", _C.CALL_TRACKING),
    _e(r"calltrackingmetrics\.com/js", "CallTrackingMetrics", _C.CALL_TRACKING),
    _e(r"solutions\.invoca\.net", "Invoca", _C.CALL_TRACKING),
    _e(r"scripts\.infinity-tracking\.net", "Infinity Call Tracking", _C.CALL_TRACKING),
    _e(r"tags\.responsetap\.com", "ResponseTap", _C.CALL_TRACKING),
    _e(r"cdn\.dialogtech\.com", "DialogTech / Marchex", _C.CALL_TRACKING),
    _e(r"cdn\.marchex\.com", "Marchex", _C.CALL_TRACKING),
    _e(r"tracking\.marchex\.com", "Marchex", _C.CALL_TRACKING),
    _e(r"cdn\.mediahawk\.co\.uk", "Mediahawk", _C.CALL_TRACKING),
    _e(r"cdn\.phonexa\.com", "Phonexa", _C.CALL_TRACKING),
    _e(r"cdn\.nimbata\.com|nimbata\.com/js", "Nimbata", _C.CALL_TRACKING),
    _e(r"cdn\.novocall\.co", "Novocall", _C.CALL_TRACKING),
    _e(r"cdn\.retreaver\.com", "Retreaver", _C.CALL_TRACKING),
    _e(r"cdn\.ringba\.com", "Ringba", _C.CALL_TRACKING),
    _e(r"static\.leadinfo\.com|script\.leadinfo\.com", "Leadinfo", _C.CALL_TRACKING),
    _e(r"cdn\.ruler\.io|ruler\.io/js", "Ruler Analytics", _C.CALL_TRACKING),
    _e(r"cdn\.convirza\.com", "Convirza", _C.CALL_TRACKING),

    # ---- Chat & Support -----------------------------------------------------
    _e(r"widget\.intercom\.io", "Intercom", _C.CHAT),
    _e(r"js\.intercomcdn\.com", "Intercom", _C.CHAT),
    _e(r"static\.zdassets\.com", "Zendesk", _C.CHAT),
    _e(r"ekr\.zdassets\.com", "Zendesk", _C.CHAT),
    _e(r"js\.hs-scripts\.com", "HubSpot Live Chat", _C.CHAT),
    _e(r"code\.tidio\.co", "Tidio", _C.CHAT),
    _e(r"client\.crisp\.chat", "Crisp", _C.CHAT),
    _e(r"wchat\.freshchat\.com", "Freshchat", _C.CHAT),
    _e(r"js\.drift\.com", "Drift", _C.CHAT),
    _e(r"cdn\.livechatinc\.com", "LiveChat", _C.CHAT),
    _e(r"embed\.tawk\.to", "Tawk.to", _C.CHAT),
    _e(r"static\.olark\.com", "Olark", _C.CHAT),
    _e(r"sdk\.gorgias\.io", "Gorgias", _C.CHAT),
    _e(r"beacon-v2\.helpscout\.net", "Help Scout", _C.CHAT),
    _e(r"cdn\.podium\.com", "Podium", _C.CHAT),
    # GoHighLevel's widget CDN — chat widget, form loader and its phone-number
    # helper all ship from here on agency-built client sites.
    _e(r"leadconnectorhq\.com", "LeadConnector (GoHighLevel)", _C.CHAT),
    _e(r"cdn\.birdeye\.com", "BirdEye", _C.CHAT),
    _e(r"cdn\.front-chat\.com", "Front", _C.CHAT),
    _e(r"cdn\.statuspage\.io", "Statuspage", _C.CHAT),
    _e(r"cdn\.userlike\.com", "Userlike", _C.CHAT),
    _e(r"cdn\.zopim\.com|v2\.zopim\.com", "Zendesk Chat (Zopim)", _C.CHAT),
    _e(r"js\.pusher\.com", "Pusher", _C.CHAT),
    _e(r"cdn\.chatra\.io", "Chatra", _C.CHAT),
    _e(r"loader\.chatra\.com", "Chatra", _C.CHAT),
    _e(r"cdn\.smartsupp\.com", "Smartsupp", _C.CHAT),
    _e(r"widget\.kommunicate\.io", "Kommunicate", _C.CHAT),
    _e(r"cdn\.freshdesk\.com", "Freshdesk", _C.CHAT),
    _e(r"cdn\.re-engage\.io|js\.re-engage\.io", "Re:amaze", _C.CHAT),
    _e(r"chat\.rasa\.io|cdn\.rasa\.io", "Rasa", _C.CHAT),
    _e(r"widget\.uservoice\.com", "UserVoice", _C.CHAT),

    # ---- CRM & Marketing Automation -----------------------------------------
    _e(r"js\.hsforms\.net|js\.hubspot\.com", "HubSpot", _C.CRM),
    _e(r"pi\.pardot\.com", "Salesforce Pardot", _C.CRM),
    _e(r"trackcmp\.net", "ActiveCampaign", _C.CRM),
    # ActiveCampaign's site-messaging/personalisation stack. Same account as
    # trackcmp.net, different hosts — unrecognised, they arrived as the loudest
    # severity the dashboard has.
    _e(r"(^|\.)app-us1\.com", "ActiveCampaign", _C.CRM),
    _e(r"munchkin\.marketo\.net", "Marketo", _C.CRM),
    _e(r"static\.klaviyo\.com", "Klaviyo", _C.CRM),
    _e(r"cdn\.mailchimpapp\.com", "Mailchimp", _C.CRM),
    _e(r"omnisrc\.com", "Omnisend", _C.CRM),
    _e(r"cdn\.drip\.com", "Drip", _C.CRM),
    _e(r"app\.convertkit\.com", "ConvertKit", _C.CRM),
    _e(r"cdn\.getresponse\.com", "GetResponse", _C.CRM),
    _e(r"cdn\.sendinblue\.com|sibautomation\.com", "Brevo / Sendinblue", _C.CRM),
    _e(r"cdn\.activecampaign\.com", "ActiveCampaign", _C.CRM),
    _e(r"cdn\.mailerlite\.com", "MailerLite", _C.CRM),
    _e(r"static\.mailerlite\.com", "MailerLite", _C.CRM),
    _e(r"cdn\.salesmanago\.com", "SALESmanago", _C.CRM),
    _e(r"cdn\.dotdigital\.com", "Dotdigital", _C.CRM),
    _e(r"cdn\.emarsys\.net", "Emarsys (SAP)", _C.CRM),
    _e(r"js\.eloqua\.com", "Oracle Eloqua", _C.CRM),
    _e(r"tags\.w55c\.net", "DataXu", _C.CRM),
    _e(r"cdn\.hubapi\.com", "HubSpot API", _C.CRM),
    _e(r"cdn\.salesforce\.com|cdn\.krxd\.net", "Salesforce", _C.CRM),
    _e(r"cdn\.autopilothq\.com", "Autopilot", _C.CRM),

    # ---- Consent & Cookie Management ----------------------------------------
    _e(r"cdn\.cookielaw\.org|optanon\.blob\.core\.windows\.net", "OneTrust", _C.SECURITY),
    _e(r"consent\.cookiebot\.com", "Cookiebot", _C.SECURITY),
    _e(r"cdn\.cookieyes\.com", "CookieYes", _C.SECURITY),
    _e(r"cdn\.osano\.com", "Osano", _C.SECURITY),
    _e(r"cdn\.trustarc\.com|consent\.truste\.com", "TrustArc", _C.SECURITY),
    _e(r"cdn\.iubenda\.com|cs\.iubenda\.com", "iubenda", _C.SECURITY),
    _e(r"cdn\.termly\.io", "Termly", _C.SECURITY),
    _e(r"app\.usercentrics\.eu", "Usercentrics", _C.SECURITY),
    _e(r"consent\.didomi\.io", "Didomi", _C.SECURITY),
    _e(r"cdn\.quantcast\.com/choice", "Quantcast Choice", _C.SECURITY),

    # ---- Payments & E-commerce ----------------------------------------------
    _e(r"js\.stripe\.com", "Stripe", _C.PAYMENT),
    _e(r"www\.paypalobjects\.com", "PayPal", _C.PAYMENT),
    _e(r"js\.squarecdn\.com|web\.squarecdn\.com", "Square", _C.PAYMENT),
    _e(r"js\.braintreegateway\.com", "Braintree", _C.PAYMENT),
    _e(r"checkoutshopify\.com|cdn\.shopify\.com/s/trekkie", "Shopify", _C.PAYMENT),
    _e(r"checkout\.adyen\.com", "Adyen", _C.PAYMENT),
    _e(r"cdn\.worldpay\.com", "Worldpay", _C.PAYMENT),
    _e(r"cdn\.klarna\.com|x\.klarnacdn\.net", "Klarna", _C.PAYMENT),
    _e(r"cdn\.afterpay\.com|js\.afterpay\.com", "Afterpay", _C.PAYMENT),
    _e(r"cdn\.affirm\.com|cdn1\.affirm\.com", "Affirm", _C.PAYMENT),
    _e(r"cdn\.sezzle\.com", "Sezzle", _C.PAYMENT),
    _e(r"cdn\.bolt\.com", "Bolt Checkout", _C.PAYMENT),
    _e(r"cdn\.recurly\.com", "Recurly", _C.PAYMENT),
    _e(r"cdn\.chargebee\.com", "Chargebee", _C.PAYMENT),
    _e(r"cdn\.zuora\.com", "Zuora", _C.PAYMENT),
    _e(r"cdn\.authorize\.net", "Authorize.Net", _C.PAYMENT),
    _e(r"cdn\.2checkout\.com|cdn\.verifone\.com", "2Checkout / Verifone", _C.PAYMENT),
    _e(r"cdn\.payoneer\.com", "Payoneer", _C.PAYMENT),
    _e(r"cdn\.yotpo\.com", "Yotpo", _C.SOCIAL),
    _e(r"cdn\.shopifycloud\.com", "Shopify", _C.PAYMENT),
    _e(r"cdn\.bigcommerce\.com", "BigCommerce", _C.PAYMENT),
    _e(r"cdn\.ecwid\.com", "Ecwid", _C.PAYMENT),
    _e(r"cdn\.woocommerce\.com", "WooCommerce", _C.PAYMENT),

    # ---- SEO & Verification / Security --------------------------------------
    _e(r"www\.google\.com/recaptcha", "Google reCAPTCHA", _C.SECURITY),
    _e(r"recaptcha\.net/recaptcha", "Google reCAPTCHA", _C.SECURITY),
    _e(r"js\.hcaptcha\.com", "hCaptcha", _C.SECURITY),
    _e(r"challenges\.cloudflare\.com", "Cloudflare Turnstile", _C.SECURITY),
    _e(r"funcaptcha\.com|arkoselabs\.com", "FunCaptcha / Arkose", _C.SECURITY),
    _e(r"cdn\.sift\.com", "Sift Science", _C.SECURITY),
    _e(r"cdn\.signifyd\.com", "Signifyd", _C.SECURITY),
    _e(r"cdn\.forter\.com", "Forter", _C.SECURITY),
    _e(r"cdn\.riskified\.com", "Riskified", _C.SECURITY),
    _e(r"cdn\.ns1\.com", "NS1 Pulse", _C.SECURITY),

    # ---- Maps & Location ----------------------------------------------------
    _e(r"maps\.googleapis\.com/maps/api/js", "Google Maps", _C.PERFORMANCE),
    _e(r"api\.mapbox\.com", "Mapbox", _C.PERFORMANCE),
    _e(r"cdn\.leafletjs\.com|unpkg\.com/leaflet", "Leaflet Maps", _C.PERFORMANCE),
    _e(r"js\.here\.com/v3/3", "HERE Maps", _C.PERFORMANCE),
    _e(r"static\.openlayers\.org", "OpenLayers", _C.PERFORMANCE),
    _e(r"cdn\.maptiler\.com", "MapTiler", _C.PERFORMANCE),

    # ---- Video & Media ------------------------------------------------------
    _e(r"fast\.wistia\.net|fast\.wistia\.com", "Wistia", _C.PERFORMANCE),
    _e(r"player\.vimeo\.com/api", "Vimeo Player API", _C.PERFORMANCE),
    _e(r"www\.youtube\.com/iframe_api", "YouTube IFrame API", _C.PERFORMANCE),
    _e(r"s\.ytimg\.com/yts/jsbin", "YouTube", _C.PERFORMANCE),
    _e(r"cdn\.jwplayer\.com", "JW Player", _C.PERFORMANCE),
    _e(r"cdn\.brightcove\.com|players\.brightcove\.net", "Brightcove", _C.PERFORMANCE),
    _e(r"api\.dailymotion\.com|geo\.dailymotion\.com", "Dailymotion", _C.PERFORMANCE),
    _e(r"cdn\.vidyard\.com", "Vidyard", _C.PERFORMANCE),
    _e(r"cdn\.loom\.com", "Loom", _C.PERFORMANCE),
    _e(r"embed\.spotify\.com", "Spotify Embed", _C.PERFORMANCE),
    _e(r"cdn\.soundcloud\.com", "SoundCloud Embed", _C.PERFORMANCE),

    # ---- Performance & CDN --------------------------------------------------
    _e(r"ajax\.googleapis\.com/ajax/libs/jquery", "jQuery CDN", _C.PERFORMANCE),
    _e(r"code\.jquery\.com", "jQuery CDN", _C.PERFORMANCE),
    _e(r"maxcdn\.bootstrapcdn\.com|cdn\.jsdelivr\.net/npm/bootstrap", "Bootstrap CDN", _C.PERFORMANCE),
    _e(r"use\.fontawesome\.com|kit\.fontawesome\.com", "Font Awesome CDN", _C.PERFORMANCE),
    _e(r"cdnjs\.cloudflare\.com/ajax/libs/lodash", "Lodash CDN", _C.PERFORMANCE),
    _e(r"cdnjs\.cloudflare\.com/ajax/libs/moment\.js", "Moment.js CDN", _C.PERFORMANCE),
    _e(r"unpkg\.com/react|cdn\.jsdelivr\.net/npm/react", "React CDN", _C.PERFORMANCE),
    _e(r"rocket-loader\.cloudflare\.com", "Cloudflare Rocket Loader", _C.PERFORMANCE),
    _e(r"fonts\.googleapis\.com|fonts\.gstatic\.com", "Google Fonts", _C.PERFORMANCE),
    _e(r"cdn\.jsdelivr\.net", "jsDelivr CDN", _C.PERFORMANCE),
    _e(r"unpkg\.com", "unpkg CDN", _C.PERFORMANCE),
    _e(r"cdnjs\.cloudflare\.com", "Cloudflare cdnjs", _C.PERFORMANCE),
    _e(r"cdn\.cloudflare\.com", "Cloudflare CDN", _C.PERFORMANCE),
    _e(r"ajax\.aspnetcdn\.com", "Microsoft Ajax CDN", _C.PERFORMANCE),
    _e(r"cdn\.datatables\.net", "DataTables CDN", _C.PERFORMANCE),
    _e(r"cdn\.jsdelivr\.net/npm/vue", "Vue.js CDN", _C.PERFORMANCE),
    _e(r"unpkg\.com/vue|cdn\.jsdelivr\.net/npm/vue@", "Vue.js CDN", _C.PERFORMANCE),
    _e(r"ajax\.googleapis\.com/ajax/libs/angularjs", "AngularJS CDN", _C.PERFORMANCE),
    _e(r"unpkg\.com/alpinejs|cdn\.jsdelivr\.net/npm/alpinejs", "Alpine.js CDN", _C.PERFORMANCE),
    _e(r"cdn\.tailwindcss\.com", "Tailwind CSS CDN", _C.PERFORMANCE),
    _e(r"cdn\.polyfill\.io|polyfill\.io/v3", "Polyfill.io", _C.PERFORMANCE),
    _e(r"d3js\.org|cdn\.jsdelivr\.net/npm/d3", "D3.js CDN", _C.PERFORMANCE),
    _e(r"cdn\.jsdelivr\.net/npm/chart\.js|cdn\.chart\.js", "Chart.js CDN", _C.PERFORMANCE),
    _e(r"cdn\.highcharts\.com", "Highcharts CDN", _C.PERFORMANCE),
    _e(r"cdn\.amcharts\.com", "amCharts CDN", _C.PERFORMANCE),
    _e(r"ajax\.googleapis\.com/ajax/libs/swfobject", "SWFObject CDN", _C.PERFORMANCE),
    _e(r"cdnjs\.cloudflare\.com/ajax/libs/gsap", "GSAP CDN", _C.PERFORMANCE),
    _e(r"cdn\.jsdelivr\.net/npm/swiper", "Swiper CDN", _C.PERFORMANCE),
    _e(r"cdn\.jsdelivr\.net/npm/aos", "AOS CDN", _C.PERFORMANCE),
    _e(r"cdn\.vimeocdn\.com", "Vimeo CDN", _C.PERFORMANCE),
    _e(r"cdn\.speedcurve\.com", "SpeedCurve RUM", _C.PERFORMANCE),
    _e(r"cdn\.wp-rocket\.me|cdn\.rocketpreload\.com", "WP Rocket", _C.PERFORMANCE),
    _e(r"ajax\.cloudflare\.com", "Cloudflare AJAX", _C.PERFORMANCE),

    # ---- Social & Reviews ---------------------------------------------------
    _e(r"widget\.trustpilot\.com", "Trustpilot", _C.SOCIAL),
    _e(r"reviews\.io", "Reviews.io", _C.SOCIAL),
    _e(r"apis\.google\.com/js", "Google APIs", _C.SOCIAL),
    _e(r"platform\.twitter\.com/widgets\.js", "Twitter Widgets", _C.SOCIAL),
    _e(r"connect\.facebook\.net/[a-z_]+/sdk", "Facebook SDK", _C.SOCIAL),
    _e(r"platform\.linkedin\.com", "LinkedIn Follow", _C.SOCIAL),
    _e(r"snapwidget\.com", "SnapWidget", _C.SOCIAL),
    _e(r"www\.instagram\.com/embed\.js", "Instagram Embed", _C.SOCIAL),
    _e(r"www\.tiktok\.com/embed", "TikTok Embed", _C.SOCIAL),
    _e(r"assets\.pinterest\.com/js/pinit", "Pinterest Save Button", _C.SOCIAL),
    _e(r"apis\.google\.com/js/plusone", "Google+ (Legacy)", _C.SOCIAL),
    _e(r"cdn\.judge\.me", "Judge.me Reviews", _C.SOCIAL),
    _e(r"cdn\.okendo\.io", "Okendo Reviews", _C.SOCIAL),
    _e(r"cdn\.stamped\.io", "Stamped.io Reviews", _C.SOCIAL),
    _e(r"widget\.reviews\.co\.uk", "Reviews.co.uk", _C.SOCIAL),
    _e(r"cdn\.powerreviews\.com", "PowerReviews", _C.SOCIAL),
    _e(r"cdn\.reevoo\.com", "Reevoo", _C.SOCIAL),
    _e(r"cdn\.bazaarvoice\.com", "Bazaarvoice", _C.SOCIAL),
    _e(r"cdn\.yelp\.com", "Yelp Widget", _C.SOCIAL),
    _e(r"cdn\.addthis\.com", "AddThis", _C.SOCIAL),
    _e(r"cdn\.sharethis\.com", "ShareThis", _C.SOCIAL),
    _e(r"static\.addtoany\.com", "AddToAny", _C.SOCIAL),
    _e(r"cdn\.shareaholic\.com", "Shareaholic", _C.SOCIAL),
    _e(r"static\.sumo\.com|sumo\.com/scripts", "Sumo", _C.SOCIAL),
    _e(r"cdn\.referralcandy\.com", "ReferralCandy", _C.SOCIAL),
    _e(r"cdn\.refersion\.com", "Refersion", _C.SOCIAL),
    _e(r"cdn\.impact\.com|cdn\.impact-ad\.com", "Impact Radius", _C.ADVERTISING),
    _e(r"cdn\.shareasale\.com", "ShareASale", _C.ADVERTISING),
    _e(r"cdn\.cj\.com|www\.emjcd\.com", "CJ Affiliate", _C.ADVERTISING),
    _e(r"cdn\.rakutenadvertising\.com", "Rakuten Advertising", _C.ADVERTISING),
    _e(r"cdn\.awin1\.com|cdn\.awinapis\.com", "AWIN", _C.ADVERTISING),
    _e(r"cdn\.partnerize\.com", "Partnerize", _C.ADVERTISING),
    _e(r"cdn\.pepperjam\.com", "Pepperjam", _C.ADVERTISING),
    _e(r"cdn\.viglink\.com", "VigLink / Sovrn Commerce", _C.ADVERTISING),
    _e(r"cdn\.skimresources\.com", "Skimlinks", _C.ADVERTISING),

    # ---- Booking & Scheduling -----------------------------------------------
    _e(r"calendly\.com/assets/external", "Calendly", _C.CRM),
    _e(r"assets\.calendly\.com", "Calendly", _C.CRM),
    _e(r"static\.hsappstatic\.net", "HubSpot Meetings", _C.CRM),
    _e(r"cdn\.acuityscheduling\.com", "Acuity Scheduling", _C.CRM),
    _e(r"cdn\.squareup\.com/appointments", "Square Appointments", _C.CRM),

    # ---- Forms & Surveys ----------------------------------------------------
    _e(r"webforms\.pipedrive\.com|cdn\.forms-content\.sg-form\.com", "Pipedrive Forms", _C.CRM),
    _e(r"cdn\.jotfor\.ms|cdn\.jotform\.com", "JotForm", _C.CRM),
    _e(r"typeform\.com/embed", "Typeform", _C.CRM),
    _e(r"cdn\.surveymonkey\.com", "SurveyMonkey", _C.CRM),
    _e(r"forms\.app/static", "Forms.app", _C.CRM),
    _e(r"static\.wufoo\.com", "Wufoo", _C.CRM),
    _e(r"cdn\.formstack\.com", "Formstack", _C.CRM),
    _e(r"js\.hsforms\.com", "HubSpot Forms", _C.CRM),
    _e(r"cdn\.gravity\.com|cdn\.gravityforms\.com", "Gravity Forms", _C.CRM),
    _e(r"embed\.cognito\.forms\.com", "Cognito Forms", _C.CRM),

    # ---- Reputation & Reviews -----------------------------------------------
    _e(r"cdn\.widewail\.com", "Widewail", _C.SOCIAL),
    _e(r"cdn\.reviewtrackers\.com", "ReviewTrackers", _C.SOCIAL),
    _e(r"api\.snoball\.it", "Snoball Reviews", _C.SOCIAL),
    _e(r"cdn\.chatmeter\.com", "Chatmeter", _C.SOCIAL),
    _e(r"cdn\.brightlocal\.com", "BrightLocal", _C.SOCIAL),

    # ---- Google broad catch-all (after all specific google patterns) ---------
    _e(r"googleapis\.com", "Google APIs", _C.PERFORMANCE),
    _e(r"gstatic\.com", "Google Static CDN", _C.PERFORMANCE),
    _e(r"google\.com/js", "Google Script", _C.PERFORMANCE),
)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassificationResult:
    provider: str
    category: str
    is_known: bool


_UNKNOWN_RESULT = ClassificationResult(
    provider="unknown", category=Script.Category.UNKNOWN, is_known=False
)


class ScriptClassifier:
    """Classify a script source URL against the known provider library.

    Usage::

        result = ScriptClassifier.classify("https://www.googletagmanager.com/gtm.js?id=GTM-XXXX")
        result.provider   # "Google Tag Manager"
        result.category   # "tag_management"
        result.is_known   # True
    """

    @classmethod
    def classify(cls, src_url: str) -> ClassificationResult:
        """Return classification for a script URL. Never raises."""
        if not src_url:
            return _UNKNOWN_RESULT
        for entry in _LIBRARY:
            if entry.pattern.search(src_url):
                return ClassificationResult(
                    provider=entry.provider,
                    category=entry.category,
                    is_known=True,
                )
        return _UNKNOWN_RESULT

    @classmethod
    def extract_domain(cls, src_url: str) -> str:
        """Extract the hostname from a URL, returning empty string on failure."""
        try:
            return urlparse(src_url).netloc or ""
        except Exception:
            return ""

    @classmethod
    def is_critical_provider(cls, provider: str) -> bool:
        """Return True for providers whose removal is always high-severity."""
        critical = {
            "Google Analytics 4",
            "Google Universal Analytics",
            "Google Tag Manager",
            "Meta Pixel",
            "WhatConverts",
            "CallRail",
            "Stripe",
            "PayPal",
        }
        return provider in critical
