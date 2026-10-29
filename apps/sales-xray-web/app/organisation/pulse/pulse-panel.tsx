"use client";

/**
 * Organisation → Connections → Pulse (owner, 25 Oct 2026): link this
 * organisation to its Pulse org so the team's names, photos, titles and teams
 * come from Pulse; see who matched, invite who's missing, choose what is
 * shared each way, and unlink at any time. Owners and admins only.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link2, RefreshCw, Unplug, UsersRound } from "lucide-react";

import { SwitchRow } from "../../leads/app-card";
import { notify } from "../../notice-center";
import { PulseTile } from "../../ui/pulse-mark";
import {
  Avatar,
  Badge,
  Button,
  Empty,
  List,
  Panel,
  Row,
  SkeletonRow,
} from "../../ui/kit";
import {
  type PulseState,
  PulseRefusal,
  invitePulseMembers,
  pulseReturnNotice,
  readPulse,
  revokePulseAccess,
  savePulseSharing,
  startPulseLink,
  syncPulse,
  unlinkPulse,
} from "./pulse-client";
import styles from "./pulse-panel.module.css";

const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function when(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : DATE.format(parsed);
}

const SCOPE_WORDS: Record<string, string> = {
  "calls:read": "read calls",
  "calls:write": "send recordings",
  "reports:read": "read reports",
  "leads:read": "read leads",
  "leads:write": "add leads",
  "leads:update": "change lead details",
  "leads:notes": "add notes",
  "leads:tasks": "add tasks",
};

/** "read calls, read leads" → "Read calls, read leads". */
const sentence = (words: string) =>
  words ? words.charAt(0).toUpperCase() + words.slice(1) : words;

type Loaded =
  | { state: "loading" }
  | { state: "hidden" }
  | { state: "failed" }
  | { state: "ready"; pulse: PulseState };

export function PulsePanel() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const told = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const pulse = await readPulse(signal);
      setLoaded(pulse ? { state: "ready", pulse } : { state: "hidden" });
    } catch {
      if (!signal?.aborted) setLoaded({ state: "failed" });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    readPulse(controller.signal).then(
      (pulse) =>
        setLoaded(pulse ? { state: "ready", pulse } : { state: "hidden" }),
      () => {
        if (!controller.signal.aborted) setLoaded({ state: "failed" });
      },
    );
    return () => controller.abort();
  }, []);

  // The way back from Pulse: one corner card, then a clean address.
  useEffect(() => {
    if (told.current || typeof window === "undefined") return;
    told.current = true;
    const params = new URLSearchParams(window.location.search);
    const notice = pulseReturnNotice(params.get("pulse"));
    if (!notice) return;
    notify({ id: "pulse-link", ...notice });
    params.delete("pulse");
    const query = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
    );
  }, []);

  async function run(
    key: string,
    action: () => Promise<PulseState | void>,
    done?: string,
  ) {
    setBusy(key);
    try {
      const next = await action();
      if (next) setLoaded({ state: "ready", pulse: next });
      if (done) notify({ id: "pulse", tone: "success", title: done });
    } catch (error) {
      notify({
        id: "pulse",
        tone: "error",
        title: "Not done",
        message:
          error instanceof PulseRefusal
            ? error.message
            : "That didn't work. Try again.",
      });
    } finally {
      setBusy(null);
    }
  }

  if (loaded.state === "loading")
    return (
      <Panel title="Pulse">
        <SkeletonRow avatar={36} lines={2} />
      </Panel>
    );
  // Never a blank page (owner, 29 Oct 2026: "the Pulse connection"): when
  // Pulse isn't offered to this organisation, say so in one calm card.
  if (loaded.state === "hidden")
    return (
      <section className={styles.hero} aria-label="Pulse">
        <PulseTile size={44} />
        <div className={styles.heroText}>
          <h2>Pulse</h2>
          <p>Not available for this organisation yet.</p>
        </div>
      </section>
    );
  if (loaded.state === "failed")
    return (
      <Panel title="Pulse">
        <Empty
          icon={RefreshCw}
          title="Pulse didn't load"
          action={{ label: "Try again", onClick: () => void load() }}
        />
      </Panel>
    );

  const { pulse } = loaded;
  const link = pulse.link;
  const access = pulse.access.filter((item) => !item.revokedAt);
  const invitable = pulse.members.filter((member) => member.canInvite);
  const matched = pulse.members.filter((member) => member.personId);

  return (
    <div data-pulse-panel="" className={styles.stack}>
      {/* One calm card: the mark, whether it's linked, and its one action
          (owner, 29 Oct 2026). */}
      <section className={styles.hero} aria-label="Pulse">
        <PulseTile size={44} />
        <div className={styles.heroText}>
          <h2>
            {link
              ? `Linked to ${link.orgName ?? "your Pulse org"}`
              : "Connect Pulse"}
          </h2>
          <p>
            {link
              ? [
                  link.lastSyncAt
                    ? `Read ${when(link.lastSyncAt)}`
                    : "Not read yet",
                  link.webhooks ? "updates arrive at once" : null,
                  link.linkedBy ? `linked by ${link.linkedBy}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : pulse.configured
                ? "Your team's names, photos, titles and teams come from Pulse. Roles here never change."
                : "Pulse isn't set up for this Sales X-Ray yet."}
          </p>
          {link?.lastSync.problem ? (
            <p className={styles.problem}>
              <Badge tone="warn">{link.lastSync.problem}</Badge>
            </p>
          ) : null}
        </div>
        <div className={styles.heroActions}>
          {link ? (
            <>
              <Button
                className={styles.chip}
                disabled={busy !== null}
                onClick={() =>
                  void run("sync", syncPulse, "Read again from Pulse")
                }
              >
                <RefreshCw size={14} aria-hidden="true" />
                {busy === "sync" ? "Reading…" : "Sync now"}
              </Button>
              <Button
                variant="ghost"
                className={styles.chip}
                data-confirm={confirmUnlink ? "" : undefined}
                disabled={busy !== null}
                onClick={() => {
                  if (!confirmUnlink) {
                    setConfirmUnlink(true);
                    return;
                  }
                  setConfirmUnlink(false);
                  void run("unlink", unlinkPulse, "Unlinked from Pulse");
                }}
              >
                <Unplug size={14} aria-hidden="true" />
                {confirmUnlink ? "Unlink from Pulse?" : "Unlink"}
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              className={styles.chip}
              disabled={busy !== null || !pulse.configured}
              onClick={() =>
                void run("link", async () => {
                  window.location.assign(await startPulseLink());
                })
              }
            >
              <Link2 size={14} aria-hidden="true" />
              {busy === "link" ? "Opening Pulse…" : "Connect your Pulse org"}
            </Button>
          )}
        </div>
      </section>

      {link ? (
        <Panel
          title="Your team in Pulse"
          sub={`${matched.length} of ${pulse.members.length} here`}
          className={styles.fit}
          tools={
            invitable.length ? (
              <Button
                variant="primary"
                className={styles.chip}
                disabled={busy !== null}
                onClick={() =>
                  void run(
                    "invite",
                    () => invitePulseMembers(invitable.map((m) => m.id)),
                    `Invited ${invitable.length} as Sellers`,
                  )
                }
              >
                {busy === "invite" ? "Inviting…" : `Invite ${invitable.length}`}
              </Button>
            ) : null
          }
        >
          {pulse.members.length ? (
            <List label="Pulse members">
              {pulse.members.map((member) => (
                <Row
                  key={member.id}
                  icon={
                    <Avatar
                      name={member.name ?? member.email ?? "?"}
                      photoUrl={member.photoUrl}
                      size={32}
                    />
                  }
                  title={member.name ?? member.email ?? "A Pulse member"}
                  meta={[
                    [member.title, member.team].filter(Boolean).join(" · "),
                    member.pulseRole ? `Pulse ${member.pulseRole}` : null,
                  ]}
                  end={
                    member.status === "left" ? (
                      <Badge>Left Pulse</Badge>
                    ) : member.personId ? (
                      <Badge tone="good">
                        {member.matchedBy === "pulse_sign_in"
                          ? "Signs in with Pulse"
                          : "Matched by email"}
                      </Badge>
                    ) : member.invitedAt ? (
                      <Badge tone="accent">Invited</Badge>
                    ) : member.canInvite ? (
                      <Badge tone="warn">Not here yet</Badge>
                    ) : (
                      <Badge>No checked email</Badge>
                    )
                  }
                />
              ))}
            </List>
          ) : (
            <Empty
              icon={UsersRound}
              title="No members read yet"
              text="Press Sync now to read your Pulse org's members."
            />
          )}
        </Panel>
      ) : null}

      {link ? (
        <Panel
          title="What you share"
          sub="Each way"
          className={`${styles.fit} ${styles.share}`}
        >
          <SwitchRow
            label="Names, job titles and teams from Pulse (read)"
            hint="What the link is for. Unlink to stop it."
            checked
            disabled
            onChange={() => undefined}
          />
          <SwitchRow
            label="Photos from Pulse (read)"
            hint="Off removes Pulse photos here; people's own uploads stay."
            checked={link.sharing.photos === "read"}
            disabled={busy !== null}
            onChange={(on) =>
              void run("sharing", () =>
                savePulseSharing({
                  photos: on ? "read" : "off",
                  signals: link.sharing.signals,
                }),
              )
            }
          />
          <SwitchRow
            label="Work counts to Pulse (write)"
            hint="Calls analysed, leads worked, follow-ups done and talk minutes per person per day. Never call content, transcripts or lead details."
            checked={link.sharing.signals === "write"}
            disabled={busy !== null}
            onChange={(on) =>
              void run("sharing", () =>
                savePulseSharing({
                  photos: link.sharing.photos,
                  signals: on ? "write" : "off",
                }),
              )
            }
          />
        </Panel>
      ) : null}

      <Panel
        title="Pulse's access here"
        sub="Allowed by each person"
        className={styles.fit}
      >
        {access.length ? (
          <List label="Pulse connections">
            {access.map((item) => (
              <Row
                key={item.id}
                icon={<PulseTile size={28} />}
                title={sentence(
                  item.scopes
                    .map((scope) => SCOPE_WORDS[scope] ?? scope)
                    .join(", "),
                )}
                meta={[
                  `Since ${when(item.createdAt) ?? "—"}`,
                  item.lastUsedAt ? `Used ${when(item.lastUsedAt)}` : null,
                ]}
                end={
                  <Button
                    variant="ghost"
                    className={styles.chip}
                    disabled={busy !== null}
                    onClick={() =>
                      void run(
                        `revoke:${item.id}`,
                        async () => {
                          await revokePulseAccess(item.id);
                          return (await readPulse()) ?? undefined;
                        },
                        "Pulse's access ended",
                      )
                    }
                  >
                    End
                  </Button>
                }
              />
            ))}
          </List>
        ) : (
          <Empty
            icon={Link2}
            title="Pulse has no access here"
            text="People connect Sales X-Ray from Pulse → Apps; their access shows here."
          />
        )}
      </Panel>
    </div>
  );
}
