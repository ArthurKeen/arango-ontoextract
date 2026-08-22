import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

/** Global brand font (Arango rule §2): Inter, self-hosted at build by next/font. */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

/** Prefix for static assets when ``NEXT_PUBLIC_BASE_PATH`` is set (manual CM bundle). */
function staticAsset(path: string): string {
  const base = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

export const metadata: Metadata = {
  title: "Arango-OntoExtract",
  description: "LLM-driven ontology extraction and curation platform",
  icons: {
    icon: staticAsset("/favicon.svg"),
    shortcut: staticAsset("/favicon.svg"),
  },
};

/**
 * Resolve the theme BEFORE first paint so the page never flashes the wrong one.
 *
 * This has to be an inline blocking script rather than a `useEffect`: React
 * effects run after hydration, which is several frames too late — the user
 * would see a white flash on every navigation in dark mode. Mirrors the model
 * in r2g's studio UI (stored choice, else OS preference, else light).
 */
const THEME_BOOTSTRAP = `(function(){try{
var s=localStorage.getItem('aoe.theme');
var t=s||((window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light');
document.documentElement.setAttribute('data-theme',t);
}catch(e){document.documentElement.setAttribute('data-theme','light');}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning: the bootstrap script sets `data-theme` on the
    // client before React hydrates, so the server-rendered <html> legitimately
    // differs from the client's. Scoped to this element only.
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
