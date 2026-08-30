export default function Loading() {
  return (
    <section
      className="route-boundary"
      id="route-loading-boundary"
      aria-labelledby="loading-title"
      role="status"
      aria-live="polite"
    >
      <span className="route-boundary-code">Loading / route boundary</span>
      <h1 id="loading-title">Checking admin access and route state.</h1>
      <p>No operational record is shown until the server route resolves.</p>
      <div className="route-skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </section>
  );
}
