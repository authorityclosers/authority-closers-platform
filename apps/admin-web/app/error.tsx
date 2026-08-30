"use client";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main
      className="route-boundary route-boundary-error"
      id="admin-content"
      aria-labelledby="error-title"
      tabIndex={-1}
    >
      <span className="route-boundary-code">Error / retryable boundary</span>
      <h1 id="error-title">The admin route could not be rendered.</h1>
      <p>
        No action was performed and no operational data is assumed. Retry the
        route, then escalate with the trace reference if the boundary repeats.
      </p>
      {error.digest ? (
        <code className="route-boundary-trace">Trace {error.digest}</code>
      ) : null}
      <button className="button" type="button" onClick={reset}>
        Retry route
      </button>
    </main>
  );
}
