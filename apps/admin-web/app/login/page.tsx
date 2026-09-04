import { notFound } from "next/navigation";

import { DevAdminLoginForm } from "../components/dev-admin-login-form";
import { isStagingAdminBridge } from "../lib/dev-api-proxy";

export default function DevAdminLoginPage() {
  if (!isStagingAdminBridge(process.env, process.env.NODE_ENV)) notFound();

  return (
    <main className="dev-admin-login-shell" id="admin-content">
      <DevAdminLoginForm />
    </main>
  );
}
