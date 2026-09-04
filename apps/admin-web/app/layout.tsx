import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";

import "./styles.css";
import { AdminDevelopmentBridgeNotice } from "./components/admin-development-bridge-notice";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = IBM_Plex_Mono({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = { title: "Authority Closers Operations" };

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
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
