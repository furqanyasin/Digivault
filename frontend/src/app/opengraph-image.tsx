import { ImageResponse } from "next/og";

export const alt = "Stacks Monitor: website monitoring for agencies";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Default social share card for every page that does not set its own.
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between",
          padding: 72, background: "linear-gradient(135deg, #1e1b4b 0%, #3730a3 55%, #6366f1 100%)", color: "white",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <svg width="72" height="72" viewBox="0 0 64 64" fill="none">
            <path d="M32 6 58 19 32 32 6 19Z" fill="#A5A6F6" />
            <path d="M6 31 32 44 58 31" stroke="#A5A6F6" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M6 43 32 56 58 43" stroke="#A5A6F6" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
          </svg>
          <span style={{ fontSize: 40, fontWeight: 700 }}>Stacks Monitor</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <span style={{ fontSize: 68, fontWeight: 800, lineHeight: 1.05, maxWidth: 950 }}>
            Every client website, monitored in one dashboard
          </span>
          <span style={{ fontSize: 30, opacity: 0.85 }}>
            Uptime · SSL and domain expiry · Script changes · Credentials vault
          </span>
        </div>
      </div>
    ),
    size,
  );
}
