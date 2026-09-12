import type { Metadata } from "next";
import "./styles.css";
export const metadata: Metadata = {
  title: "Dipak’s Sales Xray · Authority Closers",
  description:
    "Review the conversation. Understand the evidence. Practice with purpose.",
  robots: { index: false, follow: false },
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="sales-xray-document">{children}</body>
    </html>
  );
}
