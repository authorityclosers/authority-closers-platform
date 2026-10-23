import Link from "next/link";

import { PolicyFooter } from "../policy-footer";
import styles from "../policy-pages.module.css";

/**
 * Where Settings → Security → Delete account lands: the server has closed the
 * account and signed it out everywhere (/v1/me/account-deletion). A plain page
 * that needs no session, like the policy pages.
 */
export default function AccountClosedPage() {
  return (
    <main className={styles.page} data-policy-page="account-closed">
      <header className={styles.top}>
        <Link className={styles.brand} href="/">
          Sales X-Ray
        </Link>
      </header>
      <article className={styles.content}>
        <p className={styles.eyebrow}>Delete account</p>
        <h1>Your account is closed</h1>
        <p className={styles.updated}>
          You asked for your Sales X-Ray account to be deleted.
        </p>
        <div className={styles.sections}>
          <section className={styles.section}>
            <p>
              You’re signed out on every device, and nobody can sign in to it
              now. We delete your details, recordings, reports and leads within
              2 days. We’ve emailed you to confirm.
            </p>
            <p>
              Changed your mind? Write to admin@authorityclosers.com before
              then.
            </p>
          </section>
          <section className={styles.section}>
            <ul>
              <li>
                <a href="/data-deletion">How deletion works</a>
              </li>
              <li>
                <Link href="/">Back to Sales X-Ray</Link>
              </li>
            </ul>
          </section>
        </div>
      </article>
      <PolicyFooter />
    </main>
  );
}
