import type { Metadata, Viewport } from "next";
import { Fraunces, Instrument_Sans } from "next/font/google";
import "./globals.css";

const display = Fraunces({ subsets: ["latin"], axes: ["opsz"], variable: "--font-display", display: "swap" });
const text = Instrument_Sans({ subsets: ["latin"], variable: "--font-text", display: "swap" });

export const metadata: Metadata = {
  title: "ATLAS 2050 | Ce que la Gironde vaut, et ce qu'on ne sait pas encore",
  description:
    "Prix immobiliers relevés sur les ventes DVF de Gironde, estimation d'un bien en fourchette et projection 2050 honnête : ce qui n'est pas mesuré reste en blanc.",
  applicationName: "ATLAS 2050",
};

export const viewport: Viewport = {
  themeColor: "#07090d",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr" className={`${display.variable} ${text.variable}`}>
      <body>{children}</body>
    </html>
  );
}
