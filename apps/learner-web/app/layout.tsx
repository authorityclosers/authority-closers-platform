import type { Metadata, Viewport } from "next";
import { Inter, Newsreader } from "next/font/google";

import "./styles.css";
import "./auth-clarity.css";
import "./onboarding-clarity.css";
import "./learner-clarity.css";
import { PwaRegister } from "./components/pwa-register";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const serif = Newsreader({ subsets: ["latin"], variable: "--font-serif" });

export const metadata: Metadata = {
  title: "Authority Closers — Learning that changes the next conversation",
  description: "Evidence-backed sales practice for deliberate professionals.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "AC Learning",
  },
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#11140f",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>
        {children}
        <PwaRegister />
      </body>
    </html>
  );
}
