import Link from "next/link";
import type { AppDownloads } from "./downloads";
import styles from "./get-apps.module.css";

const platforms = [
  [
    "android",
    "Android",
    "Open the downloaded APK on your phone and follow the Android installer.",
  ],
  [
    "ios",
    "iOS",
    "Follow the installation instructions provided with the iOS build.",
  ],
  [
    "windows",
    "Windows",
    "Open the downloaded installer and follow the setup steps.",
  ],
  ["macos", "Mac", "Open the disk image and move Sales Xray to Applications."],
  [
    "chrome",
    "Chrome",
    "Unzip the download. In chrome://extensions, use Developer mode → Load unpacked and choose the extension folder.",
  ],
] as const;

export function GetApps({ downloads }: { downloads: AppDownloads | null }) {
  return (
    <main className={styles.page}>
      <Link href="/dashboard">← Back to Sales Xray</Link>
      <header>
        <h1>Get the apps</h1>
        <p>Install Sales Xray for your phone, computer or browser.</p>
      </header>
      <div className={styles.grid}>
        {platforms.map(([key, title, steps]) => {
          const files =
            downloads?.files.filter((file) => file.platform === key) ?? [];
          return (
            <article className={styles.card} key={key}>
              <h2>{title}</h2>
              {files.length ? (
                <>
                  <p>Version {downloads?.version}</p>
                  {files.map((file) => (
                    <div key={file.name}>
                      <a
                        href={`/api/downloads/${encodeURIComponent(file.name)}`}
                        download
                      >
                        Download {file.name}
                      </a>
                      <p>
                        SHA-256 <code>{file.sha256}</code>
                      </p>
                    </div>
                  ))}
                </>
              ) : (
                <p role="status">Not available yet</p>
              )}
              <details>
                <summary>How to install</summary>
                <ol>
                  <li>{steps}</li>
                  <li>
                    Open Sales Xray and sign in with your Authority Closers
                    account.
                  </li>
                </ol>
              </details>
            </article>
          );
        })}
      </div>
      <section className={styles.card} aria-labelledby="tester-checklist">
        <h2 id="tester-checklist">Tester checklist</h2>
        <p>Use fictional test data for these checks.</p>
        {[
          "Check the downloaded file’s SHA-256 against the value above.",
          "Install, sign in and check that your workspace opens.",
          "Sign out and check that a download link asks you to sign in again.",
        ].map((check) => (
          <label className={styles.check} key={check}>
            <input type="checkbox" /> {check}
          </label>
        ))}
      </section>
    </main>
  );
}
