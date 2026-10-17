/**
 * Off (17 Oct release decision): the published build is a debuggable test
 * build, so nobody is offered it until a release build is published.
 *
 * Kept apart from phone-app.tsx so the account menu can ask without loading
 * the download dialog. While it is off, nothing anywhere offers the app
 * (owner, 18 Oct: no "Phone app" button in the Leads header).
 */
export const ANDROID_DOWNLOAD_READY = false;

/** The account menu's way in: /leads opens the download dialog. */
export const PHONE_APP_HREF = "/leads?app=1";
