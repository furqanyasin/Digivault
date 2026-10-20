import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";

// Three faces, one job each — see the type notes in globals.css.
// next/font self-hosts the files at build time, so none of this costs a
// request to Google at runtime and none of it shifts layout while loading.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
  // Only code strings use it, so it is not worth a preload on every page.
  preload: false,
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://stacksmonitor.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Stacks Monitor: website monitoring for agencies",
    template: "%s | Stacks Monitor",
  },
  description:
    "Uptime, SSL and domain expiry, third-party script changes and a shared credentials vault for every client website, in one dashboard.",
  applicationName: "Stacks Monitor",
  openGraph: {
    type: "website",
    siteName: "Stacks Monitor",
    url: SITE_URL,
  },
  twitter: { card: "summary_large_image" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`h-full antialiased ${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-full bg-background text-foreground font-sans">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
