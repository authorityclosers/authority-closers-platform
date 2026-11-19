"use client";

import { ParentLogo } from "./brand/parent-brand";
import styles from "./policy-pages.module.css";

const POLICY_LINKS = [
  ["Pricing", "/pricing"],
  ["Terms", "/terms"],
  ["Privacy", "/privacy"],
  ["Refunds", "/refunds"],
  ["Delivery", "/delivery"],
  ["Contact", "/contact"],
] as const;

export function PolicyFooter() {
  return (
    // Website chrome: the phone app hides it (in-app.ts).
    <footer className={`${styles.footer} sx-web-only`}>
      <nav aria-label="Sales Xray policy pages">
        <ul className={styles.footerLinks}>
          {POLICY_LINKS.map(([label, href]) => (
            <li key={href}>
              <a href={href}>{label}</a>
            </li>
          ))}
        </ul>
      </nav>
      {/* The company behind the policies (brand order, 19 Nov 2026). */}
      <p className={styles.footerBrand}>
        <ParentLogo />
      </p>
    </footer>
  );
}
