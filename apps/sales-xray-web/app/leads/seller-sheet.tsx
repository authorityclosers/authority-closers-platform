"use client";

/**
 * A seller's lead settings (owner bug #49, 27 Oct 2026: "choosing areas is
 * hard… the tick boxes are very ugly… this itself is a huge ux ui design and
 * not a joke"). Progressive: first whether they take new leads and how many
 * at once; then who they fit, as one row of chips that opens an editor of
 * languages (each in its own script), areas and products, the choices on
 * this organisation's leads first, with how many of last month's leads the
 * profile would take; then the AI on their calls as one choice.
 */

import {
  Car,
  Check,
  ChevronRight,
  GraduationCap,
  Home,
  Landmark,
  Minus,
  Plane,
  Plus,
  Search,
  Stethoscope,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  CallAiError,
  LEVEL_NAMES,
  levelFor,
  saveCallAiPerson,
  type CallAiLevel,
  type CallAiSettings,
} from "../call-ai/call-ai-client";
import { notify } from "../notice-center";
import { PersonAvatar } from "../people/person-avatar";
import { Button, Segmented } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import { SwitchRow } from "./app-card";
import { LeadsError, saveRep, type RepView, type Team } from "./leads-client";
import {
  LIMIT_RULE,
  limitDraft,
  readLimit,
  type LimitDraft,
} from "./limit-field";
import {
  LANGUAGES,
  languageKey,
  placeKey,
  readChoices,
  readFit,
  type Choice,
  type Choices,
  type Fit,
} from "./team-choices-client";
import styles from "./seller-sheet.module.css";

type Part = "languages" | "areas" | "products";

const PRESETS: (number | null)[] = [10, 25, 50, null];

// The industry's own icon on its products, where it has one.
const INDUSTRY_ICONS: Record<string, LucideIcon> = {
  real_estate: Home,
  education: GraduationCap,
  healthcare: Stethoscope,
  clinic: Stethoscope,
  automobile: Car,
  finance: Landmark,
  insurance: Landmark,
  travel: Plane,
  solar: Sun,
};

const keyOf = (part: Part, value: string) =>
  part === "languages" ? languageKey(value) : placeKey(value);

/** A language's words on a chip: its own script, then its name. */
function languageWords(value: string): { native: string | null; name: string } {
  const known = LANGUAGES.find((item) => item.code === languageKey(value));
  return known && known.native !== known.name
    ? { native: known.native, name: known.name }
    : { native: null, name: known?.name ?? value };
}

/**
 * Chips on one row (the orchestrator, 27 Oct 2026: a second line is the
 * "stacked" look the owner hates): as many as fit, then "+k". Every chip is
 * measured in a hidden copy of the row.
 */
function ChipRow({ chips }: { chips: { key: string; words: string }[] }) {
  const row = useRef<HTMLSpanElement>(null);
  const ruler = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(chips.length);
  const signature = chips.map((chip) => chip.key).join("|");
  useLayoutEffect(() => {
    const box = row.current;
    const measure = ruler.current;
    if (!box || !measure) return;
    const fit = () => {
      const widths = [...measure.children].map(
        (child) => (child as HTMLElement).offsetWidth,
      );
      const room = box.clientWidth;
      const more = 44; // the "+k" chip
      let used = 0;
      let count = 0;
      for (const [index, width] of widths.entries()) {
        const last = index === widths.length - 1;
        if (used + width + (last ? 0 : more) > room) break;
        used += width + 6;
        count += 1;
      }
      setShown(count);
    };
    const resize =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    resize?.observe(box);
    return () => resize?.disconnect();
  }, [signature]);
  if (!chips.length)
    return <span className={styles.anyone}>Any lead: no limits yet</span>;
  const hidden = chips.length - Math.min(shown, chips.length);
  return (
    <span className={styles.chipRow} ref={row}>
      <span className={styles.ruler} ref={ruler} aria-hidden="true">
        {chips.map((chip) => (
          <span key={chip.key} className={styles.chip}>
            {chip.words}
          </span>
        ))}
      </span>
      {chips.slice(0, chips.length - hidden).map((chip) => (
        <span key={chip.key} className={styles.chip}>
          {chip.words}
        </span>
      ))}
      {hidden ? <span className={styles.chip}>+{hidden}</span> : null}
    </span>
  );
}

/** How many of last month's leads the profile takes; the counts per part only in the editor. */
function FitLine({ fit, detail }: { fit: Fit; detail?: boolean }) {
  return (
    <div className={styles.fit} role="status">
      <span>
        Fits <strong>{fit.fits}</strong> of last month&apos;s {fit.leads} leads
        ({fit.percent}%)
      </span>
      <span className={styles.bar} aria-hidden="true">
        <i style={{ width: `${Math.min(100, fit.percent)}%` }} />
      </span>
      {detail ? (
        <small>
          By language {fit.by.language} · by area {fit.by.area} · by product{" "}
          {fit.by.product}
        </small>
      ) : null}
    </div>
  );
}

function Editor({
  name,
  part,
  onPart,
  chosen,
  onChosen,
  choices,
  fit,
}: {
  name: string;
  part: Part;
  onPart: (part: Part) => void;
  chosen: Record<Part, string[]>;
  onChosen: (part: Part, values: string[]) => void;
  choices: Choices | null;
  fit: Fit | null;
}) {
  const [query, setQuery] = useState("");
  const words = query.trim().toLocaleLowerCase();
  const picked = chosen[part];
  const pickedKeys = new Set(picked.map((value) => keyOf(part, value)));
  const matches = (value: string) =>
    !words ||
    value.toLocaleLowerCase().includes(words) ||
    (part === "languages" &&
      (languageWords(value).native ?? "").includes(query.trim()));
  const onLeads = (choices?.[part] ?? []).filter(
    (item) => !pickedKeys.has(item.key) && matches(item.value),
  );
  const leadKeys = new Set((choices?.[part] ?? []).map((item) => item.key));
  const others =
    part === "languages"
      ? LANGUAGES.filter(
          (item) =>
            !pickedKeys.has(item.code) &&
            !leadKeys.has(item.code) &&
            (matches(item.name) || item.native.includes(query.trim())),
        )
      : [];
  const known =
    part === "languages"
      ? LANGUAGES.some(
          (item) =>
            item.name.toLocaleLowerCase() === words ||
            item.native === query.trim(),
        )
      : leadKeys.has(placeKey(query));
  const canAdd =
    part !== "languages" &&
    words.length > 0 &&
    !known &&
    !pickedKeys.has(placeKey(query));
  const Icon =
    part === "products" && choices?.industry
      ? INDUSTRY_ICONS[choices.industry.id]
      : undefined;
  const label = (value: string) => {
    if (part !== "languages") return value;
    const { native, name: english } = languageWords(value);
    return native ? (
      <>
        <span className={styles.native}>{native}</span> {english}
      </>
    ) : (
      english
    );
  };
  const add = (value: string) => {
    onChosen(part, [...picked, value]);
    setQuery("");
  };
  const count = (item: Choice) => (
    <em aria-label={`${item.leads} leads`}>{item.leads}</em>
  );
  return (
    <div className={styles.editor}>
      <p className={styles.note}>
        Empty means any. Leads with no{" "}
        {part === "products" ? "product" : part.slice(0, -1)} aren&apos;t
        limited by it.
      </p>
      {fit ? <FitLine fit={fit} detail /> : null}
      <div className={styles.parts}>
        <Segmented
          label={`Who ${name} fits`}
          value={part}
          items={(["languages", "areas", "products"] as Part[]).map((key) => ({
            key,
            label: (
              <>
                {key[0].toUpperCase() + key.slice(1)}
                {chosen[key].length ? <i>{chosen[key].length}</i> : null}
              </>
            ),
          }))}
          onChange={(next) => {
            setQuery("");
            onPart(next);
          }}
        />
      </div>
      <label className={styles.search}>
        <Search size={18} aria-hidden="true" />
        <input
          value={query}
          placeholder={
            part === "languages"
              ? "Search languages"
              : part === "areas"
                ? "Search or add a place"
                : "Search or add a product"
          }
          aria-label={`Search ${part}`}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && canAdd) {
              event.preventDefault();
              add(query.trim());
            }
          }}
        />
      </label>
      {picked.length ? (
        <section className={styles.group} aria-label="Chosen">
          <h4>
            Chosen <small>Tap to remove</small>
          </h4>
          <div className={styles.chips}>
            {picked.map((value) => (
              <button
                key={keyOf(part, value)}
                type="button"
                className={styles.pick}
                aria-pressed="true"
                onClick={() =>
                  onChosen(
                    part,
                    picked.filter((item) => item !== value),
                  )
                }
              >
                {Icon ? <Icon size={15} aria-hidden="true" /> : null}
                {label(value)}
                <Check size={14} aria-hidden="true" className={styles.tick} />
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {onLeads.length ? (
        <section className={styles.group} aria-label="On your leads">
          <h4>
            On your leads <small>most leads first</small>
          </h4>
          <div className={styles.chips}>
            {onLeads.map((item) => (
              <button
                key={item.key}
                type="button"
                className={styles.pick}
                aria-pressed="false"
                onClick={() => add(item.value)}
              >
                {Icon ? <Icon size={15} aria-hidden="true" /> : null}
                {label(item.value)}
                {count(item)}
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {others.length ? (
        <section className={styles.group} aria-label="More languages">
          <h4>More languages</h4>
          <div className={styles.chips}>
            {others.map((item) => (
              <button
                key={item.code}
                type="button"
                className={styles.pick}
                aria-pressed="false"
                onClick={() => add(item.name)}
              >
                {label(item.name)}
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {canAdd ? (
        <button
          type="button"
          className={styles.add}
          onClick={() => add(query.trim())}
        >
          <Plus size={15} aria-hidden="true" />
          Add “{query.trim()}”{part === "areas" ? " as a place" : ""}
        </button>
      ) : null}
    </div>
  );
}

export function SellerSheet({
  rep,
  callAi,
  onClose,
  onSaved,
  onCallAiSaved,
}: {
  rep: RepView | null;
  /** AI on calls (owner, 21 Oct): this seller's level; null when it didn't load. */
  callAi: CallAiSettings | null;
  onClose: () => void;
  onSaved: (team: Team) => void;
  onCallAiSaved: (settings: CallAiSettings) => void;
}) {
  // TeamView gives each opening a new key, so these start from this seller.
  const own = rep && callAi ? levelFor(callAi, rep.person_id) : null;
  const startLevel: CallAiLevel | "" = own?.own ? own.level : "";
  const [aiLevel, setAiLevel] = useState<CallAiLevel | "">(startLevel);
  const [available, setAvailable] = useState(rep?.available ?? true);
  const [cap, setCap] = useState<LimitDraft>(() =>
    limitDraft(rep ? rep.max_open : undefined),
  );
  const [chosen, setChosen] = useState<Record<Part, string[]>>({
    languages: rep?.languages ?? [],
    areas: rep?.areas ?? [],
    products: rep?.interests ?? [],
  });
  const [view, setView] = useState<"main" | Part>("main");
  const [choices, setChoices] = useState<Choices | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const person = rep?.person_id ?? null;
  const name = rep?.name.split(" ")[0] ?? "this seller";

  // The organisation's choices, once for this seller.
  useEffect(() => {
    if (!person) return;
    const controller = new AbortController();
    readChoices(controller.signal).then(setChoices, () => setChoices(null));
    return () => controller.abort();
  }, [person]);

  // How many leads this profile takes, as the chips change (debounced).
  const profile = JSON.stringify(chosen);
  useEffect(() => {
    if (!person || !choices) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const { languages, areas, products } = JSON.parse(profile) as Record<
        Part,
        string[]
      >;
      readFit({ languages, areas, products }, controller.signal).then(
        setFit,
        () => undefined,
      );
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [person, choices, profile]);

  const save = async () => {
    if (!rep) return;
    const max = readLimit(cap);
    if (max === undefined) {
      setError(LIMIT_RULE);
      return;
    }
    setSaving(true);
    setError(null);
    if (callAi?.can_edit && aiLevel !== startLevel) {
      try {
        onCallAiSaved(
          await saveCallAiPerson(
            callAi.revision,
            rep.person_id,
            aiLevel || null,
          ),
        );
      } catch (reason) {
        notify({
          id: `call-ai-${rep.person_id}`,
          tone: "error",
          title: "AI on calls not saved",
          message:
            reason instanceof CallAiError
              ? reason.message
              : "Not saved. Try again.",
        });
        setSaving(false);
        return;
      }
    }
    try {
      onSaved(
        await saveRep(rep, {
          available,
          max_open: max,
          languages: chosen.languages.slice(0, 12),
          areas: chosen.areas,
          interests: chosen.products,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof LeadsError ? reason.message : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  const number = cap.none ? null : Number(cap.value) || 0;
  const step = (by: number) =>
    setCap({
      none: false,
      value: String(Math.min(1000, Math.max(1, (number ?? 50) + by))),
    });
  const summary = [
    ...chosen.languages.map((value) => ({
      key: `l:${languageKey(value)}`,
      words: languageWords(value).native ?? languageWords(value).name,
    })),
    ...chosen.areas.map((value) => ({
      key: `a:${placeKey(value)}`,
      words: value,
    })),
    ...chosen.products.map((value) => ({
      key: `p:${placeKey(value)}`,
      words: value,
    })),
  ];
  const defaultName = callAi ? LEVEL_NAMES[callAi.default] : "";
  const level = aiLevel || callAi?.default;

  return (
    <Sheet
      open={rep !== null}
      title={view === "main" ? (rep?.name ?? "Lead rules") : `Who ${name} fits`}
      lead={
        rep ? (
          <PersonAvatar personId={rep.person_id} name={rep.name} size={44} />
        ) : null
      }
      description={
        view === "main" && rep
          ? `${rep.open_leads} open leads · ${rep.due_now} due now`
          : undefined
      }
      onClose={onClose}
      footer={
        view === "main" ? (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </>
        ) : (
          <Button variant="primary" onClick={() => setView("main")}>
            Done
          </Button>
        )
      }
    >
      {view !== "main" ? (
        <Editor
          name={name}
          part={view}
          onPart={setView}
          chosen={chosen}
          onChosen={(part, values) =>
            setChosen((current) => ({ ...current, [part]: values }))
          }
          choices={choices}
          fit={fit}
        />
      ) : (
        <div className={styles.main}>
          <section className={styles.card} aria-label="New leads">
            <SwitchRow
              label="Takes new leads"
              hint={
                available
                  ? `On: new leads can go to ${name} now`
                  : `Off: no new leads go to ${name}`
              }
              checked={available}
              onChange={setAvailable}
            />
            <div className={styles.capacity}>
              <h3>Most open leads at once</h3>
              <div className={styles.stepper}>
                <button
                  type="button"
                  aria-label="Fewer"
                  disabled={number === null || number <= 1}
                  onClick={() => step(-5)}
                >
                  <Minus size={20} aria-hidden="true" />
                </button>
                <output aria-live="polite">
                  {number === null ? "No limit" : number}
                  <small>{number === null ? "any number" : "open leads"}</small>
                </output>
                <button
                  type="button"
                  aria-label="More"
                  disabled={number !== null && number >= 1000}
                  onClick={() => step(5)}
                >
                  <Plus size={20} aria-hidden="true" />
                </button>
              </div>
              <div
                className={styles.presets}
                role="group"
                aria-label="Quick limits"
              >
                {PRESETS.map((preset) => (
                  <button
                    key={preset ?? "none"}
                    type="button"
                    aria-pressed={preset === number}
                    onClick={() =>
                      setCap(
                        preset === null
                          ? { none: true, value: cap.value }
                          : { none: false, value: String(preset) },
                      )
                    }
                  >
                    {preset ?? "No limit"}
                  </button>
                ))}
              </div>
              {rep?.default_cap ? (
                <small className={styles.note}>
                  The organisation&apos;s default until you change it.
                </small>
              ) : null}
            </div>
          </section>
          <section className={styles.card} aria-label={`Who ${name} fits`}>
            <h3>Who {name} fits</h3>
            <button
              type="button"
              className={styles.fitRow}
              aria-label={`Edit who ${name} fits`}
              onClick={() => setView("languages")}
            >
              <ChipRow chips={summary} />
              <ChevronRight size={18} aria-hidden="true" />
            </button>
            {fit ? <FitLine fit={fit} /> : null}
          </section>
          {callAi?.can_edit ? (
            <section className={styles.ai} aria-label={`AI on ${name}'s calls`}>
              <h3>AI on {name}&apos;s calls</h3>
              <div className={styles.levels}>
                <Segmented
                  label={`AI on ${name}'s calls`}
                  value={aiLevel || "default"}
                  items={[
                    {
                      key: "default",
                      label: (
                        <span className={styles.twoLine}>
                          Default <small>({defaultName})</small>
                        </span>
                      ),
                    },
                    ...callAi.levels.map((item) => ({
                      key: item.id,
                      label: item.name,
                    })),
                  ]}
                  onChange={(next) =>
                    setAiLevel(next === "default" ? "" : (next as CallAiLevel))
                  }
                />
              </div>
              <p className={styles.note}>
                {callAi.levels.find((item) => item.id === level)?.hint}
              </p>
            </section>
          ) : null}
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
        </div>
      )}
    </Sheet>
  );
}
