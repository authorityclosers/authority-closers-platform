import type { Metadata, Viewport } from "next";
import { Inter, Newsreader } from "next/font/google";
import Script from "next/script";

import "./styles.css";
import "./auth-clarity.css";
import "./onboarding-clarity.css";
import "./learner-clarity.css";
import "./learning-loop-runtime.css";
import "./course-surfaces.css";
import "./theme.css";
import "./learner-next-slice.css";
import "./progress-momentum.css";
import { DevStagingBridgeNotice } from "./components/dev-staging-bridge-notice";
import { PwaRegister } from "./components/pwa-register";
import { ThemeRuntime } from "./components/theme-runtime";
import { DevelopmentMediaBridgeProvider } from "./components/development-media-bridge";
import { resolveDevAuthBridgeConfig } from "./lib/dev-api-proxy";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const serif = Newsreader({ subsets: ["latin"], variable: "--font-serif" });

export const metadata: Metadata = {
  title: "Closers Academy · Cohorva",
  description: "Evidence-backed sales practice for deliberate professionals.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: [
      { url: "/brand/closers-academy-v0.1/icon-180.png", sizes: "180x180" },
    ],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Closers Academy",
  },
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#f7f8fa",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Only the non-secret exact local origin is serialized. Invalid opted-in
  // configuration throws rather than silently bypassing the bridge transport.
  const mediaBridge = resolveDevAuthBridgeConfig(
    process.env,
    process.env.NODE_ENV,
  );
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${sans.variable} ${serif.variable}`}
      suppressHydrationWarning
    >
      <head>
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <Script src="/theme-init.js" strategy="beforeInteractive" />
      </head>
      <body>
        <DevStagingBridgeNotice />
        <ThemeRuntime />
        <DevelopmentMediaBridgeProvider
          browserOrigin={mediaBridge?.browserOrigin ?? null}
        >
          {children}
        </DevelopmentMediaBridgeProvider>
        <PwaRegister />
      </body>
    </html>
  );
}
