import { notFound } from "next/navigation";
import Link from "next/link";
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <main style={{ maxWidth: 480, margin: "48px auto", padding: 24 }}>
      <h1>Fictional Pulse approval</h1>
      <p>
        Dev fixture only. This checks navigation; it does not link a real
        organisation.
      </p>
      <p>Allow Sales X-Ray to read Sample Office’s directory?</p>
      <form action="/organisation/review" method="get">
        <input type="hidden" name="tab" value="connections" />
        <input type="hidden" name="part" value="pulse" />
        <input type="hidden" name="pulse" value="connected" />
        <button type="submit">Allow fictional link</button>
      </form>
      <p>
        <Link href="/organisation/review?tab=connections&part=pulse&pulse=cancelled">
          Cancel
        </Link>
      </p>
    </main>
  );
}
