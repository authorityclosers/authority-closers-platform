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

export const metadata: Metadata = {
  title: "Cohorva · Academy Operations",
  icons: {
    icon: [{ url: "/brand/cohorva-v0.1/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/brand/cohorva-v0.1/icon-180.png", sizes: "180x180" }],
  },
};

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
