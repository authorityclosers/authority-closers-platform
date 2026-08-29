import type { Metadata } from "next";
import { Manrope, Newsreader } from "next/font/google";

import "./styles.css";

const sans = Manrope({ subsets: ["latin"], variable: "--font-sans" });
const serif = Newsreader({ subsets: ["latin"], variable: "--font-serif" });

export const metadata: Metadata = {
  title: "Authority Closers — Learning that changes the next conversation",
  description: "Evidence-backed sales practice for deliberate professionals.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>{children}</body>
    </html>
  );
}
