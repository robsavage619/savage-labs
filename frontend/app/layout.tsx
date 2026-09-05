import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { TactileFeedback } from "@/components/tactile-feedback";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Savage Labs",
  description: "Personal health intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full`}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/* Load every weight the CSS actually asks for. Loading 900 alone meant
            .eyebrow (500), .shc-section-title (600), .metric-* (500) and the
            header HUD (500/700) all rendered synthesized or silently Black. */}
        <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700;900&display=swap" rel="stylesheet" />
      </head>
      <body className="min-h-full bg-[var(--bg)] text-[var(--foreground)] antialiased">
        <TactileFeedback />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
