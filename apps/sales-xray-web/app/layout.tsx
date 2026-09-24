import type { Metadata } from "next";
import "@fontsource-variable/plus-jakarta-sans/wght.css";
import "./styles.css";
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
  return (
    <html lang="en">
      <body className="sales-xray-document">
        {liveDataMode ? <LiveDataBanner>{children}</LiveDataBanner> : children}
      </body>
    </html>
  );
}
