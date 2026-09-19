import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Research Orb · Think out loud",
  description: "Follow Jev routing, Paper2Agent source analysis, and cited research reports as they happen.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Browser scripts can add root attributes (for example, class="hydrated") before React starts.
  return <html lang="en" suppressHydrationWarning><body>{children}</body></html>;
}
