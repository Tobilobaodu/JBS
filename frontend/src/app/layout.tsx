import type { Metadata } from "next";
import { Anek_Tamil, Archivo, Cairo } from "next/font/google";
import "./globals.css";
import "@/styles/modernist.css";
import { Providers } from "./providers";
import { SiteChrome } from "@/components/site-chrome";
import { WebVitalsReporter } from "@/components/web-vitals-reporter";

// Modernist's stylesheet specifies Archivo 400/600/800 via a CSS @import;
// next/font/google self-hosts and preloads the same family/weights instead
// (see src/styles/modernist.css's header comment for why).
const archivo = Archivo({
  subsets: ["latin"],
  // 700 is used by the landing page's buttons and labels (Figma "Fix+Apply").
  weight: ["400", "600", "700", "800"],
  variable: "--font-archivo",
  display: "swap",
});

// Two accent faces only the landing page uses: Cairo for the big step
// numerals, Anek Tamil for company names on the job cards. preload is off
// so every other route doesn't download them up front.
const cairo = Cairo({
  subsets: ["latin"],
  weight: ["700"],
  variable: "--font-cairo",
  display: "swap",
  preload: false,
});
const anekTamil = Anek_Tamil({
  subsets: ["latin"],
  weight: ["500"],
  variable: "--font-anek-tamil",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: "CV Tailoring",
  description: "Evidence-backed CV tailoring and cover letters.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${archivo.variable} ${cairo.variable} ${anekTamil.variable} antialiased`}>
        <WebVitalsReporter />
        <Providers>
          <SiteChrome>{children}</SiteChrome>
        </Providers>
      </body>
    </html>
  );
}
