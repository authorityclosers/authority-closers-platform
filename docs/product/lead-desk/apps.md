# Sales Xray apps: where the code lives

Since 17 Oct 2026 the app code lives in the public repo https://github.com/authorityclosers/sales-xray-apps (owner's go: "public, no secrets or signing keys in it"). It holds:

- `apps/phone`: Android and iPhone (Capacitor 8).
- `apps/chrome`: the Chrome extension.
- `apps/desktop`: Mac and Windows (Tauri 2).

The repo also has their GitHub build workflows. It is the only copy of that code. The old `apps/sales-xray-android`, `apps/sales-xray-chrome` and their two workflows were removed from this repo after v0.50.0 (#483).

These stay here, because they are the web side the apps talk to:

- `apps/sales-xray-web/app/leads/native-phone.ts`: the `SXPhone` channel between the page and the Android app.
- `apps/sales-xray-web/app/leads/phone-app.tsx`: the Phone app dialog and its download link.

Downloads:

- The `sales-xray-android-latest` release in this repo keeps the last APK built here (0.2.4, durable key).
- New Android builds are published from the apps repo. Publishing there is manual, on main, approved by the owner, and ships the live app only.
- Switch the dialog's link to the apps repo's release once it has published one.
