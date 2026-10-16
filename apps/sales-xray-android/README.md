# Sales Xray for Android

The Sales Xray web app (https://salesxray.authorityclosers.com) in a Capacitor 8 shell, plus **Calls on this phone**. It works only on phones that record calls by themselves (owner order, 5 Oct 2026; AUT-1210).

## What it does

- Opens the live Sales Xray site, so every web release reaches the app with no app update.
- **Call a lead from the app** (owner order, 16 Oct 2026). On a lead, Call asks once for three permissions: Phone, Call history, and Music and audio. Then:
  - the app places the call itself;
  - when the call ends, the app reads the phone's call history (connected or not, talk time) and the lead screen opens "How did it go?" already filled in;
  - the app looks for the recording the phone's own dialer saved for that call, and the lead screen offers it for analysis.
  Nothing is uploaded until the person ticks the consent box and taps Analyse. The web side is `apps/sales-xray-web/app/leads/native-phone.ts`.
- **Calls on this phone.** A button on other pages lists the call recordings the phone saved by itself, from these folders:

  | Phone maker | Folder |
  |---|---|
  | Samsung | `Recordings/Call` |
  | Xiaomi, Redmi, POCO | `MIUI/sound_recorder/call_rec` |
  | OnePlus, Realme, Oppo | `Recordings/Call Recordings`, `Music/Recordings/Call Recordings` |
  | Vivo | `Record/Call` |
  | Others | `PhoneRecord`, `Call Recordings` |

- **Tell me about new recordings.** A 15-minute background check (WorkManager) posts a notification for each new recording.

## Limits

- **Google Phone app:** keeps its recordings private, so they can't be read.
- **Call history:** download builds read it to tell connected from not connected. Google Play allows that only for default phone apps, so a Play build would drop it and the person answers by hand.
- **iPhone:** gives apps no access to call audio.
- **Formats:** `.aac` and `.amr` are listed but cannot be analysed until the server accepts them.
- **Google sign-in:** Google blocks it inside apps. Use the email code or a password, until native Google sign-in is added.

## How it is built

- **Page-to-phone channel:** the page talks to the phone through an origin-restricted `WebViewCompat` message channel called `SXPhone`. It answers only Sales Xray's own sites and works under the site's content security policy. Methods: `status`, `requestAccess`, `requestCallAccess`, `call`, `lastCall`, `forgetCall`, `list`, `read`, `setWatch`, `openAllFiles`, `consumeLaunch`. When a call ends the app also posts `{event: "call", call}` to the page.
- **Where the code lives:**
  - `PhoneBridge.java`: the channel.
  - `CallTracker.java`: placing a lead's call, following it, the call history and matching the recording.
  - `RecordingScanner.java`: finding and reading recordings.
  - `RecordingWatchWorker.java`: the background check.
  - `android/app/src/main/assets/sx-phone.js`: the in-app panel.
- **CI build:** `.github/workflows/sales-xray-android.yml` builds two APKs on GitHub-hosted runners for `main` and `task/**` pushes: "Sales Xray" (live site) and "Sales Xray Dev" (dev site, package `com.authorityclosers.salesxray.dev`, installs beside it). Download them from the run's artifacts. Build the dev one locally with `./gradlew assembleDebug -PsxDev` after pointing `capacitor.config.json` at dev.
- **Signing:** `android/app/sales-xray-test.keystore` is a **test-only** key with the public password `android`, so test builds update in place. A release key belongs in Infisical, never here.
- **Icons:** `scripts/make-icons.mjs` draws the launcher icons and splash screens.

## Local build

```bash
npm ci --ignore-scripts
npx cap sync android
cd android && ./gradlew assembleDebug
```
