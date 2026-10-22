"use client";

/**
 * Get the Sales Xray phone app (owner order 16 Oct 2026: Android first, a
 * download link inside Sales Xray, stores later). The link is the signed
 * release build from authorityclosers/sales-xray-apps (Orchestrator 2,
 * 18 Oct): each publish replaces the files of one fixed release, so it always
 * fetches the newest build. It is offered only from the account menu, and
 * only while ANDROID_DOWNLOAD_READY is on.
 */

import {
  Check,
  Copy,
  Download,
  Monitor,
  Puzzle,
  Smartphone,
  X,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useState, useSyncExternalStore } from "react";

import { Badge, Button, Dialog } from "../ui/kit";
import { inPhoneApp } from "./native-phone";
import { ANDROID_DOWNLOAD_READY } from "./phone-app-flag";
import styles from "./leads.module.css";

export { ANDROID_DOWNLOAD_READY };

const RELEASE =
  "https://github.com/authorityclosers/sales-xray-apps/releases/download/sales-xray-android-latest";
export const ANDROID_APP = `${RELEASE}/sales-xray-android.apk`;
const BANNER_KEY = "sx-leads-app-banner";

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

function CopyLink({ link }: { link: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      onClick={() => {
        navigator.clipboard
          ?.writeText(link)
          .then(() => setCopied(true))
          .catch(() => undefined);
      }}
    >
      {copied ? (
        <Check size={14} aria-hidden="true" />
      ) : (
        <Copy size={14} aria-hidden="true" />
      )}
      {copied ? "Link copied" : "Copy the link for your team"}
    </Button>
  );
}

export function PhoneAppDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { android, app } = useDevice();
  // Only the real app is ever offered; the Dev build is never a download.
  const link = ANDROID_APP;
  return (
    <Dialog
      open={open}
      title="Sales Xray on your phone"
      description="Call leads from your phone. Sales Xray places the call, notes whether they picked up and for how long, and offers the phone's own recording for analysis."
      onClose={onClose}
    >
      <div className={styles.apps}>
        <section className={styles.appCard} aria-label="Android">
          <div className={styles.appHead}>
            <span className={styles.wayIcon}>
              <Smartphone size={22} aria-hidden="true" />
            </span>
            <span>
              <strong>Android</strong>
              <small>Test build, updated with every release</small>
            </span>
            <Badge tone="accent">
              {ANDROID_DOWNLOAD_READY ? "New" : "Testing"}
            </Badge>
          </div>
          {app ? (
            <p className={styles.hint}>
              You&apos;re using the app. On any lead, tap Call.
            </p>
          ) : !ANDROID_DOWNLOAD_READY ? (
            <p className={styles.hint}>
              The Android app is being tested by the Authority Closers team. The
              download appears here once it&apos;s signed for your phones.
            </p>
          ) : (
            <>
              <div className={styles.appGet}>
                {android ? null : (
                  <QRCodeSVG
                    value={link}
                    size={132}
                    marginSize={2}
                    className={styles.qr}
                    title="Scan with your Android phone's camera"
                  />
                )}
                <div className={styles.appGetText}>
                  {android ? null : (
                    <p className={styles.hint}>
                      Scan with your Android phone&apos;s camera, or open Sales
                      Xray on the phone and download it there.
                    </p>
                  )}
                  <a className={styles.downloadButton} href={link}>
                    <Download size={16} aria-hidden="true" />
                    Download for Android
                  </a>
                  <CopyLink link={link} />
                </div>
              </div>
              <a className={styles.appsLink} href="/apps">
                Install help with pictures, the file&apos;s SHA-256 and other
                platforms
              </a>
              <details className={styles.terms}>
                <summary>How to install</summary>
                <ol className={styles.steps}>
                  <li>Open the downloaded file.</li>
                  <li>
                    If your phone asks, allow your browser to install apps.
                  </li>
                  <li>
                    Open Sales Xray and sign in with the email code (Google
                    sign-in doesn&apos;t work inside apps).
                  </li>
                  <li>
                    On a lead, tap Call and allow Phone, Call history, and Music
                    and audio.
                  </li>
                </ol>
              </details>
            </>
          )}
          <p className={styles.hint}>
            Works on phones that record calls by themselves: Samsung, Xiaomi,
            Redmi, POCO, OnePlus, Realme, Oppo, Vivo and Motorola. Google&apos;s
            Phone app keeps its recordings private.
          </p>
        </section>
        <ul className={styles.soon} aria-label="Coming next">
          <li>
            <Smartphone size={16} aria-hidden="true" />
            <span>
              <strong>iPhone</strong> · knows when the call connected and how
              long it lasted
            </span>
            <Badge>Coming</Badge>
          </li>
          <li>
            <Monitor size={16} aria-hidden="true" />
            <span>
              <strong>Mac and Windows</strong> · records Zoom, Meet and Teams
              sales calls
            </span>
            <Badge>Coming</Badge>
          </li>
          <li>
            <Puzzle size={16} aria-hidden="true" />
            <span>
              <strong>Chrome extension</strong> · add leads from any page and
              call with one click
            </span>
            <Badge>Coming</Badge>
          </li>
        </ul>
      </div>
    </Dialog>
  );
}

function readHidden(): boolean {
  try {
    return localStorage.getItem(BANNER_KEY) === "hidden";
  } catch {
    return false;
  }
}

/** A one-line nudge for sellers on an Android phone who aren't in the app yet. */
export function PhoneAppBanner({ onOpen }: { onOpen: () => void }) {
  const { android, app } = useDevice();
  const stored = useSyncExternalStore(never, readHidden, () => true);
  const [closed, setClosed] = useState(false);
  if (!ANDROID_DOWNLOAD_READY || !android || app || stored || closed)
    return null;
  return (
    <div className={styles.appBanner} role="note">
      <Smartphone size={18} aria-hidden="true" />
      <span>
        <strong>Get the Sales Xray app.</strong> Tap Call, and it fills in how
        the call went and finds the recording for you.
      </span>
      {/* Tonal: Leads keeps one filled action, Start calling (Liquid Glass
          polish rubric, 22 Oct 2026). */}
      <Button className={styles.bannerAction} onClick={onOpen}>
        Get the app
      </Button>
      <button
        type="button"
        className={styles.bannerClose}
        aria-label="Hide this"
        onClick={() => {
          try {
            localStorage.setItem(BANNER_KEY, "hidden");
          } catch {
            // Storage blocked: it stays hidden for this visit only.
          }
          setClosed(true);
        }}
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
