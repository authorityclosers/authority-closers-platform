"use client";

/**
 * Get the Sales Xray apps (owner order 18 Oct: "extremely easy to download and
 * install"). One public page, phone-first: a big button per platform, a QR
 * code for the Android file, its version, size and SHA-256, and three install
 * steps with pictures of the prompts people actually meet. Windows, Mac and
 * Chrome say "Coming soon" until they ship.
 */

import {
  Check,
  Globe,
  Copy,
  Download,
  Laptop,
  Monitor,
  Smartphone,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

import { Badge } from "../ui/kit";
import { inPhoneApp } from "../leads/native-phone";
import { useApkLinksAllowed } from "../purchase-policy";
import { formatSize, type AndroidRelease } from "./release";
import styles from "./apps.module.css";

const never = () => () => undefined;

/** Device facts read after hydration only, so the first paint matches the server's. */
function useDevice() {
  const android = useSyncExternalStore(
    never,
    () => /Android/i.test(navigator.userAgent),
    () => false,
  );
  const app = useSyncExternalStore(never, inPhoneApp, () => false);
  return { android, app };
}

function shortDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  });
}

function CopyValue({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={styles.copy}
      aria-label={`Copy ${label}`}
      onClick={() =>
        navigator.clipboard
          ?.writeText(value)
          .then(() => setCopied(true))
          .catch(() => undefined)
      }
    >
      {copied ? (
        <Check size={14} aria-hidden="true" />
      ) : (
        <Copy size={14} aria-hidden="true" />
      )}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/* ---------- Pictures of the prompts (drawn, so they match any phone's words) ---------- */

function AndroidPrompt() {
  return (
    <svg
      className={styles.picture}
      viewBox="0 0 220 150"
      role="img"
      aria-label="Android asks to allow installs from this source; turn on Allow from this source"
    >
      <rect
        x="1"
        y="1"
        width="218"
        height="148"
        rx="14"
        className={styles.pPhone}
      />
      <rect
        x="14"
        y="14"
        width="192"
        height="122"
        rx="10"
        className={styles.pCard}
      />
      <text x="26" y="36" className={styles.pTitle}>
        Install unknown apps
      </text>
      <text x="26" y="56" className={styles.pText}>
        Chrome
      </text>
      <rect
        x="26"
        y="70"
        width="168"
        height="34"
        rx="8"
        className={styles.pRow}
      />
      <text x="36" y="91" className={styles.pText}>
        Allow from this source
      </text>
      <rect
        x="158"
        y="79"
        width="28"
        height="16"
        rx="8"
        className={styles.pOn}
      />
      <circle cx="178" cy="87" r="6" className={styles.pKnob} />
      <circle cx="172" cy="87" r="17" className={styles.pTap} />
      <text x="26" y="124" className={styles.pHint}>
        Then go back and tap Install
      </text>
    </svg>
  );
}

function OpenPrompt() {
  return (
    <svg
      className={styles.picture}
      viewBox="0 0 220 150"
      role="img"
      aria-label="When the download finishes, tap Open, then Install"
    >
      <rect
        x="1"
        y="1"
        width="218"
        height="148"
        rx="14"
        className={styles.pPhone}
      />
      <rect
        x="14"
        y="78"
        width="192"
        height="58"
        rx="10"
        className={styles.pCard}
      />
      <text x="26" y="100" className={styles.pTitle}>
        sales-xray-android.apk
      </text>
      <text x="26" y="120" className={styles.pText}>
        Download complete
      </text>
      <rect
        x="150"
        y="106"
        width="46"
        height="22"
        rx="11"
        className={styles.pButton}
      />
      <text x="161" y="121" className={styles.pButtonText}>
        Open
      </text>
      <circle cx="173" cy="117" r="17" className={styles.pTap} />
    </svg>
  );
}

function SignInPrompt() {
  return (
    <svg
      className={styles.picture}
      viewBox="0 0 220 150"
      role="img"
      aria-label="Open Sales X-Ray and sign in with the code sent to your email"
    >
      <rect
        x="1"
        y="1"
        width="218"
        height="148"
        rx="14"
        className={styles.pPhone}
      />
      <rect
        x="14"
        y="14"
        width="192"
        height="122"
        rx="10"
        className={styles.pCard}
      />
      <text x="26" y="38" className={styles.pTitle}>
        Sales X-Ray
      </text>
      <rect
        x="26"
        y="52"
        width="168"
        height="26"
        rx="7"
        className={styles.pRow}
      />
      <text x="36" y="69" className={styles.pText}>
        {/* Two spans: Cloudflare's email obfuscation must not rewrite the
            example address (its decoder fails on SVG links). */}
        <tspan>you@</tspan>
        <tspan>company.com</tspan>
      </text>
      <rect
        x="26"
        y="88"
        width="168"
        height="28"
        rx="14"
        className={styles.pButton}
      />
      <text x="62" y="106" className={styles.pButtonText}>
        Email me a code
      </text>
      <circle cx="110" cy="102" r="17" className={styles.pTap} />
    </svg>
  );
}

function SmartScreenPrompt() {
  return (
    <svg
      className={styles.picture}
      viewBox="0 0 220 150"
      role="img"
      aria-label="Windows protected your PC: choose More info, then Run anyway"
    >
      <rect
        x="1"
        y="1"
        width="218"
        height="148"
        rx="6"
        className={styles.pSmart}
      />
      <text x="14" y="34" className={styles.pSmartTitle}>
        Windows protected your PC
      </text>
      <text x="14" y="56" className={styles.pSmartText}>
        Microsoft Defender SmartScreen…
      </text>
      <text x="14" y="78" className={styles.pSmartLink}>
        More info
      </text>
      <circle cx="36" cy="74" r="15" className={styles.pTap} />
      <rect
        x="112"
        y="112"
        width="96"
        height="26"
        rx="3"
        className={styles.pSmartButton}
      />
      <text x="128" y="129" className={styles.pSmartText}>
        Run anyway
      </text>
    </svg>
  );
}

/* ---------- The page ---------- */

const SOON = [
  {
    key: "windows",
    name: "Windows",
    icon: Monitor,
    line: "Records Zoom, Meet and Teams sales calls",
  },
  {
    key: "mac",
    name: "Mac",
    icon: Laptop,
    line: "Records Zoom, Meet and Teams sales calls",
  },
  {
    key: "chrome",
    name: "Chrome extension",
    icon: Globe,
    line: "Add leads from any page, call in one click",
  },
] as const;

export function AppsView({ android }: { android: AndroidRelease }) {
  const device = useDevice();
  const apkLinks = useApkLinksAllowed();
  const facts = [
    android.version ? `Version ${android.version}` : null,
    formatSize(android.sizeBytes),
    android.updatedAt ? `updated ${shortDate(android.updatedAt)}` : null,
  ].filter(Boolean);

  return (
    <main className={styles.page} data-apps-page="">
      <header className={styles.top}>
        <Link className={styles.brand} href="/">
          Sales X-Ray
        </Link>
      </header>

      <section className={styles.hero}>
        <p className={styles.eyebrow}>Sales X-Ray apps</p>
        <h1>Get Sales X-Ray on your phone</h1>
        <p className={styles.lead}>
          Call leads with one tap. The app notes who picked up and for how long,
          logs every work call, and sends the phone&apos;s own recording for
          analysis.
        </p>
      </section>

      <section className={styles.android} aria-label="Android">
        <div className={styles.androidHead}>
          <span className={styles.icon}>
            <Smartphone size={24} aria-hidden="true" />
          </span>
          <span>
            <strong>Android</strong>
            <small>
              {!apkLinks
                ? "From Google Play"
                : facts.length
                  ? facts.join(" · ")
                  : "Newest build"}
            </small>
          </span>
          <Badge tone="good">Ready</Badge>
        </div>

        {!apkLinks ? (
          <p className={styles.note} role="status">
            You&apos;re using Sales X-Ray from Google Play. Updates come from
            Google Play.
          </p>
        ) : device.app ? (
          <p className={styles.note} role="status">
            You&apos;re already using the app. Updates download from here too.
          </p>
        ) : null}

        {/* The Google Play app updates only through Play (Play policy): no file to download. */}
        {apkLinks ? (
          <>
            <div className={styles.get}>
              <a className={styles.download} href={android.url} download>
                <Download size={20} aria-hidden="true" />
                Download for Android
              </a>
              {device.android ? null : (
                <figure className={styles.qrBox}>
                  <QRCodeSVG
                    value={android.url}
                    size={148}
                    marginSize={2}
                    className={styles.qr}
                    title="Scan with your Android phone's camera"
                  />
                  <figcaption>Scan with your phone&apos;s camera</figcaption>
                </figure>
              )}
            </div>

            {android.sha256 ? (
              <details className={styles.check}>
                <summary>Check the file (SHA-256)</summary>
                <p>
                  <code>{android.sha256}</code>
                  <CopyValue value={android.sha256} label="SHA-256" />
                </p>
              </details>
            ) : null}

            <ol className={styles.steps} aria-label="Install on Android">
              <li>
                <OpenPrompt />
                <span>
                  <strong>1. Download and open</strong>
                  Tap Download, then Open when it finishes.
                </span>
              </li>
              <li>
                <AndroidPrompt />
                <span>
                  <strong>2. Allow the install</strong>
                  If the phone asks, tap Settings, turn on &ldquo;Allow from
                  this source&rdquo;, go back and tap Install.
                </span>
              </li>
              <li>
                <SignInPrompt />
                <span>
                  <strong>3. Sign in</strong>
                  Open Sales X-Ray and sign in with the code we email you. On a
                  lead, tap Call and allow Phone, Call history and Music and
                  audio.
                </span>
              </li>
            </ol>
            <p className={styles.small}>
              Works best on phones that record calls by themselves: Samsung,
              Xiaomi, Redmi, POCO, OnePlus, Realme, Oppo, Vivo and Motorola.
            </p>
          </>
        ) : null}
      </section>

      <section className={styles.soon} aria-label="Coming soon">
        <h2>More apps</h2>
        <ul>
          {SOON.map(({ key, name, icon: Icon, line }) => (
            <li key={key} data-platform={key}>
              <span className={styles.icon}>
                <Icon size={20} aria-hidden="true" />
              </span>
              <span>
                <strong>{name}</strong>
                <small>{line}</small>
              </span>
              <span className={styles.soonButton} aria-disabled="true">
                Coming soon
              </span>
            </li>
          ))}
        </ul>
        <details className={styles.check}>
          <summary>Installing on Windows, when it&apos;s ready</summary>
          <div className={styles.windowsHelp}>
            <SmartScreenPrompt />
            <p>
              Windows may say it protected your PC. Choose{" "}
              <strong>More info</strong>, then <strong>Run anyway</strong>. The
              app is ours; Windows shows this for any new app until enough
              people have installed it.
            </p>
          </div>
        </details>
      </section>

      <footer className={styles.footer}>
        <Link href="/privacy">Privacy</Link>
        <Link href="/terms">Terms</Link>
        <Link href="/contact">Contact</Link>
      </footer>
    </main>
  );
}
