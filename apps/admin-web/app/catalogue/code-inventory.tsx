/**
 * "From the code": what the catalogue generator found that no feature card
 * names yet, plus the API, settings, switches and releases it read. Staff
 * use it to spot what the catalogue is missing.
 */
import { CATALOGUE } from "./catalogue-data";
import styles from "./catalogue.module.css";

export function CodeInventory() {
  const { pages, api, settings, switches, releases, source } = CATALOGUE;
  return (
    <section className={styles.inventory} aria-labelledby="inventory-title">
      <header className={styles.inventoryHead}>
        <h2 id="inventory-title">From the code</h2>
        <p>
          Built by <code>scripts/catalogue/build_feature_catalogue.py</code>
          {source.commit ? ` at ${source.commit}` : ""}
          {source.date ? `, ${source.date.slice(0, 16).replace("T", " ")}` : ""}
          . Product words live in{" "}
          <code>scripts/catalogue/feature_seed.json</code>; status and versions
          come from the code and the releases on {source.main}.
        </p>
      </header>
      <div className={styles.inventoryGrid}>
        <div className={styles.glassPanel}>
          <h3>Screens per app</h3>
          <ul className={styles.meters}>
            {pages.map((app) => (
              <li key={app.key}>
                <span className={styles.meterHead}>
                  <strong>{app.app}</strong>
                  <span>
                    {app.named} of {app.pages} screens in a feature
                  </span>
                </span>
                <span
                  className={styles.meter}
                  style={{
                    ["--fill" as string]: `${app.pages ? (app.named / app.pages) * 100 : 0}%`,
                  }}
                  aria-hidden="true"
                />
                {app.unnamed.length ? (
                  <details className={styles.unnamed}>
                    <summary>{app.unnamed.length} not in a feature yet</summary>
                    <ul>
                      {app.unnamed.map((route) => (
                        <li key={route}>
                          <code>{route}</code>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
        <div className={styles.glassPanel}>
          <h3>API · {api.routes} routes</h3>
          <ul className={styles.bars}>
            {api.areas.slice(0, 14).map((area) => (
              <li key={area.prefix}>
                <code>{area.prefix}</code>
                <span
                  className={styles.bar}
                  style={{
                    ["--fill" as string]: `${(area.routes / (api.areas[0]?.routes || 1)) * 100}%`,
                  }}
                  aria-hidden="true"
                />
                <span className={styles.barValue}>{area.routes}</span>
              </li>
            ))}
          </ul>
          <h3>One-click settings</h3>
          <p className={styles.small}>
            {settings.map((s) => `${s.area} (${s.entries})`).join(" · ")}
          </p>
          <h3>Env switches</h3>
          <p className={styles.small}>
            {switches.map((name) => (
              <code key={name}>{name} </code>
            ))}
          </p>
        </div>
        <div className={`${styles.glassPanel} ${styles.releases}`}>
          <h3>Releases on main</h3>
          <ol>
            {releases.slice(0, 16).map((release) => (
              <li key={`${release.version}-${release.date}-${release.title}`}>
                <span className={styles.releaseHead}>
                  <strong>{release.version}</strong>
                  <span>{release.date}</span>
                </span>
                <span className={styles.small}>{release.title}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
