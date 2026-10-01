import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  variable: "--font-ibm-plex-sans",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  // Resolves the relative /opengraph-image URLs above into absolute ones for
  // crawlers; set NEXT_PUBLIC_SITE_URL to the deployment origin in production
  // (falls back to localhost for local dev, matching Next's default).
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: "AWS Instance Advisor",
  description:
    "Describe your workload. Get a vetted compute, database, cache, and load-balancer recommendation — plus ready-to-apply Terraform.",
  // Static OG/Twitter metadata for the landing page and the results view it
  // renders.  The image comes from src/app/opengraph-image.tsx (file
  // convention — Next links it automatically); the /share/[jobId] route
  // overrides all of this with real job data.
  openGraph: {
    siteName: "AWS Instance Advisor",
    title: "AWS Instance Advisor",
    description:
      "Describe your workload. Get a vetted compute, database, cache, and load-balancer recommendation — plus ready-to-apply Terraform.",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "AWS Instance Advisor",
    description:
      "Describe your workload. Get a vetted compute, database, cache, and load-balancer recommendation — plus ready-to-apply Terraform.",
  },
  robots: "noindex",
};

export const viewport: Viewport = {
  themeColor: "#0F0F0E",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${ibmPlexSans.variable} ${ibmPlexMono.variable}`}
    >
      <body className="bg-canvas text-ink font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
