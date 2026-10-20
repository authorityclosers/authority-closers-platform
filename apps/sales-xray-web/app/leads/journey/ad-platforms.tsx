"use client";

/**
 * Where a business's lead stages go: one card per ad platform. Sales Xray
 * matches each stage to the platform's own events; the card says each match in
 * plain words ("Site visit booked → Meta hears “Site visit booked”") and one tap
 * confirms them. Only the platform's own lead or click id and scrambled contact
 * details leave Sales Xray. No prices or costs anywhere.
 */

import { ArrowRight, Pencil, RotateCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { notify } from "../../notice-center";
import { Button, Skeleton } from "../../ui/kit";
import { useAppConnect, type ConnectProvider } from "../app-connect";
import {
  AppCard,
  AppCardSkeleton,
  AppLogo,
  StatusPill,
  SwitchRow,
  cardStyles,
} from "../app-card";
import { ago, LeadsError } from "../leads-client";
import {
  call,
  confirmMatches,
  readAds,
  readQuality,
  qualityLine,
  retryEvent,
  saveDestination,
  sentLine,
  STATUS_WORDS,
  type AdsView,
  type MatchView,
  type ProviderView,
  type Quality,
} from "./journey-client";
import styles from "./journey.module.css";

type Dataset = { id: string; name: string };

// Phone-app Connect (system browser) for the platforms Lead sources connects.
const APP_CONNECT: Record<string, ConnectProvider> = {
  meta: "meta",
  google_ads: "google",
};
const RETURNS: Record<string, string> = {
  linkedin: "LinkedIn",
  tiktok: "TikTok",
  microsoft: "Microsoft Ads",
};
type Datasets = { adAccounts: Dataset[]; datasets: Dataset[] };

const failed = (reason: unknown, title: string) =>
  notify({
    id: "journey-ads-error",
    tone: "error",
    title,
    message:
      reason instanceof LeadsError
        ? reason.message
        : "Check your connection and try again.",
  });

export function AdPlatforms({ version }: { version: number }) {
  const [ads, setAds] = useState<AdsView | null>(null);
  const load = useCallback(() => {
    readAds()
      .then(setAds)
      .catch((reason: unknown) =>
        failed(reason, "Your ad platforms didn't load"),
      );
  }, []);
  useEffect(load, [load, version]);
  // Back from a platform's Connect: say how it went, in a corner card.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    for (const [slug, name] of Object.entries(RETURNS)) {
      const outcome = params.get(slug);
      if (!outcome) continue;
      notify({
        id: `journey-connect-${slug}`,
        tone: outcome === "connected" ? "success" : "error",
        title:
          outcome === "connected"
            ? `${name} is connected`
            : outcome === "cancelled"
              ? `${name} wasn't connected`
              : `${name} didn't finish connecting`,
        message:
          outcome === "connected"
            ? "Pick where your stages go, and check the matches."
            : "Press Connect to try again.",
        timeout: outcome === "connected" ? 5000 : undefined,
      });
    }
  }, []);
  // While stages wait to settle (5 minutes), keep the line moving.
  useEffect(() => {
    if (!ads?.settling) return;
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [ads?.settling, load]);

  // Platforms set up on this environment get a card; the rest share one line.
  const ready =
    ads?.providers.filter((item) => item.available && item.configured) ?? [];
  const later =
    ads?.providers.filter((item) => !item.available || !item.configured) ?? [];
  return (
    <div className={styles.ads}>
      <header className={styles.paneHead}>
        <div>
          <h2>Where your stages go</h2>
          <p>
            Your ads learn which leads became customers and find more like them.
            Sales Xray matches your stages for you.
          </p>
        </div>
      </header>
      {ads ? (
        ready.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            ads={ads}
            version={ads.version}
            onChange={setAds}
            reload={load}
          />
        ))
      ) : (
        <AppCardSkeleton
          title="Meta"
          logo={<AppLogo brands={["meta"]} />}
          lines={3}
        />
      )}
      {later.length ? (
        <div className={styles.later}>
          <span className={styles.laterLogos} aria-hidden="true">
            {later.map((item) => (
              <AppLogo key={item.id} brands={[item.brand]} size={28} />
            ))}
          </span>
          <small>
            {later.map((item) => item.name).join(", ")}: not set up here yet.
            Your stages will match them the same way once they are.
          </small>
        </div>
      ) : null}
      <HowItWorks />
    </div>
  );
}

// What leaves Sales Xray for each platform, in words an owner reads.
const SENDS: { id: string; name: string; sends: string }[] = [
  {
    id: "meta",
    name: "Meta",
    sends:
      "Meta's own lead id, plus the email, phone, country and the lead's Sales Xray id, scrambled.",
  },
  {
    id: "google_ads",
    name: "Google Ads",
    sends:
      "Google's click id from your form, or the email and phone, scrambled.",
  },
  {
    id: "linkedin",
    name: "LinkedIn",
    sends: "LinkedIn's click id from your website, or the email, scrambled.",
  },
  {
    id: "tiktok",
    name: "TikTok",
    sends: "TikTok's lead or click id, or the email and phone, scrambled.",
  },
  {
    id: "microsoft_ads",
    name: "Microsoft Ads",
    sends:
      "Microsoft's click id from your website, or the email and phone, scrambled.",
  },
];

/** A short, plain answer to "what do my ads get, and why does it help?". No prices. */
export function HowItWorks() {
  return (
    <details className={styles.help}>
      <summary>What your ads receive, and why it helps</summary>
      <div className={styles.helpBody}>
        <p>
          On their own, your ads only see who filled a form, not who became a
          customer. When a lead reaches a stage, Sales Xray tells the ad
          platform. It then shows your ads to more people like the leads that
          went far, and fewer like the ones that went nowhere.
        </p>
        <ul>
          {SENDS.map((item) => (
            <li key={item.id}>
              <strong>{item.name}</strong>
              <span>{item.sends}</span>
            </li>
          ))}
        </ul>
        <p>
          <strong>Scrambled</strong> means one-way: the platform can match it to
          its own users, but can&apos;t read it. Names, notes, calls and what
          was said never leave Sales Xray.
        </p>
        <p>
          Only stages you confirmed are sent. Each move waits 5 minutes first,
          in case it&apos;s changed back.
        </p>
      </div>
    </details>
  );
}

function statusOf(provider: ProviderView) {
  if (!provider.configured) return <StatusPill>Not set up here yet</StatusPill>;
  if (!provider.connected) return <StatusPill>Not connected</StatusPill>;
  if (!provider.destination)
    return (
      <StatusPill tone="warn">Pick a {provider.destinationWords}</StatusPill>
    );
  if (provider.waitingOn) return <StatusPill tone="bad">Needs you</StatusPill>;
  if (!provider.on) return <StatusPill tone="warn">Switched off</StatusPill>;
  if (provider.needsCheck)
    return (
      <StatusPill tone="accent">{provider.needsCheck} to check</StatusPill>
    );
  return <StatusPill tone="good">Sending</StatusPill>;
}

function ProviderCard({
  provider,
  ads,
  version,
  onChange,
  reload,
}: {
  provider: ProviderView;
  ads: AdsView;
  version: number;
  onChange: (next: AdsView) => void;
  reload: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [quality, setQuality] = useState<Quality | null>(null);
  const asksQuality = provider.id === "meta" && !!provider.destination?.id;
  useEffect(() => {
    if (!asksQuality) return;
    let live = true;
    readQuality(provider.id)
      .then((found) => {
        if (live) setQuality(found);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [asksQuality, provider.id]);
  const [choosing, setChoosing] = useState(false);
  const app = APP_CONNECT[provider.id];
  const connect = useAppConnect(app ?? "meta", ({ result }) => {
    if (result === "connected") reload();
  });
  const run = async (work: () => Promise<AdsView>, title: string) => {
    setBusy(true);
    try {
      onChange(await work());
      return true;
    } catch (reason) {
      failed(reason, title);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const connectLink =
    provider.connectPath && provider.configured && !provider.connected ? (
      <a
        className={cardStyles.primary}
        href={provider.connectPath}
        onClick={app ? connect : undefined}
      >
        Connect {provider.name}
      </a>
    ) : null;

  const destination = provider.destination;
  const showChooser = provider.connected && (choosing || !destination);
  return (
    <AppCard
      title={provider.name}
      logo={<AppLogo brands={[provider.brand]} />}
      status={statusOf(provider)}
      summary={provider.learns}
      action={connectLink}
    >
      {!provider.configured ? null : !provider.connected ? (
        <p className={styles.cardNote}>
          {provider.reaches} Connect {provider.name} with the account that runs
          your ads.
        </p>
      ) : (
        <>
          {showChooser ? (
            <DestinationChooser
              provider={provider}
              current={destination}
              busy={busy}
              onCancel={destination ? () => setChoosing(false) : undefined}
              onPick={async (picked) => {
                const done = await run(
                  () =>
                    saveDestination(provider.id, {
                      destinationId: picked.id,
                      destinationName: picked.name,
                      on: true,
                      testCode: provider.testCode,
                    }),
                  "That dataset wasn't saved",
                );
                if (done) setChoosing(false);
              }}
            />
          ) : destination ? (
            <SwitchRow
              label={`Send lead stages to ${provider.name}`}
              hint={sentLine(provider, ads)}
              checked={provider.on}
              disabled={busy}
              onChange={(on) =>
                void run(
                  () =>
                    saveDestination(provider.id, {
                      destinationId: destination.id,
                      destinationName: destination.name,
                      on,
                      testCode: provider.testCode,
                    }),
                  on ? "Sending didn't start" : "Sending didn't stop",
                )
              }
            />
          ) : null}
          {quality && destination ? (
            <p className={styles.quality}>
              <span
                className={styles.qualityScore}
                data-level={
                  quality.score >= 6
                    ? "good"
                    : quality.score >= 4
                      ? "ok"
                      : "low"
                }
              >
                {quality.score.toFixed(1)}
              </span>
              <span>
                {qualityLine(provider.name, quality)}.{" "}
                {quality.score < 6
                  ? "Leads with an email and a phone number match best."
                  : "Good: Meta can find people like your customers."}
              </span>
            </p>
          ) : null}
          {provider.waitingOn ? (
            <p className={cardStyles.problem} role="status">
              {provider.waitingOn}
            </p>
          ) : null}
          <Matches
            provider={provider}
            editing={editing}
            busy={busy}
            onEdit={() => setEditing(true)}
            onCancel={() => setEditing(false)}
            onConfirm={async (events) => {
              const done = await run(
                () => confirmMatches(provider.id, version, events),
                "Those matches weren't saved",
              );
              if (done) setEditing(false);
            }}
          />
          {destination && !showChooser && provider.naming === "stage" ? (
            <TestEvents
              provider={provider}
              busy={busy}
              onSave={(testCode) =>
                void run(
                  () =>
                    saveDestination(provider.id, {
                      destinationId: destination.id,
                      destinationName: destination.name,
                      on: provider.on,
                      testCode,
                    }),
                  "The test code wasn't saved",
                )
              }
              onChange={() => setChoosing(true)}
            />
          ) : null}
          <Recent
            provider={provider}
            ads={ads}
            onRetry={(id) =>
              void run(() => retryEvent(id), "That event wasn't tried again")
            }
          />
        </>
      )}
    </AppCard>
  );
}

/* ---------- what each stage becomes ---------- */

const shown = (item: MatchView) =>
  item.state === "new" ? item.suggested : item.saved;

function Matches({
  provider,
  editing,
  busy,
  onEdit,
  onCancel,
  onConfirm,
}: {
  provider: ProviderView;
  editing: boolean;
  busy: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onConfirm: (events: Record<string, string | null>) => Promise<void>;
}) {
  const [names, setNames] = useState<Record<string, string | null>>({});
  const [all, setAll] = useState(false);
  const edit = () => {
    setNames(
      Object.fromEntries(
        provider.matches.map((item) => [item.stageKey, shown(item)]),
      ),
    );
    onEdit();
  };

  const fresh = provider.matches.filter(
    (item) => item.state === "new" && item.suggested,
  );
  const sentAll = provider.matches.every((item) => item.state !== "new");
  const going = provider.matches.filter((item) => shown(item));
  // Compact by default (the screen fits without scrolling): the new matches, or
  // the first few that go; everything on "Show all" and while editing.
  const visible =
    editing || all
      ? provider.matches
      : fresh.length
        ? fresh
        : going.slice(0, 3);
  const hidden = provider.matches.length - visible.length;
  return (
    <div className={styles.matches}>
      <div className={styles.matchesHead}>
        <h4>What {provider.name} hears</h4>
        {editing ? null : (
          <Button variant="ghost" onClick={edit} disabled={busy}>
            <Pencil size={13} aria-hidden="true" />
            Edit
          </Button>
        )}
      </div>
      {fresh.length && !editing && provider.destination ? (
        <div className={styles.check}>
          <Sparkles size={15} aria-hidden="true" />
          <span>
            {fresh.length === 1
              ? `“${fresh[0].stageLabel}” is new.`
              : `${fresh.length} stages are new.`}{" "}
            Sales Xray matched {fresh.length === 1 ? "it" : "them"} for you.
          </span>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              void onConfirm(
                Object.fromEntries(
                  fresh.map((item) => [item.stageKey, item.suggested]),
                ),
              )
            }
          >
            Looks right
          </Button>
        </div>
      ) : null}
      <ol className={styles.matchList}>
        {visible.map((item) => {
          const name = editing ? (names[item.stageKey] ?? null) : shown(item);
          return (
            <li
              key={item.stageKey}
              className={styles.match}
              data-state={editing ? "edit" : item.state}
              data-off={name ? undefined : ""}
            >
              <span className={styles.matchStage} data-kind={item.kind}>
                <span aria-hidden="true" />
                {item.stageLabel}
              </span>
              <ArrowRight
                size={13}
                className={styles.matchArrow}
                aria-hidden="true"
              />
              {editing && provider.options?.length ? (
                <span className={styles.matchEdit}>
                  <select
                    value={name ?? ""}
                    aria-label={`What ${provider.name} hears for ${item.stageLabel}`}
                    onChange={(event) =>
                      setNames((all) => ({
                        ...all,
                        [item.stageKey]: event.target.value || null,
                      }))
                    }
                  >
                    <option value="">Not sent</option>
                    {provider.options.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.words}
                      </option>
                    ))}
                  </select>
                </span>
              ) : editing ? (
                <span className={styles.matchEdit}>
                  <input
                    value={name ?? ""}
                    maxLength={50}
                    placeholder="Not sent"
                    aria-label={`What ${provider.name} hears for ${item.stageLabel}`}
                    onChange={(event) =>
                      setNames((all) => ({
                        ...all,
                        [item.stageKey]: event.target.value || null,
                      }))
                    }
                  />
                </span>
              ) : (
                <span className={styles.matchName}>
                  {name ? (item.words ?? `“${name}”`) : "Not sent"}
                  {item.state === "new" && name ? (
                    <em className={styles.newChip}>New</em>
                  ) : null}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {!editing && (hidden > 0 || all) ? (
        <button
          type="button"
          className={styles.linkButton}
          aria-expanded={all}
          onClick={() => setAll((open) => !open)}
        >
          {all
            ? "Show fewer"
            : `Show all ${provider.matches.length} stages (${going.length} go to ${provider.name})`}
        </button>
      ) : null}
      {editing ? (
        <div className={styles.matchActions}>
          <small>Leave a name empty to send nothing for that stage.</small>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => void onConfirm(names)}
          >
            Save names
          </Button>
        </div>
      ) : sentAll && provider.confirmedAt ? (
        <small className={styles.matchFoot}>
          Confirmed {ago(provider.confirmedAt)}. A lead that skips ahead also
          sends the stages it skipped, so {provider.name} sees the whole way.
        </small>
      ) : null}
    </div>
  );
}

/* ---------- picking where a platform's events go ---------- */

function DestinationChooser({
  provider,
  current,
  busy,
  onPick,
  onCancel,
}: {
  provider: ProviderView;
  current: { id: string; name: string } | null;
  busy: boolean;
  onPick: (dataset: Dataset) => Promise<void>;
  onCancel?: () => void;
}) {
  const [found, setFound] = useState<Datasets | null>(null);
  const [picked, setPicked] = useState<Dataset | null>(current);
  const [making, setMaking] = useState(false);
  const [typed, setTyped] = useState("");
  const [account, setAccount] = useState("");
  const [name, setName] = useState("Sales Xray lead stages");
  const meta = provider.id === "meta";
  useEffect(() => {
    const read = meta
      ? call<Datasets>("/meta/datasets")
      : call<Dataset[]>(`/journey/ads/${provider.id}/destinations`).then(
          (datasets) => ({ adAccounts: [], datasets }),
        );
    read
      .then((data) => {
        setFound(data);
        setAccount(data.adAccounts[0]?.id ?? "");
        if (data.datasets.length === 1)
          setPicked((value) => value ?? data.datasets[0]);
        if (meta && !data.datasets.length) setMaking(true);
      })
      .catch((reason: unknown) =>
        failed(
          reason,
          `Your ${provider.name} ${provider.destinationWords}s didn't load`,
        ),
      );
  }, [meta, provider.id, provider.name, provider.destinationWords]);
  const create = async () => {
    try {
      const made = await call<Dataset>("/meta/datasets", {
        method: "POST",
        body: JSON.stringify({ adAccountId: account, name: name.trim() }),
      });
      setFound((value) =>
        value ? { ...value, datasets: [made, ...value.datasets] } : value,
      );
      setPicked(made);
      setMaking(false);
    } catch (reason) {
      failed(reason, "The dataset wasn't made");
    }
  };
  return (
    <div className={styles.chooser}>
      <h4>
        Which {provider.name} {provider.destinationWords} gets your stages?
      </h4>
      {found ? (
        <ul className={styles.datasets} role="radiogroup" aria-label="Datasets">
          {found.datasets.map((dataset) => (
            <li key={dataset.id}>
              <button
                type="button"
                role="radio"
                aria-checked={picked?.id === dataset.id}
                onClick={() => setPicked(dataset)}
              >
                <strong>{dataset.name}</strong>
                <small>{dataset.id}</small>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <Skeleton height={44} />
      )}
      {making && found ? (
        <div className={styles.makeDataset}>
          <label>
            <span>Name</span>
            <input
              value={name}
              maxLength={60}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          {found.adAccounts.length > 1 ? (
            <label>
              <span>Ad account</span>
              <select
                value={account}
                onChange={(event) => setAccount(event.target.value)}
              >
                {found.adAccounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <Button
            onClick={() => void create()}
            disabled={!account || !name.trim()}
          >
            Make dataset
          </Button>
        </div>
      ) : found && meta ? (
        <button
          type="button"
          className={styles.linkButton}
          onClick={() => setMaking(true)}
        >
          Make a new dataset
        </button>
      ) : found && !found.datasets.length && provider.manualDestination ? (
        <label className={styles.manual}>
          <span>{provider.manualDestination}</span>
          <input
            value={typed}
            maxLength={40}
            aria-label={`${provider.name} ${provider.destinationWords} id`}
            onChange={(event) => {
              const id = event.target.value.trim();
              setTyped(id);
              setPicked(
                id ? { id, name: `${provider.destinationWords} ${id}` } : null,
              );
            }}
          />
        </label>
      ) : found && !found.datasets.length ? (
        <p className={styles.cardNote}>
          No {provider.name} {provider.destinationWords}s are connected yet.
          Connect {provider.name} in Lead sources first.
        </p>
      ) : null}
      <div className={styles.chooserActions}>
        {onCancel ? (
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        ) : null}
        <Button
          variant="primary"
          disabled={!picked || busy}
          onClick={() => picked && void onPick(picked)}
        >
          Looks right, start sending
        </Button>
      </div>
    </div>
  );
}

/* ---------- Meta's test events ---------- */

function TestEvents({
  provider,
  busy,
  onSave,
  onChange,
}: {
  provider: ProviderView;
  busy: boolean;
  onSave: (testCode: string | null) => void;
  onChange: () => void;
}) {
  const saved = provider.testCode ?? "";
  const [code, setCode] = useState(saved);
  const changed = code !== saved;
  return (
    <details className={styles.more}>
      <summary>
        {saved ? `Test events on · ${saved}` : "Test events off"}
        <small className={styles.moreWhere}>
          {" "}
          · {provider.destination?.name}
        </small>
      </summary>
      <form
        className={styles.moreBody}
        onSubmit={(event) => {
          event.preventDefault();
          if (changed && !busy) onSave(code || null);
        }}
      >
        <p>
          {saved
            ? `Stages also show in ${provider.name} Events Manager → Test events while this code is on.`
            : `In ${provider.name} Events Manager open this ${provider.destinationWords}, then Test events, and copy its test code here. Stages then show there as they go.`}
        </p>
        <span className={styles.testRow}>
          <input
            value={code}
            maxLength={32}
            placeholder="TEST12345"
            enterKeyHint="done"
            aria-label={`${provider.name} test code`}
            onChange={(event) => setCode(event.target.value.trim())}
          />
          {changed ? (
            <Button type="submit" variant="primary" disabled={busy}>
              {code ? "Use test code" : "Stop testing"}
            </Button>
          ) : saved ? (
            <Button
              disabled={busy}
              onClick={() => {
                setCode("");
                onSave(null);
              }}
            >
              Stop testing
            </Button>
          ) : null}
        </span>
        <button type="button" className={styles.linkButton} onClick={onChange}>
          Use another {provider.destinationWords}
        </button>
      </form>
    </details>
  );
}

/* ---------- what went lately ---------- */

function Recent({
  provider,
  ads,
  onRetry,
}: {
  provider: ProviderView;
  ads: AdsView;
  onRetry: (id: string) => void;
}) {
  const items = ads.recent.filter((item) => item.provider === provider.id);
  if (!items.length) return null;
  return (
    <details className={styles.more}>
      <summary>What went lately ({items.length})</summary>
      <ul className={styles.recent}>
        {items.map((item) => (
          <li key={item.id} data-status={item.status}>
            <span>
              <strong>{item.leadName}</strong>
              <small>
                {item.stageLabel} · {ago(item.eventTime)}
                {item.test ? " · test" : ""}
              </small>
            </span>
            <span className={styles.recentStatus}>
              {STATUS_WORDS[item.status]}
              {item.status === "rejected" || item.status === "dead_letter" ? (
                <Button
                  variant="icon"
                  aria-label={`Try ${item.leadName}'s stage again`}
                  onClick={() => onRetry(item.id)}
                >
                  <RotateCw size={13} />
                </Button>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
