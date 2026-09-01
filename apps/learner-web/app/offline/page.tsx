import { CloudOff } from "lucide-react";
import Link from "next/link";

import { PublicShell } from "../components/site-shell";
import { ROUTES } from "../lib/routes";

export default function OfflinePage() {
  return (
    <PublicShell>
      <main id="main-content" className="narrow-main" tabIndex={-1}>
        <section className="surface-state surface-state--offline" role="status">
          <CloudOff size={28} aria-hidden="true" />
          <p className="eyebrow">
            <span aria-hidden="true" /> Offline
          </p>
          <h1>You are offline.</h1>
          <p>
            Reconnect before signing in, saving a workbook draft, or submitting
            implementation evidence. No local response is treated as canonical
            progress.
          </p>
          <Link className="button button--ink" href={ROUTES.home}>
            Retry the learner app
          </Link>
        </section>
      </main>
    </PublicShell>
  );
}
