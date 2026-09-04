const STAGING_APP_ORIGIN = "https://staging.authorityclosers.com";

export function StagingAuthHandoff({
  path,
  action,
}: {
  path: "/register" | "/forgot-password" | "/verify-email" | "/reset-password";
  action: string;
}) {
  const href = new URL(path, STAGING_APP_ORIGIN).toString();
  return (
    <div className="auth-card">
      <h2>Continue on deployed staging.</h2>
      <p className="auth-card__intro">
        {action} remains on the canonical staging origin so one-time links and
        provider callbacks are never relayed through localhost.
      </p>
      <a className="button button--ink button--full" href={href}>
        Open deployed staging
      </a>
    </div>
  );
}
