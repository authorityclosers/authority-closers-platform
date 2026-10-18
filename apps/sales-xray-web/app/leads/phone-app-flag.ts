/**
 * On from v0.58.0 (18 Oct, Orchestrator 2 on the CEO's authority): the download is the
 * signed release build on the sales-xray-apps "sales-xray-android-latest" release.
 * (Off from 17 Oct while only a debuggable test build was published.)
 *
 * Kept apart from phone-app.tsx so the account menu can ask without loading
 * the download dialog. While it is off, nothing anywhere offers the app
 * (owner, 18 Oct: no "Phone app" button in the Leads header).
 */
export const ANDROID_DOWNLOAD_READY = true;

/** The account menu's way in: /leads opens the download dialog. */
export const PHONE_APP_HREF = "/leads?app=1";
