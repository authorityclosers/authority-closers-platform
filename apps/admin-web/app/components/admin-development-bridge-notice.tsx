import { isStagingAdminBridge } from "../lib/dev-api-proxy";

export function AdminDevelopmentBridgeNotice() {
  if (!isStagingAdminBridge(process.env, process.env.NODE_ENV)) return null;

  return (
    <div className="development-bridge-notice" role="status">
      Local UI · remote staging data · development-only admin bridge
    </div>
  );
}
