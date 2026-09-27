import type { Metadata } from "next";
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
import { ThemeProvider } from "./lightbox/theme-provider";
import { LiveDataBanner } from "./live-data-banner";
export const metadata: Metadata = {
  title: "Dipak’s Sales Xray · Authority Closers",
  description:
    "Review the conversation. Understand the evidence. Practice with purpose.",
  robots: { index: false, follow: false },
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
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
        <ThemeProvider controlEnabled={themeControl}>
          {/* The root layout persists across client navigation, so a live
              upload is owned here rather than by the page that started it. */}
          <UploadSessionProvider>
            {liveDataMode ? (
              <LiveDataBanner>{children}</LiveDataBanner>
            ) : (
              children
            )}
            <UploadIndicator />
          </UploadSessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
