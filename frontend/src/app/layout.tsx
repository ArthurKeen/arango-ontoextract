import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Arango-OntoExtract",
  description: "LLM-driven ontology extraction and curation platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
