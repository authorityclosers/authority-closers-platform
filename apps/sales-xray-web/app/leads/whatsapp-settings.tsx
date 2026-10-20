"use client";

/**
 * WhatsApp in Settings → Connected apps: the organisation connects its own
 * WhatsApp Business number through Meta's Embedded Signup (Meta bills the
 * organisation for its messages), sets its auto replies, and keeps its message
 * templates. Owners and admins only.
 *
 * Owner, 20 Oct: one card with WhatsApp's logo, a plain status and one main
 * action; each number a card with its automatic replies and templates.
 */

import { ChevronDown, RefreshCw } from "lucide-react";
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
  type CardTone,
} from "./app-card";
import { useAppConnect } from "./app-connect";
import { LeadsError } from "./leads-client";
import {
  START_URL,
  waCall,
  type AutoReplies,
  type WaNumber,
  type WaStatus,
  type WaTemplate,
} from "./whatsapp-client";

const RETURNED: Record<string, string> = {
  connected:
    "WhatsApp is connected. Messages to your number now arrive in Leads.",
  nonumbers:
    "No WhatsApp number was shared. Connect again and pick your number.",
  cancelled: "Connecting WhatsApp was cancelled.",
  failed: "That didn't finish. Try connecting WhatsApp again.",
};
const TEMPLATE_STATUS: Record<string, { tone: CardTone; words: string }> = {
  APPROVED: { tone: "good", words: "Approved" },
  PENDING: { tone: "warn", words: "Meta is reviewing" },
  REJECTED: { tone: "bad", words: "Rejected" },
  PAUSED: { tone: "bad", words: "Paused by Meta" },
  DISABLED: { tone: "bad", words: "Turned off by Meta" },
};
const QUALITY: Record<string, { tone: CardTone; words: string }> = {
  GREEN: { tone: "good", words: "Good quality" },
  YELLOW: { tone: "warn", words: "Quality dropping" },
  RED: { tone: "bad", words: "Low quality" },
};
const TITLE = "WhatsApp";
const LOGO = <AppLogo brands={["whatsapp"]} />;

function problem(title: string, reason: unknown) {
  notify({
    id: "whatsapp-settings",
    tone: "error",
    title,
    message:
      reason instanceof LeadsError
        ? reason.message
        : "That didn't work. Try again.",
  });
}

/** "visit_reminder" → "Visit reminder". */
function readable(name: string): string {
  const words = name.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : name;
}

function AutoRepliesForm({
  number,
  approved,
  onSaved,
}: {
  number: WaNumber;
  approved: { name: string; language: string }[];
  onSaved: (status: WaStatus) => void;
}) {
  const [rules, setRules] = useState<AutoReplies>(number.autoReplies);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const first = rules.firstReply;
  const late = rules.outOfHours;
  const dirty = JSON.stringify(rules) !== JSON.stringify(number.autoReplies);
  const change = (next: AutoReplies) => {
    setSaved(false);
    setRules(next);
  };
  const save = async () => {
    setBusy(true);
    try {
      const next = await waCall<WaStatus>(
        `/whatsapp/numbers/${number.id}/auto-replies`,
        { method: "PUT", body: JSON.stringify(rules) },
      );
      onSaved(next);
      const mine = next.numbers?.find((item) => item.id === number.id);
      if (mine) setRules(mine.autoReplies);
      setSaved(true);
    } catch (reason) {
      problem("Auto replies not saved", reason);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Group title="Automatic replies">
      <SwitchRow
        label="Greet new ad leads at once"
        hint="Only people whose lead form said yes to WhatsApp get it."
        checked={first.on}
        onChange={(on) => change({ ...rules, firstReply: { ...first, on } })}
      >
        <div className={cardStyles.fields}>
          <label className={cardStyles.field}>
            <span className={cardStyles.fieldLabel}>
              <strong>Template</strong>
              <small>WhatsApp allows only an approved template here.</small>
            </span>
            <select
              value={
                first.template ? `${first.template}|${first.language}` : ""
              }
              onChange={(event) => {
                const [template, language] = event.target.value.split("|");
                change({
                  ...rules,
                  firstReply: { ...first, template, language },
                });
              }}
            >
              <option value="">Pick an approved template</option>
              {approved.map((t) => (
                <option
                  key={`${t.name}|${t.language}`}
                  value={`${t.name}|${t.language}`}
                >
                  {readable(t.name)} ({t.language})
                </option>
              ))}
            </select>
          </label>
          <label className={cardStyles.field}>
            <span className={cardStyles.fieldLabel}>
              <strong>The WhatsApp question on your form</strong>
              <small>Exactly as it is on your lead form.</small>
            </span>
            <input
              value={first.consentQuestion ?? ""}
              maxLength={200}
              placeholder="e.g. Can we message you on WhatsApp?"
              onChange={(event) =>
                change({
                  ...rules,
                  firstReply: { ...first, consentQuestion: event.target.value },
                })
              }
            />
          </label>
        </div>
      </SwitchRow>
      <SwitchRow
        label="Reply outside your work hours"
        hint="Sent at most once in 12 hours to each person."
        checked={late.on}
        onChange={(on) => change({ ...rules, outOfHours: { ...late, on } })}
      >
        <textarea
          aria-label="After-hours reply"
          placeholder="Thanks! We're closed now and will answer first thing tomorrow."
          value={late.text ?? ""}
          maxLength={1000}
          rows={2}
          onChange={(event) =>
            change({
              ...rules,
              outOfHours: { ...late, text: event.target.value },
            })
          }
        />
      </SwitchRow>
      <SaveBar
        dirty={dirty}
        busy={busy}
        saved={saved}
        label="Save auto replies"
        onSave={() => void save()}
        onDiscard={() => setRules(number.autoReplies)}
      />
    </Group>
  );
}

function NewTemplate({
  number,
  onSaved,
}: {
  number: WaNumber;
  onSaved: (status: WaStatus) => void;
}) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<"UTILITY" | "MARKETING">("UTILITY");
  const [example, setExample] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      onSaved(
        await waCall<WaStatus>(`/whatsapp/numbers/${number.id}/templates`, {
          method: "POST",
          body: JSON.stringify({
            name: name.trim(),
            language: "en",
            category,
            body: body.trim(),
            example: example
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          }),
        }),
      );
      setName("");
      setBody("");
      setExample("");
      notify({
        id: "whatsapp-template",
        tone: "success",
        title: "Sent to Meta for review",
        message: "It shows as Meta is reviewing until Meta decides.",
        timeout: 5000,
      });
    } catch (reason) {
      problem("Template not sent", reason);
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className={cardStyles.details}>
      <summary>
        New template
        <ChevronDown size={14} aria-hidden="true" />
      </summary>
      <div className={cardStyles.subBody}>
        <div className={cardStyles.fields}>
          <label className={cardStyles.field}>
            <span className={cardStyles.fieldLabel}>
              <strong>Name</strong>
              <small>Lower case and underscores, e.g. visit_reminder</small>
            </span>
            <input
              value={name}
              maxLength={60}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className={cardStyles.field}>
            <span className={cardStyles.fieldLabel}>
              <strong>Kind</strong>
              <small>
                Utility is about their enquiry; marketing is offers.
              </small>
            </span>
            <select
              value={category}
              onChange={(e) =>
                setCategory(e.target.value as "UTILITY" | "MARKETING")
              }
            >
              <option value="UTILITY">Utility (about their enquiry)</option>
              <option value="MARKETING">Marketing</option>
            </select>
          </label>
        </div>
        <label className={cardStyles.field}>
          <span className={cardStyles.fieldLabel}>
            <strong>Message</strong>
            <small>
              Use {"{{1}}"}, {"{{2}}"} for parts you fill in, like their name.
            </small>
          </span>
          <textarea
            value={body}
            maxLength={1024}
            rows={3}
            onChange={(e) => setBody(e.target.value)}
          />
        </label>
        <label className={cardStyles.field}>
          <span className={cardStyles.fieldLabel}>
            <strong>Examples for the parts</strong>
            <small>
              Comma separated, e.g. Asha, 11 am. Meta asks for these.
            </small>
          </span>
          <input
            value={example}
            maxLength={300}
            onChange={(e) => setExample(e.target.value)}
          />
        </label>
        <div>
          <button
            type="button"
            className={cardStyles.primary}
            disabled={busy || !name.trim() || !body.trim()}
            onClick={() => void submit()}
          >
            {busy ? "Sending…" : "Send for review"}
          </button>
        </div>
      </div>
    </details>
  );
}

function Templates({
  templates,
  busy,
  onSync,
}: {
  templates: WaTemplate[];
  busy: boolean;
  onSync: () => void;
}) {
  return (
    <Group
      title="Templates"
      hint="WhatsApp's approved messages, for the first message and after 24 hours of silence."
    >
      {templates.length ? (
        <ul className={cardStyles.list}>
          {templates.map((template) => {
            const state = TEMPLATE_STATUS[template.status] ?? {
              tone: "neutral" as const,
              words: template.status.toLowerCase(),
            };
            return (
              <li key={`${template.name}|${template.language}`}>
                <span>
                  <strong>{readable(template.name)}</strong>
                  <small>
                    {template.name} · {template.language}
                  </small>
                  <small className={cardStyles.listText}>{template.text}</small>
                  {template.rejectedReason ? (
                    <small className={cardStyles.listText}>
                      Why: {template.rejectedReason}
                    </small>
                  ) : null}
                </span>
                <StatusPill tone={state.tone}>{state.words}</StatusPill>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className={cardStyles.quietText}>
          No templates yet. Add one below; Meta reviews it, usually within a
          day.
        </p>
      )}
      <div>
        <button
          type="button"
          className={cardStyles.quiet}
          disabled={busy}
          onClick={onSync}
        >
          <RefreshCw size={14} aria-hidden="true" />
          Check with Meta
        </button>
      </div>
    </Group>
  );
}

export function WhatsAppSettings() {
  const params = useSearchParams();
  const [status, setStatus] = useState<WaStatus | null>(null);
  const [note, setNote] = useState<string | null>(
    params?.get("whatsapp") === "connected" ? RETURNED.connected : null,
  );
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(0);
  // In the Sales Xray app, Connect opens Meta in the phone's browser and
  // finishes back here (Facebook refuses sign-in inside the app).
  const connect = useAppConnect("whatsapp", ({ result, message }) => {
    if (result === "connected") {
      setNote(message ?? RETURNED.connected);
      setLoaded((times) => times + 1);
    } else
      notify({
        id: "whatsapp-connect",
        tone: "error",
        title: "WhatsApp not connected",
        message: message ?? RETURNED[result] ?? RETURNED.failed,
      });
  });

  useEffect(() => {
    const result = params?.get("whatsapp") ?? "";
    if (result && result !== "connected" && RETURNED[result])
      notify({
        id: "whatsapp-connect",
        tone: "error",
        title: "WhatsApp not connected",
        message: RETURNED[result],
      });
  }, [params]);

  useEffect(() => {
    let live = true;
    waCall<WaStatus>("/whatsapp/status")
      .then(
        (data) =>
          live &&
          setStatus(
            Array.isArray(data?.numbers) && Array.isArray(data?.templates)
              ? data
              : { configured: false, numbers: [], templates: [] },
          ),
      )
      .catch(
        () =>
          live && setStatus({ configured: false, numbers: [], templates: [] }),
      );
    return () => {
      live = false;
    };
  }, [loaded]);

  if (!status) return <AppCardSkeleton title={TITLE} logo={LOGO} />;

  if (!status.configured && !status.numbers.length)
    return (
      <AppCard
        logo={LOGO}
        title={TITLE}
        status={<StatusPill>Coming soon</StatusPill>}
        summary="Talk to leads on your own WhatsApp Business number, inside Sales Xray. Sales Xray is finishing this with Meta."
      />
    );

  const act = async (work: () => Promise<WaStatus>, done: string) => {
    setBusy(true);
    setNote(null);
    try {
      setStatus(await work());
      notify({
        id: "whatsapp-settings",
        tone: "success",
        title: done,
        timeout: 4000,
      });
    } catch (reason) {
      problem("That didn't work", reason);
    } finally {
      setBusy(false);
    }
  };
  const approved = status.templates.filter((t) => t.status === "APPROVED");
  const count = status.numbers.length;

  return (
    <AppCard
      logo={LOGO}
      title={TITLE}
      status={
        !status.configured ? (
          <StatusPill>Coming soon</StatusPill>
        ) : count ? (
          <StatusPill tone="good">
            {count} number{count === 1 ? "" : "s"} connected
          </StatusPill>
        ) : (
          <StatusPill>Not connected</StatusPill>
        )
      }
      summary="Talk to leads on your own WhatsApp Business number, inside Sales Xray. Meta bills your business for its messages; Sales Xray adds nothing."
      action={
        status.configured ? (
          <a
            className={count ? cardStyles.secondary : cardStyles.primary}
            href={START_URL}
            onClick={connect}
          >
            {count ? "Add a number" : "Connect WhatsApp"}
          </a>
        ) : null
      }
    >
      {note ? (
        <p className={cardStyles.quietText} role="status">
          {note}
        </p>
      ) : null}
      {status.numbers.map((number) => {
        const quality = number.quality
          ? QUALITY[number.quality.toUpperCase()]
          : undefined;
        return (
          <SubCard
            key={number.id}
            title={number.verifiedName ?? number.displayNumber}
            meta={
              <>
                {number.displayNumber}
                {quality ? (
                  <>
                    {" "}
                    <StatusPill tone={quality.tone}>{quality.words}</StatusPill>
                  </>
                ) : null}
              </>
            }
            actions={
              <button
                type="button"
                className={cardStyles.quiet}
                data-danger=""
                disabled={busy}
                onClick={() =>
                  void act(
                    () =>
                      waCall<WaStatus>(
                        `/whatsapp/numbers/${number.id}/disconnect`,
                        { method: "POST" },
                      ),
                    `${number.displayNumber} is disconnected`,
                  )
                }
              >
                Disconnect
              </button>
            }
          >
            <AutoRepliesForm
              number={number}
              approved={approved}
              onSaved={setStatus}
            />
            <Templates
              templates={status.templates}
              busy={busy}
              onSync={() =>
                void act(
                  () =>
                    waCall<WaStatus>(
                      `/whatsapp/numbers/${number.id}/templates/sync`,
                      { method: "POST" },
                    ),
                  "Templates brought in from Meta",
                )
              }
            />
            <NewTemplate number={number} onSaved={setStatus} />
          </SubCard>
        );
      })}
    </AppCard>
  );
}
