"use client";

/**
 * The Offer Studio: pick catalogue features into a value stack, score the
 * offer with Hormozi's value equation, add bonuses, a guarantee, scarcity,
 * urgency and a name, write the positioning, ideal customer and voice, set
 * internal price tiers, collect ideas, and export a one-pager. Offers live in
 * this browser (offer-store.ts) with JSON export and import.
 */
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Copy,
  Download,
  Lightbulb,
  Plus,
  Printer,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState, type ReactNode } from "react";

import {
  CATALOGUE,
  NO_FILTERS,
  filterFeatures,
  productName,
} from "../catalogue/catalogue-data";
import { StatusPill } from "../catalogue/catalogue-view";
import {
  GUARANTEES,
  IDEA_COLUMNS,
  IDEA_PROMPTS,
  TEMPLATES,
  TONES,
  featureById,
  fillPrompt,
  fromTemplate,
  itemLabel,
  mergeStudios,
  newId,
  normalizeStudio,
  onePagerMarkdown,
  positioningStatement,
  rupees,
  stackTotal,
  suggestedName,
  valueMultiple,
  valuePosition,
  valueScore,
  valueVerdict,
  type GuaranteeKind,
  type IdeaColumn,
  type Offer,
  type Studio,
} from "./offer-model";
import { STUDIO_KEY, useStudio, withOffer } from "./offer-store";
import styles from "./offers.module.css";

const TABS = [
  ["bundle", "Bundle"],
  ["value", "Value"],
  ["enhance", "Enhance"],
  ["position", "Position"],
  ["pricing", "Pricing"],
  ["ideas", "Ideas"],
  ["onepager", "One-pager"],
] as const;
type Tab = (typeof TABS)[number][0];

type Update = (change: (offer: Offer) => Offer) => void;

function Text({
  label,
  value,
  onChange,
  placeholder,
  rows,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  hint?: string;
}) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>{label}</span>
      {rows ? (
        <textarea
          rows={rows}
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {hint ? <span className={styles.hint}>{hint}</span> : null}
    </label>
  );
}

function Money({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className={`${styles.field} ${styles.money}`}>
      <span className={styles.label}>{label}</span>
      <span className={styles.moneyInput}>
        <span aria-hidden="true">₹</span>
        <input
          inputMode="numeric"
          value={value ? String(value) : ""}
          placeholder="0"
          onChange={(event) => {
            const digits = event.target.value.replace(/[^\d]/g, "");
            onChange(digits ? Math.min(Number(digits), 1e10) : 0);
          }}
        />
      </span>
    </label>
  );
}

function Card({
  title,
  sub,
  action,
  children,
}: {
  title: string;
  sub?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.card}>
      <header className={styles.cardHead}>
        <span>
          <h3>{title}</h3>
          {sub ? <p>{sub}</p> : null}
        </span>
        {action}
      </header>
      {children}
    </section>
  );
}

function IconButton({
  label,
  onClick,
  children,
  disabled,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={styles.iconButton}
      onClick={onClick}
      aria-label={label}
      title={label}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

/* ---------- Bundle ---------- */

function BundleTab({ offer, update }: { offer: Offer; update: Update }) {
  const [query, setQuery] = useState("");
  const inStack = new Set(offer.stack.map((item) => item.featureId));
  const matches = useMemo(
    () =>
      filterFeatures(CATALOGUE.features, { ...NO_FILTERS, query }).slice(0, 40),
    [query],
  );
  const toggle = (featureId: string) =>
    update((o) => ({
      ...o,
      stack: inStack.has(featureId)
        ? o.stack.filter((item) => item.featureId !== featureId)
        : [...o.stack, { featureId, worth: 0, label: "" }],
    }));
  const move = (index: number, by: number) =>
    update((o) => {
      const stack = [...o.stack];
      const [item] = stack.splice(index, 1);
      if (item) stack.splice(index + by, 0, item);
      return { ...o, stack };
    });
  return (
    <div className={styles.split}>
      <Card
        title="Pick features"
        sub={`${CATALOGUE.features.length} in the catalogue`}
      >
        <label className={styles.search}>
          <Search size={15} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search the catalogue"
            aria-label="Search the catalogue"
          />
        </label>
        <ul className={styles.pickList}>
          {matches.map((feature) => (
            <li key={feature.id}>
              <button
                type="button"
                className={styles.pick}
                aria-pressed={inStack.has(feature.id)}
                onClick={() => toggle(feature.id)}
              >
                <span className={styles.pickMain}>
                  <strong>{feature.name}</strong>
                  <span>{feature.value}</span>
                </span>
                <span className={styles.pickMeta}>
                  <StatusPill feature={feature} />
                  <span className={styles.pickMark} aria-hidden="true">
                    {inStack.has(feature.id) ? "✓" : "+"}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <Card
        title="Value stack"
        sub="Name each item in the buyer's words and say what it is worth to them"
        action={
          <span className={styles.total}>{rupees(stackTotal(offer))}</span>
        }
      >
        {offer.stack.length ? (
          <ol className={styles.stack}>
            {offer.stack.map((item, index) => {
              const feature = featureById(item.featureId);
              return (
                <li key={item.featureId}>
                  <span className={styles.stackHead}>
                    <strong>{feature?.name ?? item.featureId}</strong>
                    <span className={styles.rowTools}>
                      <IconButton
                        label="Move up"
                        onClick={() => move(index, -1)}
                        disabled={index === 0}
                      >
                        <ArrowUp size={14} />
                      </IconButton>
                      <IconButton
                        label="Move down"
                        onClick={() => move(index, 1)}
                        disabled={index === offer.stack.length - 1}
                      >
                        <ArrowDown size={14} />
                      </IconButton>
                      <IconButton
                        label="Remove"
                        onClick={() => toggle(item.featureId)}
                      >
                        <Trash2 size={14} />
                      </IconButton>
                    </span>
                  </span>
                  <span className={styles.stackFields}>
                    <Text
                      label="In the buyer's words"
                      value={item.label}
                      placeholder={feature?.name}
                      onChange={(label) =>
                        update((o) => ({
                          ...o,
                          stack: o.stack.map((s) =>
                            s.featureId === item.featureId
                              ? { ...s, label }
                              : s,
                          ),
                        }))
                      }
                    />
                    <Money
                      label="Worth to them"
                      value={item.worth}
                      onChange={(worth) =>
                        update((o) => ({
                          ...o,
                          stack: o.stack.map((s) =>
                            s.featureId === item.featureId
                              ? { ...s, worth }
                              : s,
                          ),
                        }))
                      }
                    />
                  </span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className={styles.empty}>
            Pick features on the left, or from any card in the{" "}
            <Link href="/catalogue">Feature catalogue</Link>.
          </p>
        )}
      </Card>
    </div>
  );
}

/* ---------- Value ---------- */

const DRIVERS = [
  {
    key: "dream",
    title: "Dream outcome",
    sub: "What they really want; higher is better",
    placeholder: "e.g. Every seller closes like your best one",
    low: "Small",
    high: "Life-changing",
  },
  {
    key: "likelihood",
    title: "Perceived likelihood",
    sub: "How sure they are it works for them; higher is better",
    placeholder: "Proof: results, demos, guarantee, case studies",
    low: "Doubtful",
    high: "Certain",
  },
  {
    key: "time",
    title: "Time delay",
    sub: "How long until they feel the result; lower is better",
    placeholder: "e.g. First Report within minutes of the first call",
    low: "Instant",
    high: "Months",
  },
  {
    key: "effort",
    title: "Effort and sacrifice",
    sub: "What it costs them in work and change; lower is better",
    placeholder: "e.g. Nothing to learn: the phone records and files itself",
    low: "Effortless",
    high: "Painful",
  },
] as const;

export function ValueGauge({ offer }: { offer: Offer }) {
  const score = valueScore(offer.value);
  const verdict = valueVerdict(score);
  return (
    <div className={styles.gauge} data-tone={verdict.tone}>
      <span className={styles.gaugeHead}>
        <span>Value</span>
        <strong>
          {score >= 10 ? score.toFixed(0) : score.toFixed(1)}
          <small> · {verdict.label}</small>
        </strong>
      </span>
      <span className={styles.gaugeTrack} aria-hidden="true">
        <span
          className={styles.gaugeMark}
          style={{ left: `${valuePosition(score) * 100}%` }}
        />
      </span>
      <span className={styles.hint}>
        (dream × likelihood) ÷ (time × effort)
      </span>
    </div>
  );
}

function ValueTab({ offer, update }: { offer: Offer; update: Update }) {
  const setDriver = (
    key: keyof Offer["value"],
    patch: Partial<Offer["value"]["dream"]>,
  ) =>
    update((o) => ({
      ...o,
      value: { ...o.value, [key]: { ...o.value[key], ...patch } },
    }));
  return (
    <div className={styles.stackCards}>
      <div className={styles.drivers}>
        {DRIVERS.map((d) => {
          const current = offer.value[d.key];
          return (
            <Card key={d.key} title={d.title} sub={d.sub}>
              <label className={styles.slider}>
                <span className={styles.sliderEnds}>
                  <span>{d.low}</span>
                  <strong>{current.score}</strong>
                  <span>{d.high}</span>
                </span>
                <input
                  type="range"
                  min={1}
                  max={10}
                  value={current.score}
                  aria-label={`${d.title}, 1 to 10`}
                  onChange={(event) =>
                    setDriver(d.key, { score: Number(event.target.value) })
                  }
                />
              </label>
              <Text
                label="How this offer moves it"
                rows={2}
                value={current.text}
                placeholder={d.placeholder}
                onChange={(text) => setDriver(d.key, { text })}
              />
            </Card>
          );
        })}
      </div>
      <Card
        title="Obstacles to solutions"
        sub="List every reason they wouldn't get the result, then the answer to each"
        action={
          <button
            type="button"
            className={styles.add}
            onClick={() =>
              update((o) => ({
                ...o,
                obstacles: [
                  ...o.obstacles,
                  {
                    id: newId("obstacle"),
                    problem: "",
                    solution: "",
                    featureId: "",
                  },
                ],
              }))
            }
          >
            <Plus size={14} aria-hidden="true" /> Obstacle
          </button>
        }
      >
        {offer.obstacles.length ? (
          <ul className={styles.rows}>
            {offer.obstacles.map((x) => {
              const set = (patch: Partial<typeof x>) =>
                update((o) => ({
                  ...o,
                  obstacles: o.obstacles.map((y) =>
                    y.id === x.id ? { ...y, ...patch } : y,
                  ),
                }));
              return (
                <li key={x.id} className={styles.obstacle}>
                  <Text
                    label="Obstacle"
                    value={x.problem}
                    placeholder="e.g. My sellers won't upload calls"
                    onChange={(problem) => set({ problem })}
                  />
                  <Text
                    label="Solution"
                    value={x.solution}
                    placeholder="e.g. The phone records and files every call"
                    onChange={(solution) => set({ solution })}
                  />
                  <label className={styles.field}>
                    <span className={styles.label}>Feature</span>
                    <select
                      value={x.featureId}
                      onChange={(event) =>
                        set({ featureId: event.target.value })
                      }
                    >
                      <option value="">None yet</option>
                      {CATALOGUE.features.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <IconButton
                    label="Remove obstacle"
                    onClick={() =>
                      update((o) => ({
                        ...o,
                        obstacles: o.obstacles.filter((y) => y.id !== x.id),
                      }))
                    }
                  >
                    <Trash2 size={14} />
                  </IconButton>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className={styles.empty}>
            No obstacles yet. Each one you solve raises perceived likelihood.
          </p>
        )}
      </Card>
    </div>
  );
}

/* ---------- Enhance ---------- */

function EnhanceTab({ offer, update }: { offer: Offer; update: Update }) {
  const naming = offer.naming;
  const setNaming = (patch: Partial<Offer["naming"]>) =>
    update((o) => ({ ...o, naming: { ...o.naming, ...patch } }));
  const suggestion = suggestedName(naming);
  return (
    <div className={styles.stackCards}>
      <Card
        title="Bonuses"
        sub="Each solves one more obstacle; worth far more than it costs us"
        action={
          <button
            type="button"
            className={styles.add}
            onClick={() =>
              update((o) => ({
                ...o,
                bonuses: [
                  ...o.bonuses,
                  { id: newId("bonus"), name: "", worth: 0, solves: "" },
                ],
              }))
            }
          >
            <Plus size={14} aria-hidden="true" /> Bonus
          </button>
        }
      >
        {offer.bonuses.length ? (
          <ul className={styles.rows}>
            {offer.bonuses.map((b) => {
              const set = (patch: Partial<typeof b>) =>
                update((o) => ({
                  ...o,
                  bonuses: o.bonuses.map((y) =>
                    y.id === b.id ? { ...y, ...patch } : y,
                  ),
                }));
              return (
                <li key={b.id} className={styles.bonus}>
                  <Text
                    label="Bonus"
                    value={b.name}
                    placeholder="e.g. Done-for-you lead stages setup"
                    onChange={(name) => set({ name })}
                  />
                  <Money
                    label="Worth"
                    value={b.worth}
                    onChange={(worth) => set({ worth })}
                  />
                  <Text
                    label="Solves"
                    value={b.solves}
                    placeholder="The obstacle it removes"
                    onChange={(solves) => set({ solves })}
                  />
                  <IconButton
                    label="Remove bonus"
                    onClick={() =>
                      update((o) => ({
                        ...o,
                        bonuses: o.bonuses.filter((y) => y.id !== b.id),
                      }))
                    }
                  >
                    <Trash2 size={14} />
                  </IconButton>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className={styles.empty}>No bonuses yet.</p>
        )}
      </Card>
      <Card title="Guarantee" sub={GUARANTEES[offer.guarantee.kind].hint}>
        <div
          className={styles.segmented}
          role="radiogroup"
          aria-label="Guarantee"
        >
          {(Object.keys(GUARANTEES) as GuaranteeKind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              role="radio"
              aria-checked={offer.guarantee.kind === kind}
              onClick={() =>
                update((o) => ({ ...o, guarantee: { ...o.guarantee, kind } }))
              }
            >
              {GUARANTEES[kind].label}
            </button>
          ))}
        </div>
        <Text
          label="In our words"
          rows={2}
          value={offer.guarantee.text}
          placeholder="e.g. If your team doesn't get a Report on every call in the first 14 days, we set it up with you for free."
          onChange={(text) =>
            update((o) => ({ ...o, guarantee: { ...o.guarantee, text } }))
          }
        />
      </Card>
      <div className={styles.pair}>
        <Card title="Scarcity" sub="A real limit on supply">
          <Text
            label="What is limited"
            rows={2}
            value={offer.scarcity}
            placeholder="e.g. 10 onboarding slots a month"
            onChange={(scarcity) => update((o) => ({ ...o, scarcity }))}
          />
        </Card>
        <Card title="Urgency" sub="A real reason to act now">
          <Text
            label="Why now"
            rows={2}
            value={offer.urgency}
            placeholder="e.g. Founding price until the next cohort starts"
            onChange={(urgency) => update((o) => ({ ...o, urgency }))}
          />
        </Card>
      </div>
      <Card
        title="Name it (MAGIC)"
        sub="Magnet · Avatar · Goal · Interval · Container; use three to five"
      >
        <div className={styles.grid5}>
          <Text
            label="Magnet"
            value={naming.magnet}
            placeholder="e.g. Free, Founding"
            onChange={(magnet) => setNaming({ magnet })}
          />
          <Text
            label="Avatar"
            value={naming.avatar}
            placeholder="e.g. Real estate teams"
            onChange={(avatar) => setNaming({ avatar })}
          />
          <Text
            label="Goal"
            value={naming.goal}
            placeholder="e.g. Close more site visits"
            onChange={(goal) => setNaming({ goal })}
          />
          <Text
            label="Interval"
            value={naming.interval}
            placeholder="e.g. 30-day"
            onChange={(interval) => setNaming({ interval })}
          />
          <Text
            label="Container"
            value={naming.container}
            placeholder="e.g. Sprint, System, Program"
            onChange={(container) => setNaming({ container })}
          />
        </div>
        {suggestion ? (
          <p className={styles.suggestion}>
            <span>Suggested</span>
            <strong>{suggestion}</strong>
            <button
              type="button"
              className={styles.add}
              onClick={() => setNaming({ chosen: suggestion })}
            >
              Use this name
            </button>
          </p>
        ) : null}
        <Text
          label="Chosen name"
          value={naming.chosen}
          placeholder="What the one-pager calls it"
          onChange={(chosen) => setNaming({ chosen })}
        />
      </Card>
    </div>
  );
}

/* ---------- Position ---------- */

function PositionTab({ offer, update }: { offer: Offer; update: Update }) {
  const p = offer.positioning;
  const setP = (patch: Partial<Offer["positioning"]>) =>
    update((o) => ({ ...o, positioning: { ...o.positioning, ...patch } }));
  const setIcp = (patch: Partial<Offer["icp"]>) =>
    update((o) => ({ ...o, icp: { ...o.icp, ...patch } }));
  const setVoice = (patch: Partial<Offer["voice"]>) =>
    update((o) => ({ ...o, voice: { ...o.voice, ...patch } }));
  const statement = positioningStatement(
    p,
    offer.naming.chosen.trim() || offer.name,
  );
  return (
    <div className={styles.stackCards}>
      <Card
        title="Positioning"
        sub="For … who …, it is a … that …. Unlike …, it …"
      >
        <div className={styles.grid2}>
          <Text
            label="For"
            value={p.forWho}
            placeholder="e.g. owners of 5-50 seller teams"
            onChange={(forWho) => setP({ forWho })}
          />
          <Text
            label="Who"
            value={p.need}
            placeholder="e.g. can't hear what happens on their calls"
            onChange={(need) => setP({ need })}
          />
          <Text
            label="It is a"
            value={p.category}
            placeholder="e.g. sales CRM that listens to every call"
            onChange={(category) => setP({ category })}
          />
          <Text
            label="That"
            value={p.benefit}
            placeholder="e.g. turns every call into coaching and the next step"
            onChange={(benefit) => setP({ benefit })}
          />
          <Text
            label="Unlike"
            value={p.unlike}
            placeholder="e.g. spreadsheets and dialers that only count calls"
            onChange={(unlike) => setP({ unlike })}
          />
          <Text
            label="It"
            value={p.because}
            placeholder="e.g. knows what was said and what to do about it"
            onChange={(because) => setP({ because })}
          />
        </div>
        {statement ? (
          <blockquote className={styles.quote}>{statement}</blockquote>
        ) : null}
      </Card>
      <Card title="Ideal customer" sub="Who buys fastest and gets the most">
        <div className={styles.grid2}>
          <Text
            label="Who they are"
            value={offer.icp.who}
            placeholder="Industry and kind of business"
            onChange={(who) => setIcp({ who })}
          />
          <Text
            label="Size"
            value={offer.icp.size}
            placeholder="Team size, revenue, calls a day"
            onChange={(size) => setIcp({ size })}
          />
          <Text
            label="Who signs"
            value={offer.icp.buyer}
            placeholder="Owner, sales head, founder"
            onChange={(buyer) => setIcp({ buyer })}
          />
          <Text
            label="Where to find them"
            value={offer.icp.where}
            placeholder="Channels, communities, events"
            onChange={(where) => setIcp({ where })}
          />
          <Text
            label="Pains"
            rows={3}
            value={offer.icp.pains}
            placeholder="What keeps them up at night"
            onChange={(pains) => setIcp({ pains })}
          />
          <Text
            label="Buying triggers"
            rows={3}
            value={offer.icp.triggers}
            placeholder="What happens right before they look for this"
            onChange={(triggers) => setIcp({ triggers })}
          />
          <Text
            label="Objections"
            rows={3}
            value={offer.icp.objections}
            placeholder="What they say to say no, and our answer"
            onChange={(objections) => setIcp({ objections })}
          />
        </div>
      </Card>
      <Card title="Brand voice" sub="How we sound when we sell this">
        <div className={styles.tones} role="group" aria-label="Tone">
          {TONES.map((tone) => {
            const on = offer.voice.tones.includes(tone);
            return (
              <button
                key={tone}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  setVoice({
                    tones: on
                      ? offer.voice.tones.filter((t) => t !== tone)
                      : [...offer.voice.tones, tone],
                  })
                }
              >
                {tone}
              </button>
            );
          })}
        </div>
        <div className={styles.grid2}>
          <Text
            label="Tagline"
            value={offer.voice.tagline}
            placeholder="One line they remember"
            onChange={(tagline) => setVoice({ tagline })}
          />
          <Text
            label="Elevator pitch"
            rows={2}
            value={offer.voice.pitch}
            placeholder="Thirty seconds, in their words"
            onChange={(pitch) => setVoice({ pitch })}
          />
          <Text
            label="We say"
            rows={2}
            value={offer.voice.say}
            placeholder="Words and phrases we use"
            onChange={(say) => setVoice({ say })}
          />
          <Text
            label="We never say"
            rows={2}
            value={offer.voice.never}
            placeholder="Jargon and promises we avoid"
            onChange={(never) => setVoice({ never })}
          />
        </div>
      </Card>
    </div>
  );
}

/* ---------- Pricing ---------- */

function PricingTab({ offer, update }: { offer: Offer; update: Update }) {
  const addTier = () =>
    update((o) => ({
      ...o,
      tiers: [
        ...o.tiers,
        {
          id: newId("tier"),
          name:
            ["Starter", "Growth", "Scale", "Enterprise"][o.tiers.length] ??
            "Plan",
          monthly: 0,
          yearly: 0,
          seats: "",
          minutes: "",
          featureIds: o.stack.map((s) => s.featureId),
          highlight: false,
          note: "",
        },
      ],
    }));
  const setTier = (id: string, patch: Partial<Offer["tiers"][number]>) =>
    update((o) => ({
      ...o,
      tiers: o.tiers.map((t) => (t.id === id ? { ...t, ...patch } : t)),
    }));
  return (
    <div className={styles.stackCards}>
      <p className={styles.internal}>
        Internal only. Prices never appear in Sales X-Ray; they reach a buyer
        only on a one-pager you choose to export with prices.
      </p>
      <div className={styles.tiers}>
        {offer.tiers.map((tier) => {
          const multiple = valueMultiple(offer, tier);
          return (
            <section
              key={tier.id}
              className={styles.tier}
              data-highlight={tier.highlight ? "" : undefined}
            >
              <span className={styles.stackHead}>
                <input
                  className={styles.tierName}
                  value={tier.name}
                  aria-label="Tier name"
                  onChange={(event) =>
                    setTier(tier.id, { name: event.target.value })
                  }
                />
                <IconButton
                  label="Remove tier"
                  onClick={() =>
                    update((o) => ({
                      ...o,
                      tiers: o.tiers.filter((t) => t.id !== tier.id),
                    }))
                  }
                >
                  <Trash2 size={14} />
                </IconButton>
              </span>
              <span className={styles.grid2}>
                <Money
                  label="Per month"
                  value={tier.monthly}
                  onChange={(monthly) => setTier(tier.id, { monthly })}
                />
                <Money
                  label="Per year"
                  value={tier.yearly}
                  onChange={(yearly) => setTier(tier.id, { yearly })}
                />
                <Text
                  label="Seats"
                  value={tier.seats}
                  placeholder="e.g. Up to 5"
                  onChange={(seats) => setTier(tier.id, { seats })}
                />
                <Text
                  label="Minutes"
                  value={tier.minutes}
                  placeholder="e.g. 3,000 a month"
                  onChange={(minutes) => setTier(tier.id, { minutes })}
                />
              </span>
              <label className={styles.check}>
                <input
                  type="checkbox"
                  checked={tier.highlight}
                  onChange={(event) =>
                    setTier(tier.id, { highlight: event.target.checked })
                  }
                />
                Most popular
              </label>
              <Text
                label="Note"
                value={tier.note}
                placeholder="Who it's for, what's special"
                onChange={(note) => setTier(tier.id, { note })}
              />
              <p className={styles.multiple}>
                {multiple === null
                  ? "Set a price to see value for money"
                  : `Stack worth ${multiple.toFixed(1)}× the yearly price`}
              </p>
            </section>
          );
        })}
        <button type="button" className={styles.addTier} onClick={addTier}>
          <Plus size={18} aria-hidden="true" />
          Add a tier
        </button>
      </div>
      {offer.tiers.length && offer.stack.length ? (
        <Card title="What each tier includes">
          <div className={styles.matrixWrap}>
            <table className={styles.matrix}>
              <thead>
                <tr>
                  <th scope="col">Feature</th>
                  {offer.tiers.map((tier) => (
                    <th key={tier.id} scope="col">
                      {tier.name || "Plan"}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {offer.stack.map((item) => (
                  <tr key={item.featureId}>
                    <th scope="row">{itemLabel(item)}</th>
                    {offer.tiers.map((tier) => {
                      const on = tier.featureIds.includes(item.featureId);
                      return (
                        <td key={tier.id}>
                          <input
                            type="checkbox"
                            checked={on}
                            aria-label={`${itemLabel(item)} in ${tier.name || "plan"}`}
                            onChange={() =>
                              setTier(tier.id, {
                                featureIds: on
                                  ? tier.featureIds.filter(
                                      (f) => f !== item.featureId,
                                    )
                                  : [...tier.featureIds, item.featureId],
                              })
                            }
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

/* ---------- Ideas ---------- */

const COLUMN_ORDER: IdeaColumn[] = ["idea", "try", "keep", "drop"];

function IdeasTab({ offer, update }: { offer: Offer; update: Update }) {
  const [draft, setDraft] = useState("");
  const add = (text: string) => {
    const clean = text.trim();
    if (!clean) return;
    update((o) => ({
      ...o,
      ideas: [
        ...o.ideas,
        { id: newId("idea"), text: clean, column: "idea", votes: 0 },
      ],
    }));
  };
  const setIdea = (id: string, patch: Partial<Offer["ideas"][number]>) =>
    update((o) => ({
      ...o,
      ideas: o.ideas.map((i) => (i.id === id ? { ...i, ...patch } : i)),
    }));
  return (
    <div className={styles.stackCards}>
      <Card title="Sparks" sub="Tap a question to put it on the board">
        <div className={styles.sparks}>
          {IDEA_PROMPTS.map((prompt) => {
            const text = fillPrompt(prompt, offer);
            return (
              <button key={prompt} type="button" onClick={() => add(text)}>
                <Lightbulb size={14} aria-hidden="true" />
                {text}
              </button>
            );
          })}
        </div>
        <form
          className={styles.ideaForm}
          onSubmit={(event) => {
            event.preventDefault();
            add(draft);
            setDraft("");
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Write an idea and press Enter"
            aria-label="New idea"
          />
          <button type="submit" className={styles.add}>
            <Plus size={14} aria-hidden="true" /> Add
          </button>
        </form>
      </Card>
      <div className={styles.board}>
        {COLUMN_ORDER.map((column, columnIndex) => {
          const ideas = offer.ideas
            .filter((i) => i.column === column)
            .sort((a, b) => b.votes - a.votes);
          return (
            <section
              key={column}
              className={styles.column}
              data-column={column}
            >
              <h3>
                {IDEA_COLUMNS[column]} <span>{ideas.length}</span>
              </h3>
              <ul>
                {ideas.map((idea) => (
                  <li key={idea.id} className={styles.idea}>
                    <textarea
                      value={idea.text}
                      rows={2}
                      aria-label="Idea"
                      onChange={(event) =>
                        setIdea(idea.id, { text: event.target.value })
                      }
                    />
                    <span className={styles.ideaTools}>
                      <button
                        type="button"
                        className={styles.vote}
                        onClick={() =>
                          setIdea(idea.id, {
                            votes: Math.min(99, idea.votes + 1),
                          })
                        }
                        aria-label={`Vote, ${idea.votes} so far`}
                      >
                        ▲ {idea.votes}
                      </button>
                      <IconButton
                        label="Move left"
                        disabled={columnIndex === 0}
                        onClick={() =>
                          setIdea(idea.id, {
                            column: COLUMN_ORDER[columnIndex - 1] ?? column,
                          })
                        }
                      >
                        <ArrowLeft size={14} />
                      </IconButton>
                      <IconButton
                        label="Move right"
                        disabled={columnIndex === COLUMN_ORDER.length - 1}
                        onClick={() =>
                          setIdea(idea.id, {
                            column: COLUMN_ORDER[columnIndex + 1] ?? column,
                          })
                        }
                      >
                        <ArrowRight size={14} />
                      </IconButton>
                      <IconButton
                        label="Delete idea"
                        onClick={() =>
                          update((o) => ({
                            ...o,
                            ideas: o.ideas.filter((i) => i.id !== idea.id),
                          }))
                        }
                      >
                        <Trash2 size={14} />
                      </IconButton>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- One-pager ---------- */

export function OnePager({ offer, prices }: { offer: Offer; prices: boolean }) {
  const name = offer.naming.chosen.trim() || offer.name;
  const statement = positioningStatement(offer.positioning, name);
  const total = stackTotal(offer);
  return (
    <article className={styles.onePager} data-print-area="">
      <header>
        <p className={styles.kicker}>Authority Closers</p>
        <h2>{name}</h2>
        {offer.voice.tagline ? (
          <p className={styles.tagline}>{offer.voice.tagline}</p>
        ) : null}
        {statement ? <p>{statement}</p> : null}
      </header>
      {offer.value.dream.text || offer.icp.who ? (
        <dl className={styles.opFacts}>
          {offer.value.dream.text ? (
            <div>
              <dt>The result</dt>
              <dd>{offer.value.dream.text}</dd>
            </div>
          ) : null}
          {offer.icp.who ? (
            <div>
              <dt>Made for</dt>
              <dd>{offer.icp.who}</dd>
            </div>
          ) : null}
          {offer.value.time.text ? (
            <div>
              <dt>How fast</dt>
              <dd>{offer.value.time.text}</dd>
            </div>
          ) : null}
          {offer.value.effort.text ? (
            <div>
              <dt>How easy</dt>
              <dd>{offer.value.effort.text}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {offer.stack.length ? (
        <section>
          <h3>What you get</h3>
          <ul className={styles.opList}>
            {offer.stack.map((item) => (
              <li key={item.featureId}>
                <span>
                  <strong>{itemLabel(item)}</strong>
                  <span>{featureById(item.featureId)?.value}</span>
                </span>
                {prices && item.worth ? <em>{rupees(item.worth)}</em> : null}
              </li>
            ))}
            {offer.bonuses.map((bonus) => (
              <li key={bonus.id} data-bonus="">
                <span>
                  <strong>Bonus: {bonus.name || "Untitled bonus"}</strong>
                  {bonus.solves ? <span>{bonus.solves}</span> : null}
                </span>
                {prices && bonus.worth ? <em>{rupees(bonus.worth)}</em> : null}
              </li>
            ))}
          </ul>
          {prices && total ? (
            <p className={styles.opTotal}>
              Total value <strong>{rupees(total)}</strong>
            </p>
          ) : null}
        </section>
      ) : null}
      {offer.guarantee.kind !== "none" || offer.guarantee.text ? (
        <section className={styles.opGuarantee}>
          <h3>Our guarantee</h3>
          <p>
            {offer.guarantee.text || GUARANTEES[offer.guarantee.kind].label}
          </p>
        </section>
      ) : null}
      {prices && offer.tiers.length ? (
        <section>
          <h3>Plans</h3>
          <div className={styles.opTiers}>
            {offer.tiers.map((tier) => (
              <div
                key={tier.id}
                data-highlight={tier.highlight ? "" : undefined}
              >
                <strong>{tier.name || "Plan"}</strong>
                <span className={styles.opPrice}>
                  {tier.monthly
                    ? `${rupees(tier.monthly)}/mo`
                    : tier.yearly
                      ? `${rupees(tier.yearly)}/yr`
                      : "On request"}
                </span>
                {[
                  tier.seats && `${tier.seats} seats`,
                  tier.minutes && `${tier.minutes} minutes`,
                ]
                  .filter(Boolean)
                  .map((line) => (
                    <span key={String(line)}>{line}</span>
                  ))}
                {tier.note ? <span>{tier.note}</span> : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}
      {offer.scarcity || offer.urgency ? (
        <footer className={styles.opFooter}>
          {offer.scarcity ? (
            <p>
              <strong>Limited:</strong> {offer.scarcity}
            </p>
          ) : null}
          {offer.urgency ? (
            <p>
              <strong>Why now:</strong> {offer.urgency}
            </p>
          ) : null}
        </footer>
      ) : null}
    </article>
  );
}

function download(name: string, type: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "offer";

function OnePagerTab({ offer }: { offer: Offer }) {
  const [prices, setPrices] = useState(true);
  const [copied, setCopied] = useState(false);
  const markdown = onePagerMarkdown(offer, { prices });
  return (
    <div className={styles.stackCards}>
      <div className={styles.opTools}>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={prices}
            onChange={(event) => setPrices(event.target.checked)}
          />
          Show prices and worth
        </label>
        <button
          type="button"
          className={styles.add}
          onClick={() => window.print()}
        >
          <Printer size={14} aria-hidden="true" /> Print or save PDF
        </button>
        <button
          type="button"
          className={styles.add}
          onClick={() => {
            void navigator.clipboard?.writeText(markdown).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
        >
          <Copy size={14} aria-hidden="true" />{" "}
          {copied ? "Copied" : "Copy Markdown"}
        </button>
        <button
          type="button"
          className={styles.add}
          onClick={() =>
            download(
              `${slug(offer.naming.chosen || offer.name)}.md`,
              "text/markdown",
              markdown,
            )
          }
        >
          <Download size={14} aria-hidden="true" /> Markdown file
        </button>
      </div>
      <OnePager offer={offer} prices={prices} />
    </div>
  );
}

/* ---------- Studio ---------- */

function Summary({ offer }: { offer: Offer }) {
  const prices = offer.tiers.map((t) => t.monthly).filter(Boolean);
  return (
    <aside className={styles.summary} aria-label="Offer summary">
      <ValueGauge offer={offer} />
      <dl>
        <div>
          <dt>Features</dt>
          <dd>{offer.stack.length}</dd>
        </div>
        <div>
          <dt>Bonuses</dt>
          <dd>{offer.bonuses.length}</dd>
        </div>
        <div>
          <dt>Stack worth</dt>
          <dd>{rupees(stackTotal(offer))}</dd>
        </div>
        <div>
          <dt>From</dt>
          <dd>{prices.length ? `${rupees(Math.min(...prices))}/mo` : "—"}</dd>
        </div>
        <div>
          <dt>Guarantee</dt>
          <dd>{GUARANTEES[offer.guarantee.kind].label}</dd>
        </div>
        <div>
          <dt>Ideas</dt>
          <dd>{offer.ideas.length}</dd>
        </div>
      </dl>
      <p className={styles.products}>
        {[
          ...new Set(
            offer.stack
              .map((s) => featureById(s.featureId)?.product)
              .filter(Boolean),
          ),
        ]
          .map((p) => productName(p as string))
          .join(" · ")}
      </p>
    </aside>
  );
}

function Start({
  onStart,
  onCancel,
}: {
  onStart: (templateId: string) => void;
  onCancel?: () => void;
}) {
  return (
    <div className={styles.start}>
      <span className={styles.stackHead}>
        <h2>Start an offer</h2>
        {onCancel ? (
          <button type="button" className={styles.add} onClick={onCancel}>
            Back to the offer
          </button>
        ) : null}
      </span>
      <p>Pick a starting bundle; everything else is yours to write.</p>
      <ul className={styles.templates}>
        {TEMPLATES.map((template) => (
          <li key={template.id}>
            <button type="button" onClick={() => onStart(template.id)}>
              <strong>{template.name}</strong>
              <span>{template.line}</span>
              <small>
                {template.features.length
                  ? `${template.features.length} features`
                  : "Empty"}
              </small>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function OfferStudio({
  storageKey = STUDIO_KEY,
}: {
  storageKey?: string;
}) {
  const { studio, save } = useStudio(storageKey);
  const [tab, setTab] = useState<Tab>("bundle");
  const [message, setMessage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const offer =
    studio.offers.find((o) => o.id === studio.activeId) ??
    studio.offers[0] ??
    null;

  const commit = (next: Studio) => {
    if (!save(next))
      setMessage("This browser wouldn't save. Export a copy now.");
  };
  const start = (templateId: string) => {
    const created = fromTemplate(templateId);
    commit({
      ...studio,
      offers: [...studio.offers, created],
      activeId: created.id,
    });
    setTab("bundle");
  };
  const update: Update = (change) => {
    if (!offer) return;
    save((current) => {
      const live = current.offers.find((o) => o.id === offer.id) ?? offer;
      return withOffer(current, change(live));
    });
  };

  const importFile = async (file: File) => {
    try {
      const incoming = normalizeStudio(JSON.parse(await file.text()));
      commit(mergeStudios(studio, incoming));
      setMessage(
        `Imported ${incoming.offers.length} offer${incoming.offers.length === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      setMessage(
        error instanceof Error && error.message.includes("offers")
          ? error.message
          : "That file isn't an Offer Studio export.",
      );
    }
  };

  return (
    <div className={styles.studio}>
      <div className={styles.bar}>
        {studio.offers.length ? (
          <select
            className={styles.switcher}
            value={offer?.id ?? ""}
            aria-label="Offer"
            onChange={(event) =>
              commit({ ...studio, activeId: event.target.value })
            }
          >
            {studio.offers.map((o) => (
              <option key={o.id} value={o.id}>
                {o.naming.chosen || o.name}
              </option>
            ))}
          </select>
        ) : null}
        {offer ? (
          <input
            className={styles.offerName}
            value={offer.name}
            aria-label="Working name"
            onChange={(event) =>
              update((o) => ({ ...o, name: event.target.value }))
            }
          />
        ) : null}
        <span className={styles.barTools}>
          {offer ? (
            <>
              <button
                type="button"
                className={styles.add}
                onClick={() => {
                  const copy = {
                    ...offer,
                    id: newId("offer"),
                    name: `${offer.name} (copy)`,
                  };
                  commit({
                    ...studio,
                    offers: [...studio.offers, copy],
                    activeId: copy.id,
                  });
                }}
              >
                <Copy size={14} aria-hidden="true" /> Duplicate
              </button>
              <button
                type="button"
                className={styles.add}
                onClick={() => {
                  if (
                    !window.confirm(`Delete "${offer.name}" from this browser?`)
                  )
                    return;
                  const offers = studio.offers.filter((o) => o.id !== offer.id);
                  commit({
                    ...studio,
                    offers,
                    activeId: offers[0]?.id ?? null,
                  });
                }}
              >
                <Trash2 size={14} aria-hidden="true" /> Delete
              </button>
            </>
          ) : null}
          <button
            type="button"
            className={styles.add}
            onClick={() =>
              download(
                `offer-studio-${new Date().toISOString().slice(0, 10)}.json`,
                "application/json",
                JSON.stringify(studio, null, 2),
              )
            }
            disabled={!studio.offers.length}
          >
            <Download size={14} aria-hidden="true" /> Export
          </button>
          <button
            type="button"
            className={styles.add}
            onClick={() => fileRef.current?.click()}
          >
            <Upload size={14} aria-hidden="true" /> Import
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importFile(file);
              event.target.value = "";
            }}
          />
          {offer ? (
            <button
              type="button"
              className={styles.primary}
              onClick={() => setCreating(true)}
            >
              <Plus size={14} aria-hidden="true" /> New offer
            </button>
          ) : null}
        </span>
      </div>
      {message ? (
        <p className={styles.message} role="status">
          {message}
          <button
            type="button"
            onClick={() => setMessage(null)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </p>
      ) : null}

      {!offer || creating ? (
        <Start
          onStart={(id) => {
            start(id);
            setCreating(false);
          }}
          onCancel={offer ? () => setCreating(false) : undefined}
        />
      ) : (
        <>
          <nav className={styles.tabs} aria-label="Offer sections">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-current={tab === key ? "page" : undefined}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className={styles.layout}>
            <div className={styles.main}>
              {tab === "bundle" ? (
                <BundleTab offer={offer} update={update} />
              ) : null}
              {tab === "value" ? (
                <ValueTab offer={offer} update={update} />
              ) : null}
              {tab === "enhance" ? (
                <EnhanceTab offer={offer} update={update} />
              ) : null}
              {tab === "position" ? (
                <PositionTab offer={offer} update={update} />
              ) : null}
              {tab === "pricing" ? (
                <PricingTab offer={offer} update={update} />
              ) : null}
              {tab === "ideas" ? (
                <IdeasTab offer={offer} update={update} />
              ) : null}
              {tab === "onepager" ? <OnePagerTab offer={offer} /> : null}
            </div>
            {tab !== "onepager" ? <Summary offer={offer} /> : null}
          </div>
        </>
      )}
      <p className={styles.saved}>
        Saved in this browser as you type. Export a copy to move it or keep it
        safe.
      </p>
    </div>
  );
}
