"use client";

/**
 * Admin's Providers hub (owner, 20 Oct 2026: "just search for a provider name, add, add key
 * and boom it's there, and all its models listed"). Type to find a provider; pick it to
 * see every model it offers with context, inputs, JSON support, list prices and the
 * pipeline stages it can run here. Searching filters as you type; the chosen provider is
 * in the link, so a page can be shared. Keys arrive in the next step (sealed, write-only).
 */
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "../ui/kit";
import {
  NO_MODEL_FILTER,
  PIPELINE_WORDS,
  contextWords,
  filterModels,
  priceWords,
  rupeeWords,
  searchProviders,
  type Hub,
  type HubProvider,
  type KindFilter,
  type ModelFilter,
} from "./provider-hub-data";
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
export function ProviderMark({ id, name }: { id: string; name: string }) {
  const letters = name
    .replace(/\(.*\)/, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
  return (
    <span className={styles.mark} data-provider={id} aria-hidden="true">
      {letters || id.slice(0, 2).toUpperCase()}
    </span>
  );
}

const tone = (state: HubProvider["pipeline"]) =>
  state === "ready" ? "good" : state === "planned" ? "warn" : "neutral";

export function ProviderHub({ hub }: { hub: Hub }) {
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
              Adding a key here is the next step: it will be sealed for this
              environment and never shown again.
            </p>
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
