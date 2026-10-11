import type { Metadata } from "next";
import {
  IBM_Plex_Mono,
  Noto_Sans_Devanagari,
  Plus_Jakarta_Sans,
} from "next/font/google";

import "./styles.css";
import "./ui/tokens.css";
import "./ui/sx-tokens.css";
import "./ui/legacy-bridge.css";
import { AdminDevelopmentBridgeNotice } from "./components/admin-development-bridge-notice";
import { ThemeScript } from "./ui/theme-script";

// Latin and Devanagari in one stack, so Hindi and Marathi names and quotes render cleanly.
const ui = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-ui",
  display: "swap",
});
const deva = Noto_Sans_Devanagari({
  subsets: ["devanagari"],
  variable: "--font-deva",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Authority Closers · Admin",
  icons: { icon: [{ url: "/brand/ac-v0.1/icon.svg", type: "image/svg+xml" }] },
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      data-console=""
      data-theme="light"
      suppressHydrationWarning
      className={`${ui.variable} ${deva.variable} ${mono.variable}`}
    >
      <head>
        <ThemeScript />
      </head>
      <body>
        <a className="skip-link" href="#admin-content">
          Skip to admin content
        </a>
        <AdminDevelopmentBridgeNotice />
        {children}
      </body>
    </html>
  );
}
