"use client";

/**
 * Messenger and Instagram in Settings → Connected apps: the organisation connects
 * its Facebook Pages (and the Instagram accounts linked to them), and for each
 * Page picks its channels, auto replies and comment rules (a keyword in a comment
 * sends the commenter one private message and makes them a lead). Owners and
 * admins only.
 *
 * Owner, 20 Oct: one card with the real logos, a status in plain words and one
 * main action; each Page a card of switches; Save appears only after a change.
 */

import { Plus, Trash2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import {
  AppCard,
  AppCardSkeleton,
  AppLogo,
  cardStyles,
  Group,
  SaveBar,
  StatusPill,
  SubCard,
  SwitchRow,
} from "./app-card";
import { useAppConnect } from "./app-connect";
import { LeadsError } from "./leads-client";
import {
  CONNECT_URL,
  keywordList,
  type CommentRule,
  type MessagingStatus,
  type PageSettings,
  type SocialPage,
} from "./social-client";
import { waCall } from "./whatsapp-client";

// Instagram is named only when a connected Page has an Instagram account.
const CONNECTED_WITH_INSTAGRAM =
  "Connected. Messages to your Page and its Instagram account now arrive in Leads.";
const RETURNED: Record<string, string> = {
  connected: "Connected. Messages to your Page now arrive in Leads.",
  nopages: "No Pages were shared. Connect again and tick your Page.",
  taken: "That Page is connected to another organisation.",
  cancelled: "Connecting was cancelled.",
  failed: "That didn't finish. Try connecting again.",
};
const TITLE = "Messenger & Instagram";
const LOGO = <AppLogo brands={["messenger", "instagram"]} />;

function problem(title: string, reason: unknown) {
  notify({
    id: "social-settings",
    tone: "error",
    title,
    message:
      reason instanceof LeadsError
        ? reason.message
        : "That didn't work. Try again.",
  });
}

function RuleEditor({
  rule,
  index,
  onChange,
  onRemove,
}: {
  rule: CommentRule;
  index: number;
  onChange: (next: CommentRule) => void;
  onRemove: () => void;
}) {
  const [words, setWords] = useState(rule.keywords.join(", "));
  return (
    <fieldset className={cardStyles.sub}>
      <div className={cardStyles.subHead}>
        <div className={cardStyles.subTitle}>
          <strong>Rule {index + 1}</strong>
          <small>
            {rule.keywords.length
              ? `When a comment says ${rule.keywords.map((word) => `“${word}”`).join(" or ")}`
              : "Add the words that start it"}
          </small>
        </div>
        <button
          type="button"
          className={cardStyles.quiet}
          data-danger=""
          aria-label={`Remove rule ${index + 1}`}
          onClick={onRemove}
        >
          <Trash2 size={14} aria-hidden="true" />
          Remove
        </button>
      </div>
      <div className={cardStyles.fields}>
        <label className={cardStyles.field}>
          <span className={cardStyles.fieldLabel}>
            <strong>Words in the comment</strong>
            <small>
              Separated by commas, e.g. price, site visit. Any case.
            </small>
          </span>
          <input
            value={words}
            maxLength={600}
            onChange={(event) => {
              setWords(event.target.value);
              onChange({ ...rule, keywords: keywordList(event.target.value) });
            }}
          />
        </label>
        <label className={cardStyles.field}>
          <span className={cardStyles.fieldLabel}>
            <strong>Public answer under the comment</strong>
            <small>
              Optional. Instagram for now; Facebook sends the message only.
            </small>
          </span>
          <input
            value={rule.publicReply ?? ""}
            maxLength={300}
            placeholder="e.g. We've sent you a message."
            onChange={(event) =>
              onChange({ ...rule, publicReply: event.target.value || null })
            }
          />
        </label>
      </div>
      <label className={cardStyles.field}>
        <span className={cardStyles.fieldLabel}>
          <strong>Private message they get</strong>
          <small>Sent once. {"{first_name}"} becomes their first name.</small>
        </span>
        <textarea
          value={rule.reply}
          maxLength={1000}
          rows={2}
          onChange={(event) => onChange({ ...rule, reply: event.target.value })}
        />
      </label>
    </fieldset>
  );
}

function PageForm({
  page,
  busy,
  onSaved,
  onDisconnect,
}: {
  page: SocialPage;
  busy: boolean;
  onSaved: (status: MessagingStatus) => void;
  onDisconnect: () => void;
}) {
  const [form, setForm] = useState<PageSettings>(page.settings);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  // Each rule keeps its own editor state; a new rule gets a new key.
  const [ruleKeys, setRuleKeys] = useState(() =>
    page.settings.comments.map((_, index) => index),
  );
  const dirty = JSON.stringify(form) !== JSON.stringify(page.settings);
  const change = (next: PageSettings) => {
    setSaved(false);
    setForm(next);
  };
  const save = async () => {
    setSaving(true);
    try {
      const next = await waCall<MessagingStatus>(
        `/messaging/accounts/${page.id}`,
        { method: "PUT", body: JSON.stringify(form) },
      );
      onSaved(next);
      // The server's own words (trimmed, tidied) become the form.
      const mine = next.accounts?.find((account) => account.id === page.id);
      if (mine) {
        setForm(mine.settings);
        setRuleKeys(mine.settings.comments.map((_, index) => index));
      }
      setSaved(true);
    } catch (reason) {
      problem("Not saved", reason);
    } finally {
      setSaving(false);
    }
  };
  return (
    <SubCard
      title={page.pageName}
      meta={
        page.hasInstagram && page.igUsername
          ? `Facebook Page · Instagram @${page.igUsername}`
          : "Facebook Page"
      }
      actions={
        <button
          type="button"
          className={cardStyles.quiet}
          data-danger=""
          disabled={busy}
          onClick={onDisconnect}
        >
          Disconnect
        </button>
      }
    >
      <Group title="Where messages come from">
        <SwitchRow
          label="Messenger"
          hint="Messages to this Page arrive in Chats and become leads."
          checked={form.messenger}
          onChange={(on) => change({ ...form, messenger: on })}
        />
        {page.hasInstagram ? (
          <SwitchRow
            label={`Instagram @${page.igUsername ?? "linked account"}`}
            hint="In Instagram, turn on Settings → Messages and story replies → Message controls → Connected tools → Allow access to messages."
            checked={form.instagram}
            onChange={(on) => change({ ...form, instagram: on })}
          />
        ) : null}
      </Group>
      <Group title="Automatic replies">
        <SwitchRow
          label="Greet people who write for the first time"
          hint="Sent at once, so nobody waits in silence."
          checked={form.firstReply.on}
          onChange={(on) =>
            change({ ...form, firstReply: { ...form.firstReply, on } })
          }
        >
          <textarea
            aria-label="First reply"
            placeholder="Hi {first_name}! Thanks for writing. A person will answer shortly."
            value={form.firstReply.text ?? ""}
            maxLength={1000}
            rows={2}
            onChange={(event) =>
              change({
                ...form,
                firstReply: { ...form.firstReply, text: event.target.value },
              })
            }
          />
        </SwitchRow>
        <SwitchRow
          label="Reply outside your work hours"
          hint="Sent at most once in 12 hours to each person."
          checked={form.outOfHours.on}
          onChange={(on) =>
            change({ ...form, outOfHours: { ...form.outOfHours, on } })
          }
        >
          <textarea
            aria-label="After-hours reply"
            placeholder="Thanks! We're closed now and will answer first thing tomorrow."
            value={form.outOfHours.text ?? ""}
            maxLength={1000}
            rows={2}
            onChange={(event) =>
              change({
                ...form,
                outOfHours: { ...form.outOfHours, text: event.target.value },
              })
            }
          />
        </SwitchRow>
        <SwitchRow
          label="Let sellers answer personally up to 7 days later"
          hint="Meta's Human Agent rule: after 24 hours only a person, never an automation, may reply."
          checked={form.humanAgent}
          onChange={(on) => change({ ...form, humanAgent: on })}
        />
      </Group>
      <Group
        title="Comments that send a message"
        hint="When a comment on your post has one of these words, the person gets one private message and becomes a lead."
      >
        {form.comments.map((rule, index) => (
          <RuleEditor
            key={ruleKeys[index] ?? index}
            rule={rule}
            index={index}
            onChange={(next) =>
              change({
                ...form,
                comments: form.comments.map((r, i) => (i === index ? next : r)),
              })
            }
            onRemove={() => {
              setRuleKeys((keys) => keys.filter((_, i) => i !== index));
              change({
                ...form,
                comments: form.comments.filter((_, i) => i !== index),
              });
            }}
          />
        ))}
        <div>
          <button
            type="button"
            className={cardStyles.secondary}
            disabled={form.comments.length >= 20}
            onClick={() => {
              setRuleKeys((keys) => [...keys, Math.max(-1, ...keys) + 1]);
              change({
                ...form,
                comments: [
                  ...form.comments,
                  { on: true, keywords: [], reply: "", publicReply: null },
                ],
              });
            }}
          >
            <Plus size={14} aria-hidden="true" />
            Add a comment rule
          </button>
        </div>
      </Group>
      <SaveBar
        dirty={dirty}
        busy={saving}
        saved={saved}
        onSave={() => void save()}
        onDiscard={() => {
          setRuleKeys(page.settings.comments.map((_, index) => index));
          setForm(page.settings);
        }}
      />
    </SubCard>
  );
}

export function SocialSettings() {
  const params = useSearchParams();
  const [status, setStatus] = useState<MessagingStatus | null>(null);
  const [note, setNote] = useState<string | null>(
    params?.get("messaging") === "connected" ? RETURNED.connected : null,
  );
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(0);
  // In the Sales Xray app, Connect opens Facebook in the phone's browser and
  // finishes back here (Facebook refuses sign-in inside the app).
  const connect = useAppConnect("messaging", ({ result, message }) => {
    if (result === "connected") {
      setNote(message ?? RETURNED.connected);
      setLoaded((times) => times + 1);
    } else
      notify({
        id: "social-connect",
        tone: "error",
        title: "Not connected",
        message: message ?? RETURNED[result] ?? RETURNED.failed,
      });
  });

  // A problem coming back from Meta is a corner card, once.
  useEffect(() => {
    const result = params?.get("messaging") ?? "";
    if (result && result !== "connected" && RETURNED[result])
      notify({
        id: "social-connect",
        tone: "error",
        title: "Not connected",
        message: RETURNED[result],
      });
  }, [params]);

  useEffect(() => {
    let live = true;
    waCall<MessagingStatus>("/messaging/status")
      .then(
        (data) =>
          live &&
          setStatus(
            Array.isArray(data?.accounts)
              ? data
              : { configured: false, accounts: [] },
          ),
      )
      .catch(() => live && setStatus({ configured: false, accounts: [] }));
    return () => {
      live = false;
    };
  }, [loaded]);

  if (!status) return <AppCardSkeleton title={TITLE} logo={LOGO} />;

  if (!status.configured && !status.accounts.length)
    return (
      <AppCard
        logo={LOGO}
        title={TITLE}
        status={<StatusPill>Coming soon</StatusPill>}
        summary="Messages to your Facebook Page and Instagram will arrive in Chats. Sales Xray is finishing this with Meta."
      />
    );

  const shown =
    note === RETURNED.connected &&
    status.accounts.some((account) => account.hasInstagram)
      ? CONNECTED_WITH_INSTAGRAM
      : note;
  const count = status.accounts.length;

  const disconnect = async (page: SocialPage) => {
    setBusy(true);
    setNote(null);
    try {
      setStatus(
        await waCall<MessagingStatus>(
          `/messaging/accounts/${page.id}/disconnect`,
          { method: "POST" },
        ),
      );
      notify({
        id: "social-settings",
        tone: "success",
        title: `${page.pageName} is disconnected`,
        timeout: 4000,
      });
    } catch (reason) {
      problem("Not disconnected", reason);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppCard
      logo={LOGO}
      title={TITLE}
      label="Messenger and Instagram"
      status={
        !status.configured ? (
          <StatusPill>Coming soon</StatusPill>
        ) : count ? (
          <StatusPill tone="good">
            {count} Page{count === 1 ? "" : "s"} connected
          </StatusPill>
        ) : (
          <StatusPill>Not connected</StatusPill>
        )
      }
      summary="Messages to your Facebook Page and its Instagram account arrive in Chats and go to your sellers by your rules. A keyword in a comment can send the person a message and make them a lead."
      action={
        status.configured ? (
          <a
            className={count ? cardStyles.secondary : cardStyles.primary}
            href={CONNECT_URL}
            onClick={connect}
          >
            {count ? "Add a Page" : "Connect Messenger & Instagram"}
          </a>
        ) : null
      }
    >
      {shown ? (
        <p className={cardStyles.quietText} role="status">
          {shown}
        </p>
      ) : null}
      {status.accounts.map((page) => (
        <PageForm
          key={page.id}
          page={page}
          busy={busy}
          onSaved={setStatus}
          onDisconnect={() => void disconnect(page)}
        />
      ))}
    </AppCard>
  );
}
