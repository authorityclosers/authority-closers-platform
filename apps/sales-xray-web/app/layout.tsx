import type { Metadata, Viewport } from "next";
import "@fontsource-variable/plus-jakarta-sans/wght.css";
import "@fontsource-variable/bricolage-grotesque/wght.css";
import "@fontsource-variable/newsreader/wght.css";
import "@fontsource-variable/noto-sans-devanagari/wght.css";
import "@fontsource-variable/noto-serif-devanagari/wght.css";
import "./lightbox/tokens.css";
import "./styles.css";
import { UploadSessionProvider } from "./hooks/upload-session";
import { UploadIndicator } from "./shell/upload-indicator";
import { themeControlEnabled, themeInitScript } from "./lightbox/theme";
import { earlyReadsScript } from "./early-reads";
import { sidebarInitScript } from "./shell/shell-store";
import { inAppInitScript } from "./in-app";
import { ThemeProvider } from "./lightbox/theme-provider";
import { LiveDataBanner } from "./live-data-banner";
import { AppSession } from "./app-session";
import { InitialSessionProvider } from "./initial-session";
import { DisplayDatesProvider } from "./display-clock";
import { serverDisplayDates, serverSession } from "./server-reads";
import { NoticeCenter } from "./notice-center";
export const metadata: Metadata = {
  title: "Sales Xray · Authority Closers",
  description:
    "Review the conversation. Understand the evidence. Practice with purpose.",
  robots: { index: false, follow: false },
};

/* Phones and a native wrapper (Capacitor): draw under the notch and home bar
   so the shell's safe-area padding applies, keep the browser chrome the
   app's colour, and let the keyboard shrink the layout rather than cover it.
   Zoom stays allowed for accessibility. */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f6fb" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0c0e" },
  ],
};
export default async function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // Where this server can read the API (dev), the session arrives with the
  // page, so pages that render their data on the server show it at once.
  // Dates in those pages are written as the browser will start writing them.
  const [initialSession, displayDates] = await Promise.all([
    serverSession(),
    serverDisplayDates(),
  ]);
  const liveDataMode = process.env.AC_SALES_XRAY_DEV_LIVE_DATA === "true";
  const themeControl = themeControlEnabled({
    NODE_ENV: process.env.NODE_ENV,
    AC_SALES_XRAY_THEME_PREVIEW: process.env.AC_SALES_XRAY_THEME_PREVIEW,
  });
  return (
    // data-lx-root keeps the learner-web embed tokens out of this document.
    // The pre-paint script may change the theme attributes before hydration.
    <html lang="en" data-lx-root="" data-theme="light" suppressHydrationWarning>
      <body className="sales-xray-document">
        {themeControl ? (
          <script
            id="sales-xray-theme-init"
            dangerouslySetInnerHTML={{ __html: themeInitScript() }}
          />
        ) : null}
        <script
          id="sales-xray-sidebar-init"
          dangerouslySetInnerHTML={{ __html: sidebarInitScript() }}
        />
        {/* Inside the phone app, website-only chrome is hidden from the
            first paint (html[data-sx-app], styles.css). */}
        <script
          id="sales-xray-app-init"
          dangerouslySetInnerHTML={{ __html: inAppInitScript() }}
        />
        {/* Starts this page's reads while the HTML is still arriving, so the
            app finds its data ready instead of asking after it starts. */}
        <script
          id="sales-xray-early-reads"
          dangerouslySetInnerHTML={{ __html: earlyReadsScript() }}
        />
        <ThemeProvider controlEnabled={themeControl}>
          {/* The root layout persists across client navigation, so a live
              upload is owned here rather than by the page that started it. */}
          <UploadSessionProvider>
            <InitialSessionProvider value={initialSession}>
              <DisplayDatesProvider value={displayDates}>
                <AppSession>
                  {liveDataMode ? (
                    <LiveDataBanner>{children}</LiveDataBanner>
                  ) : (
                    children
                  )}
                </AppSession>
              </DisplayDatesProvider>
            </InitialSessionProvider>
            <UploadIndicator />
            <NoticeCenter />
          </UploadSessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
