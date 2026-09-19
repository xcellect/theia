import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Voice AI · Practice",
  description: "A local practice space for Hume EVI voice conversations. Live audio requires your configured Hume account.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
