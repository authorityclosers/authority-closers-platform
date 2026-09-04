import { isStagingAuthenticatedBridge } from "../lib/dev-api-proxy";
import { DevStagingBridgeNoticeClient } from "./dev-staging-bridge-notice-client";

export function DevStagingBridgeNotice() {
  if (!isStagingAuthenticatedBridge(process.env, process.env.NODE_ENV)) {
    return null;
  }

  return <DevStagingBridgeNoticeClient />;
}

export {
  DEV_STAGING_NOTICE_STORAGE_KEY,
  DevStagingBridgeNoticeClient,
  getSessionStorage,
  isDevNoticeToggleShortcut,
  isEditableTarget,
  isNoticeDismissed,
  setNoticeDismissed,
  toggleDevNotice,
} from "./dev-staging-bridge-notice-client";
