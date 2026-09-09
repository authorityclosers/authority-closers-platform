import { developmentAdminLoginMode } from "../lib/dev-api-proxy";

export function AdminDevelopmentBridgeNotice() {
  const mode = developmentAdminLoginMode(process.env, process.env.NODE_ENV);
  if (!mode) return null;

  return (
    <div className="development-bridge-notice" role="status">
      {mode === "local-sandbox"
        ? "Local sandbox · local test accounts and data · no remote staging access"
        : "Local UI · remote staging data · development-only admin bridge"}
    </div>
  );
}
