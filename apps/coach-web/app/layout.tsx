import type { Metadata } from "next";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import "@ac/operations-web/styles.css";
import "./styles.css";
const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = IBM_Plex_Mono({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-mono",
});
export const metadata: Metadata = {
  title: "Academy Studio · Cohorva",
  robots: { index: false, follow: false },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <a className="skip-link" href="#admin-content">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
