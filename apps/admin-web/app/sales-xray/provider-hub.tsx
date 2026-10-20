"use client";

/**
 * Admin's Providers hub (owner, 20 Oct 2026: "just search for a provider name, add, add key
 * and boom it's there, and all its models listed"). Type to find a provider; pick it to
 * see every model it offers with context, inputs, JSON support, list prices and the
 * pipeline stages it can run here. Searching filters as you type; the chosen provider is
 * in the link, so a page can be shared. Each provider shows its spend here and its failures,
 * the latest in plain words with what fixes it, and its key here: sealed, write-only, with a
 * free connection test.
 */
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "../ui/kit";
import {
  NO_MODEL_FILTER,
  PIPELINE_WORDS,
  agoWords,
  contextWords,
  failureCountWords,
  filterModels,
  priceWords,
  rupeeWords,
  searchProviders,
  spendWords,
  type Hub,
  type HubProvider,
  type KindFilter,
  type ModelFilter,
  type ProviderHealth,
  type ProviderHealthRow,
  type ProviderKeys,
} from "./provider-hub-data";
import { ProviderKey } from "./provider-key";
import styles from "./provider-hub.module.css";

const KIND_CHIPS: { key: KindFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "llm", label: "Language models" },
  { key: "speech", label: "Speech to text" },
  { key: "router", label: "Routers" },
];

const MODEL_CHIPS: { key: keyof Omit<ModelFilter, "query">; label: string }[] =
  [
    { key: "runsHere", label: "Runs here" },
    { key: "cheapest", label: "Cheapest first" },
    { key: "audio", label: "Hears audio" },
    { key: "json", label: "JSON output" },
  ];

const MODEL_LIMIT = 200;

const href = (id: string) => `/sales-xray/providers?tab=hub&provider=${id}`;

/** A provider's mark: its initials on its own colour (no brand artwork). */
/**
 * Two letters for a provider's mark: the first letters of its first two words, or of a
 * one-word name's capitals ("OpenRouter" OR, "OpenAI" OA, "DeepSeek" DS), else its first two.
 */
export function initials(name: string): string {
  const words = name
    .replace(/\(.*\)/, "")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length > 1)
    return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase();
  const word = words[0] ?? "";
  const capitals = word.replace(/[^A-Z]/g, "");
  return (
    capitals.length > 1 ? capitals.slice(0, 2) : word.slice(0, 2)
  ).toUpperCase();
}

/** A provider's mark: its initials on its own colour (no brand artwork). */
export function ProviderMark({ id, name }: { id: string; name: string }) {
  return (
    <span className={styles.mark} data-provider={id} aria-hidden="true">
      {initials(name) || id.slice(0, 2).toUpperCase()}
    </span>
  );
}

const tone = (state: HubProvider["pipeline"]) =>
  state === "ready" ? "good" : state === "planned" ? "warn" : "neutral";

/** A provider's line in the list: failing today, and this month's spend here. */
function ListHealth({ row }: { row: ProviderHealthRow | undefined }) {
  if (!row) return null;
  return (
    <>
      {row.state === "attention" ? (
        <Badge tone="warn">Failing today</Badge>
      ) : null}
      {row.spend?.monthInr ? (
        <span>{spendWords(row.spend.monthInr)} this month</span>
      ) : null}
    </>
  );
}

/** The chosen provider in this environment: spend, failures, and what fixes the latest. */
function HealthHere({
  provider,
  health,
}: {
  provider: HubProvider;
  health: ProviderHealth;
}) {
  const row = health.providers[provider.id];
  const latest = row?.failures?.latest ?? null;
  return (
    <section
      className={styles.health}
      aria-label={`${provider.name} in ${health.environment}`}
      data-state={row?.state ?? "idle"}
    >
      <h3>Here in {health.environment}</h3>
      {row?.spend ? (
        <dl className={styles.spend}>
          <div>
            <dt>Today</dt>
            <dd>{spendWords(row.spend.todayInr)}</dd>
          </div>
          <div>
            <dt>This month</dt>
            <dd>{spendWords(row.spend.monthInr)}</dd>
          </div>
          <div>
            <dt>Last {health.windowDays} days</dt>
            <dd>
              {spendWords(row.spend.windowInr)}{" "}
              <small>
                {row.spend.requests}{" "}
                {row.spend.requests === 1 ? "request" : "requests"}
              </small>
            </dd>
          </div>
        </dl>
      ) : (
        <p className={styles.muted}>
          Not used here in the last {health.windowDays} days.
        </p>
      )}
      <p className={styles.failures}>
        {row
          ? failureCountWords(row, health.failureDays)
          : `No failures in the last ${health.failureDays} days.`}
      </p>
      {latest ? (
        <div className={styles.latest}>
          <p>
            <strong suppressHydrationWarning>
              Latest {agoWords(latest.at)}
            </strong>
            , in {latest.featureLabel}
            {latest.status ? ` (HTTP ${latest.status})` : ""}: {latest.words}
          </p>
          {latest.fix === "console" && provider.console ? (
            <a
              href={provider.console}
              target="_blank"
              rel="noreferrer"
              className={styles.console}
            >
              {latest.status === 402 ? "Top up credit" : "Open the console"}
            </a>
          ) : null}
        </div>
      ) : null}
      <small className={styles.source}>
        All AI here this month: {spendWords(health.month.spentInr)} of the{" "}
        {spendWords(health.month.capInr)} cap. List-price estimates, never a
        charge. <Link href="/ai-spend">AI spend</Link>
      </small>
    </section>
  );
}

export function ProviderHub({
  hub,
  health = null,
  keys = null,
}: {
  hub: Hub;
  health?: ProviderHealth | null;
  keys?: ProviderKeys | null;
}) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [filter, setFilter] = useState<ModelFilter>(NO_MODEL_FILTER);
  const found = useMemo(
    () => searchProviders(hub.providers, query, kind),
    [hub.providers, query, kind],
  );
  const chosen = hub.providers.find((item) => item.id === hub.selected) ?? null;
  const models = useMemo(
    () => filterModels(hub.models, filter),
    [hub.models, filter],
  );

  return (
    <div className={styles.hub} data-chosen={chosen ? "" : undefined}>
      <section className={styles.list} aria-label="Providers">
        <input
          type="search"
          className={styles.search}
          placeholder="Search providers: Gemini, Groq, ElevenLabs, Hindi…"
          aria-label="Search providers"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div
          className={styles.chips}
          role="group"
          aria-label="Kind of provider"
        >
          {KIND_CHIPS.map((chip) => (
            <button
              key={chip.key}
              type="button"
              className={styles.chip}
              aria-pressed={kind === chip.key}
              onClick={() => setKind(chip.key)}
            >
              {chip.label}
            </button>
          ))}
        </div>
        {found.length ? (
          <ul className={styles.providers}>
            {found.map((provider) => (
              <li key={provider.id}>
                <Link
                  href={href(provider.id)}
                  scroll={false}
                  className={styles.provider}
                  aria-current={
                    provider.id === hub.selected ? "true" : undefined
                  }
                >
                  <ProviderMark id={provider.id} name={provider.name} />
                  <span className={styles.providerText}>
                    <strong>{provider.name}</strong>
                    <small>{provider.blurb}</small>
                    <span className={styles.providerMeta}>
                      <Badge tone={tone(provider.pipeline)}>
                        {PIPELINE_WORDS[provider.pipeline]}
                      </Badge>
                      <span>
                        {provider.models
                          ? `${provider.models} ${provider.models === 1 ? "model" : "models"}`
                          : "models after its key is added"}
                      </span>
                      <ListHealth row={health?.providers[provider.id]} />
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.none}>
            No provider matches &ldquo;{query}&rdquo;. Try a model family such
            as llama, or a kind such as speech.
          </p>
        )}
      </section>

      <section
        className={styles.detail}
        aria-label={chosen ? chosen.name : "Choose a provider"}
      >
        {chosen ? (
          <>
            <Link
              href="/sales-xray/providers?tab=hub"
              scroll={false}
              className={styles.back}
            >
              All providers
            </Link>
            <header className={styles.detailHead}>
              <ProviderMark id={chosen.id} name={chosen.name} />
              <div>
                <h2>{chosen.name}</h2>
                <p>{chosen.blurb}</p>
              </div>
              {chosen.console ? (
                <a
                  href={chosen.console}
                  target="_blank"
                  rel="noreferrer"
                  className={styles.console}
                >
                  Usage, credit and keys
                </a>
              ) : null}
            </header>
            <p className={styles.keyNote}>
              {chosen.pipeline === "ready"
                ? "The analysis pipeline can call this provider today. "
                : chosen.pipeline === "planned"
                  ? "An adapter is designed but not built yet, so models can be compared, not used. "
                  : "Not wired to the pipeline yet: browse and compare its models. "}
              {keys
                ? "Its key is sealed per environment and never shown again."
                : "Keys are added here once this server offers it."}
            </p>
            {keys ? <ProviderKey provider={chosen} keys={keys} /> : null}
            {health ? <HealthHere provider={chosen} health={health} /> : null}
            <div className={styles.modelTools}>
              <input
                type="search"
                className={styles.search}
                placeholder={`Search ${chosen.name} models`}
                aria-label="Search models"
                value={filter.query}
                onChange={(event) =>
                  setFilter({ ...filter, query: event.target.value })
                }
              />
              <div
                className={styles.chips}
                role="group"
                aria-label="Filter models"
              >
                {MODEL_CHIPS.map((chip) => (
                  <button
                    key={chip.key}
                    type="button"
                    className={styles.chip}
                    aria-pressed={filter[chip.key]}
                    onClick={() =>
                      setFilter({ ...filter, [chip.key]: !filter[chip.key] })
                    }
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
              <small className={styles.count} role="status">
                Showing {Math.min(models.length, MODEL_LIMIT)} of{" "}
                {hub.models.length}
              </small>
            </div>
            {models.length ? (
              <ul className={styles.models}>
                {models.slice(0, MODEL_LIMIT).map((model) => (
                  <li key={model.id} className={styles.model}>
                    <span className={styles.modelName}>
                      <strong>{model.name}</strong>
                      <code>{model.id}</code>
                    </span>
                    <span className={styles.modelFacts}>
                      <span title="Context window">
                        {contextWords(model.context)} context
                      </span>
                      <span>
                        {model.audioIn
                          ? "Hears audio"
                          : model.inputs.join(", ") || "text"}
                      </span>
                      {model.json ? <span>JSON</span> : null}
                    </span>
                    <span className={styles.price}>
                      {priceWords(model)}
                      <small>{rupeeWords(model, hub.usdToInr)}</small>
                    </span>
                    <span className={styles.stages}>
                      {model.stages.map((stage) => (
                        <Badge key={stage} tone="good">
                          {stage}
                        </Badge>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.none}>
                {hub.models.length
                  ? "No model matches these filters."
                  : "This provider's models appear here once its key is added."}
              </p>
            )}
          </>
        ) : (
          <p className={styles.pick}>
            Choose a provider to see its models, what each costs and which
            pipeline stages can run on it.
          </p>
        )}
        <p className={styles.source}>
          {hub.catalogue.problem
            ? `${hub.catalogue.problem} Showing the pipeline's own models and the price sheet.`
            : `Models and list prices from ${hub.catalogue.source}'s public catalogue, the provider registry and our price sheet. Prices are in US dollars; rupees at ₹${hub.usdToInr} per $1.`}
        </p>
      </section>
    </div>
  );
}
