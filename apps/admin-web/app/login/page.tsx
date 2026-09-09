import { OperationsLogin } from "@ac/operations-web/login";

import { DevAdminLoginForm } from "../components/dev-admin-login-form";
import { developmentAdminLoginMode } from "../lib/dev-api-proxy";

export default function DevAdminLoginPage() {
  const mode = developmentAdminLoginMode(process.env, process.env.NODE_ENV);
  if (!mode) return <OperationsLogin surface="admin" />;

  return (
    <main className="dev-admin-login-shell" id="admin-content">
      <DevAdminLoginForm mode={mode} />
    </main>
  );
}
