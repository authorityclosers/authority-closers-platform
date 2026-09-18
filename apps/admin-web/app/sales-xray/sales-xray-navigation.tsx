import Link from "next/link";

import styles from "./sales-xray-navigation.module.css";

export type SalesXraySection = "overview" | "settings" | "benchmark" | "review";

const sections: ReadonlyArray<{
  href: string;
  id: SalesXraySection;
  label: string;
}> = [
  { href: "/sales-xray", id: "overview", label: "Control center" },
  { href: "/sales-xray/settings", id: "settings", label: "Settings" },
  { href: "/sales-xray/benchmark", id: "benchmark", label: "Benchmarks" },
  { href: "/sales-xray/review", id: "review", label: "Reviewer queue" },
];

export function SalesXrayNavigation({ active }: { active: SalesXraySection }) {
  return (
    <nav className={styles.nav} aria-label="Sales Xray sections">
      {sections.map((section) => (
        <Link
          className={`${styles.link} ${section.id === active ? styles.active : ""}`}
          href={section.href}
          key={section.id}
          aria-current={section.id === active ? "page" : undefined}
        >
          {section.label}
        </Link>
      ))}
    </nav>
  );
}
