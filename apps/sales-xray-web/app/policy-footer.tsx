"use client";

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
    </footer>
  );
}
