/**
 * The catalogue page's content: the hero with the code's numbers, the
 * searchable cards and "From the code". Shared by /catalogue and its
 * dev-only fixture.
 */
import Link from "next/link";

import { CATALOGUE } from "./catalogue-data";
import { CatalogueView } from "./catalogue-view";
import { CodeInventory } from "./code-inventory";
import styles from "./catalogue.module.css";

export function CatalogueBody({ query = "" }: { query?: string }) {
  const { counts, latest_release: latest } = CATALOGUE;
  const pages = CATALOGUE.pages.reduce((sum, app) => sum + app.pages, 0);
  return (
    <>
      <header className={styles.hero}>
        <p className={styles.kicker}>Feature catalogue · internal</p>
        <h1>Everything AC does</h1>
        <p className={styles.lede}>
          Every feature across Sales X-Ray, the Android app, Admin, the Academy
          and the platform, read from the code and the releases on main.
        </p>
        <Link className={styles.heroLink} href="/offers">
          Build an offer from these features in the Offer Studio →
        </Link>
        <ul className={styles.stats}>
          <li>
            <strong>{CATALOGUE.features.length}</strong>
            <span>features</span>
          </li>
          <li data-status="live">
            <strong>{counts.live}</strong>
            <span>live</span>
          </li>
          <li data-status="dev">
            <strong>{counts.dev}</strong>
            <span>on dev</span>
          </li>
          <li data-status="planned">
            <strong>{counts.planned}</strong>
            <span>planned</span>
          </li>
          <li>
            <strong>{pages}</strong>
            <span>screens</span>
          </li>
          <li>
            <strong>{CATALOGUE.api.routes}</strong>
            <span>API routes</span>
          </li>
          {latest ? (
            <li>
              <strong>{latest.version}</strong>
              <span>latest release · {latest.date}</span>
            </li>
          ) : null}
        </ul>
      </header>
      <CatalogueView initialQuery={query} />
      <CodeInventory />
    </>
  );
}
