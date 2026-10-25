import { CalendarDays } from "lucide-react";

import { istStamp } from "../lib/time";
import { Badge, Empty, Panel, kitStyles, type Tone } from "../ui/kit";
import {
  ANALYTICS_WORDS,
  KIND_WORDS,
  deviceName,
  phoneLine,
  serverLine,
  totalsLine,
  type Timeline,
} from "./seller-data";
import styles from "./sellers.module.css";

const capital = (text: string) =>
  text ? text[0].toUpperCase() + text.slice(1).replace(/_/g, " ") : text;

const SUMMARY_TONE: Record<Timeline["summary"]["tone"], Tone> = {
  good: "good",
  warn: "warn",
  bad: "bad",
  neutral: "neutral",
};

/**
 * One seller's days, newest first, under a line that names the newest gap.
 * Counts, times and states only (owner, 24 Oct 2026).
 */
export function SellerTimeline({ timeline }: { timeline: Timeline }) {
  return (
    <div className={styles.layout}>
      <section
        className={styles.summary}
        data-tone={timeline.summary.tone}
        aria-label="Summary"
      >
        <Badge tone={SUMMARY_TONE[timeline.summary.tone]}>
          {timeline.summary.tone === "bad"
            ? "Needs a look"
            : timeline.summary.tone === "warn"
              ? "Worth a look"
              : timeline.summary.tone === "good"
                ? "No gaps"
                : "Quiet"}
        </Badge>
        <p className={styles.summaryWords}>{timeline.summary.words}</p>
        <p className={kitStyles.muted}>{totalsLine(timeline)}</p>
        {timeline.truncated.length ? (
          <p className={kitStyles.muted}>
            Only the newest rows were read for: {timeline.truncated.join(", ")}.
            Choose fewer days to see all of them.
          </p>
        ) : null}
      </section>
      <div className={styles.detail}>
        <div className={styles.main}>
          <Panel
            title="Day by day"
            sub="Newest first, India time. What reached the server beside what the phone reported."
          >
            {timeline.timeline.length ? (
              <ol className={styles.days}>
                {timeline.timeline.map((day) => (
                  <li key={day.day} className={styles.day}>
                    <div className={styles.dayHead}>
                      <h3>{day.label}</h3>
                      {day.flags.length ? (
                        <Badge
                          tone={
                            day.flags.some((f) => f.tone === "bad")
                              ? "bad"
                              : "warn"
                          }
                        >
                          {day.flags.length === 1
                            ? "1 gap"
                            : `${day.flags.length} gaps`}
                        </Badge>
                      ) : (
                        <Badge tone="good">No gaps</Badge>
                      )}
                      {day.versions.length ? (
                        <small className={kitStyles.muted}>
                          App {day.versions.join(", ")}
                        </small>
                      ) : null}
                    </div>
                    <dl className={styles.lines}>
                      <div>
                        <dt>Server</dt>
                        <dd>{serverLine(day.server)}</dd>
                      </div>
                      <div>
                        <dt>Phone</dt>
                        <dd>{phoneLine(day.phone)}</dd>
                      </div>
                      {day.workspaces.length ? (
                        <div>
                          <dt>Opened</dt>
                          <dd>{day.workspaces.join(", ")}</dd>
                        </div>
                      ) : null}
                    </dl>
                    {day.flags.length ? (
                      <ul
                        className={styles.flags}
                        aria-label={`Gaps on ${day.label}`}
                      >
                        {day.flags.map((flag) => (
                          <li key={flag.words} data-tone={flag.tone}>
                            {flag.words}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {day.moments.length ? (
                      <ol
                        className={styles.moments}
                        aria-label={`Times on ${day.label}`}
                      >
                        {day.moments.map((moment, index) => (
                          <li key={`${moment.at}-${index}`}>
                            <time dateTime={moment.at}>{moment.time}</time>
                            <span>{moment.words}</span>
                          </li>
                        ))}
                      </ol>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : (
              <div className={styles.body}>
                <Empty
                  icon={CalendarDays}
                  title="Nothing in this window"
                  text="No calls, results, sign-ins or app use reached the server. Choose more days."
                />
              </div>
            )}
          </Panel>
        </div>
        <aside className={styles.side}>
          <Panel
            title="Workspaces"
            sub="Sign-ins in this window open the workspace shown"
          >
            <div className={styles.body}>
              {timeline.workspaces.length ? (
                <ul className={styles.facts}>
                  {timeline.workspaces.map((workspace) => (
                    <li key={workspace.id}>
                      <strong>{workspace.name}</strong>
                      <span>
                        {KIND_WORDS[workspace.kind] ?? "Workspace"} ·{" "}
                        {capital(workspace.role)}
                        {workspace.status !== "active"
                          ? ` · ${capital(workspace.status)}`
                          : ""}
                      </span>
                      <span className={kitStyles.muted}>
                        {workspace.signIns === 1
                          ? "1 sign-in"
                          : `${workspace.signIns} sign-ins`}{" "}
                        · last opened{" "}
                        {istStamp(workspace.lastOpenedAt, "not in this window")}
                      </span>
                      <span className={kitStyles.muted}>
                        {ANALYTICS_WORDS[workspace.analytics]}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={kitStyles.muted}>Not in any workspace.</p>
              )}
            </div>
          </Panel>
          <Panel title="Devices" sub="From the app's usage data">
            <div className={styles.body}>
              {timeline.devices.length ? (
                <ul className={styles.facts}>
                  {timeline.devices.map((device) => (
                    <li key={`${device.app}-${device.device}`}>
                      <strong>{deviceName(device)}</strong>
                      <span>
                        {[
                          device.model,
                          device.android ? `Android ${device.android}` : null,
                          device.store,
                          device.version ? `version ${device.version}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                      {device.versions.length > 1 ? (
                        <span className={kitStyles.muted}>
                          Also seen: {device.versions.slice(1).join(", ")}
                        </span>
                      ) : null}
                      <span className={kitStyles.muted}>
                        Last seen {istStamp(device.lastSeenAt)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={kitStyles.muted}>
                  No usage data in this window: usage analytics may be off, or
                  the app wasn&apos;t opened.
                </p>
              )}
            </div>
          </Panel>
          <Panel
            title="Phone app"
            sub="Its setup report and the installs that logged calls"
          >
            <div className={styles.body}>
              {timeline.phones.length || timeline.installs.length ? (
                <ul className={styles.facts}>
                  {timeline.phones.map((phone) => (
                    <li key={`${phone.workspace}-${phone.install}`}>
                      <strong>
                        Setup report, install {phone.install ?? "unknown"}
                        {phone.workspace ? ` · ${phone.workspace}` : ""}
                      </strong>
                      <span>
                        {[
                          phone.family ? capital(phone.family) : null,
                          phone.appVersion
                            ? `version ${phone.appVersion}`
                            : null,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "Version not reported"}
                      </span>
                      <span className={kitStyles.muted}>
                        Setup reported {istStamp(phone.reportedAt)} · call
                        history last read {istStamp(phone.syncedAt, "never")}
                      </span>
                    </li>
                  ))}
                  {timeline.installs.map((install) => (
                    <li key={install.install}>
                      <strong>Install {install.install}</strong>
                      <span>
                        {install.calls === 1
                          ? "1 call logged"
                          : `${install.calls} calls logged`}
                      </span>
                      <span className={kitStyles.muted}>
                        First {istStamp(install.firstCallAt)} · last{" "}
                        {istStamp(install.lastCallAt)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={kitStyles.muted}>
                  The phone app hasn&apos;t reported here.
                </p>
              )}
            </div>
          </Panel>
          <Panel title="Consent">
            <div className={styles.body}>
              <p>
                {timeline.consent.termsVersion
                  ? `Terms ${timeline.consent.termsVersion}, accepted ${istStamp(timeline.consent.termsAt)}`
                  : "Terms not accepted yet"}
              </p>
            </div>
          </Panel>
        </aside>
      </div>
    </div>
  );
}
