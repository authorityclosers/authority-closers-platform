import Link from "next/link";

export default function NotFound() {
  return (
    <main
      className="route-boundary"
      id="admin-content"
      aria-labelledby="not-found-title"
      tabIndex={-1}
    >
      <span className="route-boundary-code">Not found / route boundary</span>
      <h1 id="not-found-title">This admin route is outside the G1 surface.</h1>
      <p>
        No fallback operation is inferred. Return to the narrow admin overview.
      </p>
      <Link className="button" href="/">
        Return to overview
      </Link>
    </main>
  );
}
