# Live web updates: signed web bundles for the phone apps

Owner, 28 Oct 2026: "Why aren't I getting the app update on Play Store automatically ... I need new updated".

The Sales X-Ray phone app carries the web app's static export, so until now a web release reached phones only
in a new Play build, after Google's review of each closed-testing release. With live web updates, the installed
app picks up each production web release by itself within minutes:

1. A release goes live on production (`ac-ship.log`: `vX.Y.Z is live on production`).
2. `ac-web-bundle-after-release` on ac (timer, every 5 minutes) dispatches `sales-xray-web-bundle.yml` for the
   release's exact main commit. GitHub builds the same static export the app carries and packs it with
   `infra/application/scripts/sx-web-bundle pack`: web files only, `sx-web.json`, a zip named by its SHA-256.
3. The hook downloads the artifact, signs the manifest with the Ed25519 key that only Infisical holds
   (prod `/app-web`, `AC_SX_WEB_BUNDLE_SIGNING_KEY`, injected by `ac-infisical-run` into the signer alone),
   checks the signed manifest with the public key the apps pin, and publishes both into the production API's
   media volume (`/srv/authority-closers/volumes/media-video/production/app-web`, root-owned, 0755/0644).
4. The production API serves them read-only on production's own address
   (`packages/python/ac_platform/http/app_web.py`, `AC_APP_WEB_ROOT`):
   - `https://salesxray.authorityclosers.com/v1/app-web/manifest.json` (no-cache)
   - `https://salesxray.authorityclosers.com/v1/app-web/bundles/<sha256>.zip` (immutable)
5. The app (sales-xray-apps `LiveWeb.java`), on start and on coming back (at most every 5 minutes), reads the
   manifest, checks the signature against its pinned keys, downloads the zip, checks its size and SHA-256,
   unpacks only web files into its own storage and uses it from the next start. A new bundle must send the
   page's ready signal (`webReady`, from `apps/sales-xray-web/app/web-ready.tsx`) within 15 seconds of its first
   page, or the app rolls back to the bundle before it, then to its own copy. A start never waits for the
   network, so the app works offline from what it has.

## The manifest

`manifest.json` is `{"format": "sx-web-bundle/1", "key": <hex public key>, "payload": <JSON text>, "signature":
<hex>}`. The signature is Ed25519 over `sx-web-bundle/1\n` followed by the payload's exact text. The payload:

| Field                       | Meaning                                                                                                          |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `host`                      | The site the bundle is for (a dev bundle never opens in the live app)                                            |
| `version`                   | The release (`1.3.0`)                                                                                            |
| `sha`                       | The platform commit it was built from                                                                            |
| `sequence`                  | When it was signed (ms): an older manifest played back is refused; a deliberate rollback is a new signature      |
| `bundle`, `sha256`, `bytes` | `bundles/<sha256>.zip`, its SHA-256 and exact size                                                               |
| `minNative`                 | The app's native contract the web needs (`LiveWebRules.NATIVE_CONTRACT`); an older app waits for its store build |
| `commitAtMs`, `builtAtMs`   | The commit's time (compared with the app's own copy) and the build's                                             |

Raise `MIN_NATIVE` in `/etc/ac-web-bundle-after-release.conf` for a release whose web needs a new bridge method,
plugin or permission; apps without it keep their own copy until the Play build that raises the contract.

## Turning it on (owner's yes needed; not done)

Nothing is live: no key exists, the apps pin none, and the hook is not installed. In order:

1. **Owner:** create the signing key in Infisical only: in the Infisical UI, environment prod, folder `/app-web`,
   add `AC_SX_WEB_BUNDLE_SIGNING_KEY` with 64 random hex characters (for example `openssl rand -hex 32` on your
   own laptop, pasted straight in). It is never put in git, chat, logs or a GitHub secret, and only the signer
   reads it, through ac's Infisical machine identity (which needs read access to `/app-web`).
2. **Orchestrator:** print the public key (not a secret) on ac:
   `AC_INFISICAL_ENVIRONMENT=prod AC_INFISICAL_PATH=/app-web ac-infisical-run -- sx-web-bundle public-key`.
   Put it in sales-xray-apps `apps/phone/android/app/src/main/assets/live-web.json` (`sites` →
   `salesxray.authorityclosers.com` → `keys`) and ship that Play build. Apps without the key ignore manifests.
3. **Orchestrator:** install on ac: `sx-web-bundle` and `ac-web-bundle-after-release` to `/usr/local/sbin/`, the
   two units to `/etc/systemd/system/`, `/etc/ac-web-bundle-after-release.conf` with `ENABLED=1` and
   `PUBLIC_KEY=<hex>`, then `systemctl enable --now ac-web-bundle-after-release.timer`. The next production
   release publishes its bundle; `v1.3.0 is live` → phones pick it up at their next start or return.

To stop: `ENABLED=0` in the config (phones keep what they have; nothing new is published). To make every app
ignore live updates at once, remove the key from `live-web.json` in a store build. To roll back the web on phones,
ship the older release to production: the hook publishes it again with a newer signature.

## Rules that keep it inside the stores' policies

- Only files a web page shows or runs in the WebView go in a bundle (`TYPES`, the same list in the packer and the
  app): no `.so`, `.dex`, `.jar`, `.apk`, WebAssembly or unknown files. The packer fails the build and the app
  refuses the whole bundle otherwise. sales-xray-apps `apps/phone/PLAY-STORE.md` says why this is inside Google
  Play's Device and Network Abuse policy, and `APP-STORE.md` the iPhone's limits.
- Bundles are signed and pinned, because the page talks to the phone through `SXPhone`.
- New native abilities still ship as store builds (`minNative`).

## Checks

- `tests/infra/test_sx_web_bundle.py`: packing, file types, signing as the app checks it, refusals, publishing.
- `tests/infra/test_web_bundle_after_release.py`: off until enabled, exact commit, Infisical path, pinned-key check.
- `tests/unit/http/test_app_web.py`: what the API serves and refuses.
- sales-xray-apps: `Ed25519Test`, `LiveWebRulesTest` and the emulator proof (`live-web.yml`).
