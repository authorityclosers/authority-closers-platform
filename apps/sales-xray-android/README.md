# Sales Xray for Android

The Sales Xray web app (https://salesxray.authorityclosers.com) in a Capacitor 8 shell, plus **Calls on this phone**. It works only on phones that record calls by themselves (owner order, 5 Oct 2026; AUT-1210).

## What it does

- Opens the live Sales Xray site, so every web release reaches the app with no app update.
- **Calls on this phone.** A button in the app opens a list of the call recordings the phone saved by itself, from these folders:

  | Phone maker | Folder |
  |---|---|
  | Samsung | `Recordings/Call` |
  | Xiaomi, Redmi, POCO | `MIUI/sound_recorder/call_rec` |
  | OnePlus, Realme, Oppo | `Recordings/Call Recordings`, `Music/Recordings/Call Recordings` |
  | Vivo | `Record/Call` |
  | Others | `PhoneRecord`, `Call Recordings` |

  **Analyse** hands the file to the normal New analysis upload, so consent, plan and approval are the same as on the web. Nothing leaves the phone until the person taps Analyse.
- **Tell me about new recordings.** A 15-minute background check (WorkManager) posts a notification for each new recording. Tapping it opens Sales Xray with that recording ready to analyse.

## Limits

- **Google Phone app:** keeps its recordings private, so they can't be read.
- **iPhone:** gives apps no access to call audio.
- **Formats:** `.aac` and `.amr` are listed but cannot be analysed until the server accepts them.
- **Google sign-in:** Google blocks it inside apps. Use the email code or a password, until native Google sign-in is added.

## How it is built

- **Page-to-phone channel:** the page talks to the phone through an origin-restricted `WebViewCompat` message channel called `SXPhone`. It answers only Sales Xray's own sites and works under the site's content security policy.
- **Where the code lives:**
  - `PhoneBridge.java`: the channel.
  - `RecordingScanner.java`: finding and reading recordings.
  - `RecordingWatchWorker.java`: the background check.
  - `android/app/src/main/assets/sx-phone.js`: the in-app panel.
- **CI build:** `.github/workflows/sales-xray-android.yml` builds a test APK on GitHub-hosted runners for `main` and `task/**` pushes. Download it from the run's artifacts.
- **Signing:** `android/app/sales-xray-test.keystore` is a **test-only** key with the public password `android`, so test builds update in place. A release key belongs in Infisical, never here.
- **Icons:** `scripts/make-icons.mjs` draws the launcher icons and splash screens.

## Local build

```bash
npm ci --ignore-scripts
npx cap sync android
cd android && ./gradlew assembleDebug
```
