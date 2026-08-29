import { Activity, BookOpenCheck, CircleAlert, UsersRound } from "lucide-react";
import Link from "next/link";
import { BrandMark } from "@ac/ui";

const metrics = [
  { label: "Learners requiring attention", value: "—", icon: CircleAlert },
  { label: "Active enrollments", value: "—", icon: UsersRound },
  { label: "Published programs", value: "—", icon: BookOpenCheck },
  { label: "Held jobs", value: "—", icon: Activity },
];

export default function AdminHome() {
  return (
    <main className="admin-shell">
      <aside>
        <Link
          className="brand"
          href="/"
          aria-label="Authority Closers operations home"
        >
          <BrandMark />
          AC / OPS
        </Link>
        <nav aria-label="Operations">
          <Link className="active" href="/">
            Overview
          </Link>
          <Link href="/people">People</Link>
          <Link href="/catalog">Catalog</Link>
          <Link href="/learning-operations">Learning operations</Link>
        </nav>
        <p>
          Restricted control plane
          <br />
          <span>Audit every intervention</span>
        </p>
      </aside>
      <section>
        <header>
          <div>
            <span className="kicker">Operational readiness</span>
            <h1>Learning operations</h1>
          </div>
          <span className="status">Environment / local</span>
        </header>
        <div className="metrics">
          {metrics.map(({ label, value, icon: Icon }) => (
            <article key={label}>
              <Icon size={18} />
              <span>{label}</span>
              <strong>{value}</strong>
            </article>
          ))}
        </div>
        <article className="empty-panel">
          <span>NO LIVE DATA</span>
          <h2>The control plane is wired, not fabricated.</h2>
          <p>
            Metrics appear only after the API returns authorized, tenant-scoped
            operational state.
          </p>
        </article>
      </section>
    </main>
  );
}
