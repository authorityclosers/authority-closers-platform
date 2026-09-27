import Link from "next/link";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  Check,
  Clock3,
  FileAudio,
  FileText,
  FolderOpen,
  HardDrive,
  ListChecks,
  Rocket,
  Sparkles,
} from "lucide-react";
import styles from "./acquisition-dashboard-panels.module.css";

export type AcquisitionStage = "empty" | "selected" | "processing" | "report";

export type SavedCallPreview = {
  id: string;
  title: string;
  subtitle?: string;
  dateLabel?: string;
  durationLabel?: string;
  statusLabel?: string;
  href?: string;
};

export type RecentActivityPreview = {
  id: string;
  kind: "uploaded" | "analysed" | "saved";
  title: string;
  description?: string;
  timeLabel?: string;
  href?: string;
};

const steps = [
  {
    title: "Upload your first call",
    description: "Analyse a real sales conversation",
  },
  {
    title: "Explore a sample analysis",
    description: "See what insights look like",
  },
  {
    title: "Save and organise calls",
    description: "Keep your best calls handy",
  },
  {
    title: "Invite your team",
    description: "Scale learning across your team",
  },
] as const;

const supportedAudioName = /\.(mp3|mpeg|wav|m4a|ogg|flac)$/i;

function fileSizeLabel(bytes: number): string {
  const megabytes = bytes / 1048576;
  return `${Number(megabytes.toFixed(1))} MB`;
}

/** The first milestone is true only after a submission exists. Other milestones require real evidence. */
export function AcquisitionGuideRail({
  stage,
  completedStepIndexes = [],
  stagedFiles = [],
  maximumFileBytes,
  staticPreview = false,
}: {
  stage: AcquisitionStage;
  completedStepIndexes?: readonly number[];
  stagedFiles?: readonly Pick<File, "name" | "size">[];
  maximumFileBytes?: number;
  staticPreview?: boolean;
}) {
  const completed = new Set(completedStepIndexes);
  if (stage === "processing" || stage === "report") completed.add(0);
  const count = [...completed].filter(
    (index) => index >= 0 && index < steps.length,
  ).length;

  if (stage === "selected" && stagedFiles.length >= 2) {
    const supportedCount = stagedFiles.filter((file) =>
      supportedAudioName.test(file.name),
    ).length;
    const fileLimit =
      typeof maximumFileBytes === "number" && maximumFileBytes > 0
        ? maximumFileBytes
        : null;
    const withinLimitCount =
      fileLimit !== null
        ? stagedFiles.filter((file) => file.size <= fileLimit).length
        : 0;

    return (
      <aside className={styles.rail} aria-label="Added files and next steps">
        <section
          className={`${styles.card} ${styles.guide} ${styles.queueGuide}`}
          aria-labelledby="queue-guide-title"
        >
          <div className={styles.cardHeading}>
            <Rocket
              className={styles.headingIcon}
              size={29}
              strokeWidth={1.9}
              aria-hidden="true"
            />
            <h2 id="queue-guide-title">Ready to review</h2>
          </div>
          <div className={styles.queueOverview}>
            <span className={styles.queueCount} aria-hidden="true">
              {stagedFiles.length}
            </span>
            <div>
              <strong>{stagedFiles.length} files added</strong>
              <small>Choose one recording to analyse next</small>
            </div>
          </div>
          <ul className={styles.queueChecks}>
            <li>
              <span
                className={`${styles.queueCheckIcon} ${supportedCount === stagedFiles.length ? styles.queueCheckGood : ""}`}
                aria-hidden="true"
              >
                {supportedCount === stagedFiles.length ? (
                  <Check size={16} />
                ) : (
                  <FileAudio size={16} />
                )}
              </span>
              <span>
                <strong>Supported filename formats</strong>
                <small>
                  {supportedCount} of {stagedFiles.length} have a supported
                  extension
                </small>
              </span>
            </li>
            <li>
              <span
                className={`${styles.queueCheckIcon} ${fileLimit !== null && withinLimitCount === stagedFiles.length ? styles.queueCheckGood : ""}`}
                aria-hidden="true"
              >
                {fileLimit !== null &&
                withinLimitCount === stagedFiles.length ? (
                  <Check size={16} />
                ) : (
                  <HardDrive size={16} />
                )}
              </span>
              <span>
                <strong>
                  {fileLimit !== null
                    ? "Within the file size limit"
                    : "File sizes selected"}
                </strong>
                <small>
                  {fileLimit !== null
                    ? `${withinLimitCount} of ${stagedFiles.length} are ${fileSizeLabel(fileLimit)} or less`
                    : `${fileSizeLabel(stagedFiles.reduce((total, file) => total + file.size, 0))} in total on this device`}
                </small>
              </span>
            </li>
            <li>
              <span className={styles.queueCheckIcon} aria-hidden="true">
                <ListChecks size={16} />
              </span>
              <span>
                <strong>One call at a time</strong>
                <small>
                  Select a call and give consent before its upload and analysis.
                </small>
              </span>
            </li>
          </ul>
          <div className={styles.helpCard}>
            <div className={styles.helpIntro}>
              <BookOpen size={34} strokeWidth={1.7} aria-hidden="true" />
              <div>
                <h3>Need help?</h3>
                <p>Review each file before starting its analysis.</p>
              </div>
            </div>
            <details>
              <summary className={styles.cardAction}>
                View guides &amp; tips{" "}
                <ArrowRight size={17} aria-hidden="true" />
              </summary>
              <ul className={styles.helpTips}>
                <li>Select a supported file that fits the size limit.</li>
                <li>Review language and privacy details for that call.</li>
                <li>Consent applies to the selected call only.</li>
              </ul>
            </details>
          </div>
        </section>
        <section
          className={`${styles.card} ${styles.nextCard}`}
          aria-labelledby="queue-next-title"
        >
          <div className={styles.sampleHeading}>
            <AudioLines size={23} aria-hidden="true" />
            <h2 id="queue-next-title">What happens next?</h2>
          </div>
          <ol className={styles.nextSteps}>
            <li>
              <span>1</span>
              <div>
                <strong>Select one call</strong>
                <small>Choose the recording you want to review first.</small>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <strong>Review and consent</strong>
                <small>Confirm its language and privacy choices.</small>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>Analyse, then continue</strong>
                <small>Return for the next call after this one.</small>
              </div>
            </li>
          </ol>
        </section>
      </aside>
    );
  }

  return (
    <aside
      className={styles.rail}
      aria-label="Getting started and help"
      data-static-preview={staticPreview}
    >
      <section
        className={`${styles.card} ${styles.guide}`}
        aria-labelledby="acquisition-guide-title"
      >
        <div className={styles.cardHeading}>
          <Rocket
            className={styles.headingIcon}
            size={29}
            strokeWidth={1.9}
            aria-hidden="true"
          />
          <h2 id="acquisition-guide-title">Get started</h2>
          <span className={styles.progressCount}>{count}/4</span>
        </div>
        <div
          className={styles.progressTrack}
          role="progressbar"
          aria-label="Getting started"
          aria-valuemin={0}
          aria-valuemax={4}
          aria-valuenow={count}
        >
          <span style={{ width: `${count * 25}%` }} />
        </div>
        <ol className={styles.stepList}>
          {steps.map((step, index) => (
            <li className={styles.step} key={step.title}>
              <span
                className={`${styles.stepMark} ${completed.has(index) ? styles.stepDone : ""}`}
                aria-hidden="true"
              >
                {completed.has(index) && <Check size={18} strokeWidth={2.4} />}
              </span>
              <span>
                <strong>{step.title}</strong>
                <small>{step.description}</small>
              </span>
            </li>
          ))}
        </ol>
        {!staticPreview && (
          <div className={styles.helpCard}>
            <div className={styles.helpIntro}>
              <BookOpen size={34} strokeWidth={1.7} aria-hidden="true" />
              <div>
                <h3>Need help?</h3>
                <p>Get the most out of Sales Xray with a few quick tips.</p>
              </div>
            </div>
            <details>
              <summary className={styles.cardAction}>
                View guides &amp; tips{" "}
                <ArrowRight size={17} aria-hidden="true" />
              </summary>
              <ul className={styles.helpTips}>
                <li>Choose a supported audio file up to 32 MB.</li>
                <li>
                  Check the language and privacy details before you continue.
                </li>
                <li>Open saved calls to revisit a completed report.</li>
              </ul>
            </details>
          </div>
        )}
      </section>
      <section
        className={`${styles.card} ${styles.sampleCard}`}
        aria-labelledby="sample-insight-title"
      >
        <div className={styles.sampleHeading}>
          <Sparkles size={23} aria-hidden="true" />
          <h2 id="sample-insight-title">Sample insight</h2>
          <span>Example only</span>
        </div>
        <div className={styles.sampleQuote}>
          <span className={styles.quoteGlyph} aria-hidden="true">
            “
          </span>
          <p>
            A prospect raises a pricing concern. The analysis points to that
            moment so you can review the response and plan a follow-up.
          </p>
        </div>
        <div className={styles.sampleMoments}>
          <strong>What a report can highlight</strong>
          <span>
            <i className={styles.mintDot} />
            Buying signals
          </span>
          <span>
            <i className={styles.orangeDot} />
            Objections
          </span>
          <span>
            <i className={styles.violetDot} />
            Next steps
          </span>
        </div>
        <p className={styles.sampleDisclaimer}>
          Illustrative content, not from your calls.
        </p>
        {!staticPreview && (
          <details className={styles.sampleExplore}>
            <summary className={styles.cardAction}>
              Explore a sample analysis{" "}
              <ArrowRight size={17} aria-hidden="true" />
            </summary>
            <p>
              A report can connect each observation to a moment in the
              recording, when that evidence is available.
            </p>
          </details>
        )}
      </section>
    </aside>
  );
}

export function AcquisitionLowerPanels({
  calls = [],
  activity = [],
  compact = false,
}: {
  calls?: readonly SavedCallPreview[];
  activity?: readonly RecentActivityPreview[];
  compact?: boolean;
}) {
  return (
    <div className={styles.lowerPanels} data-compact={compact}>
      <section className={styles.card} aria-labelledby="saved-calls-title">
        <div className={styles.lowerHeading}>
          <FolderOpen size={28} strokeWidth={1.8} aria-hidden="true" />
          <h2 id="saved-calls-title">Your saved calls</h2>
          <Link href="/calls">
            View all <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        <div className={styles.callColumns} aria-hidden="true">
          <span>Call name</span>
          <span>Date</span>
          <span>Duration</span>
          <span>Status</span>
        </div>
        {calls.length ? (
          <ul className={styles.callList}>
            {calls.map((call) => (
              <li className={styles.callRow} key={call.id}>
                <span className={styles.rowIcon}>
                  <AudioLines size={18} aria-hidden="true" />
                </span>
                <span className={styles.callName}>
                  {call.href ? (
                    <Link href={call.href}>{call.title}</Link>
                  ) : (
                    <strong>{call.title}</strong>
                  )}
                  {call.subtitle && <small>{call.subtitle}</small>}
                </span>
                <span>{call.dateLabel || "—"}</span>
                <span>{call.durationLabel || "—"}</span>
                <span>{call.statusLabel || "—"}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}>
              <FolderOpen size={24} strokeWidth={1.7} aria-hidden="true" />
            </span>
            <strong>No saved calls yet</strong>
            <p>Calls you save to this workspace will appear here.</p>
          </div>
        )}
      </section>
      <section className={styles.card} aria-labelledby="recent-activity-title">
        <div className={styles.lowerHeading}>
          <Clock3 size={28} strokeWidth={1.8} aria-hidden="true" />
          <h2 id="recent-activity-title">Recent activity</h2>
          <Link href="/calls">
            View all <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        {activity.length ? (
          <ul className={styles.activityList}>
            {activity.map((item) => (
              <li className={styles.activityRow} key={item.id}>
                <span className={styles.rowIcon}>
                  {item.kind === "saved" ? (
                    <FileText size={18} aria-hidden="true" />
                  ) : (
                    <AudioLines size={18} aria-hidden="true" />
                  )}
                </span>
                <span className={styles.activityName}>
                  {item.href ? (
                    <Link href={item.href}>{item.title}</Link>
                  ) : (
                    <strong>{item.title}</strong>
                  )}
                  {item.description && <small>{item.description}</small>}
                </span>
                {item.timeLabel && <time>{item.timeLabel}</time>}
              </li>
            ))}
          </ul>
        ) : (
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}>
              <Clock3 size={24} strokeWidth={1.7} aria-hidden="true" />
            </span>
            <strong>No recent activity</strong>
            <p>Your call activity will appear here when it is available.</p>
          </div>
        )}
      </section>
    </div>
  );
}
