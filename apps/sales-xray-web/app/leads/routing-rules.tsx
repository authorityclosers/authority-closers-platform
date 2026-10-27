"use client";

/**
 * Settings → Lead rules → "Who gets which leads" (owner #39 and #42, 27 Oct
 * 2026: rules "much smarter… toggles, cards"; Lead OS's routing rules). Each
 * rule is one card that reads as a sentence: when a lead is like this, give
 * it to these people (in turn). Rules run top to bottom; the first that fits
 * and has someone free gives the lead out; leads no rule fits are shared
 * fairly. Edits wait for Save. "Try a lead" asks the server who a lead like
 * this would go to now, and why.
 */

import {
  ArrowDown,
  ArrowUp,
  Pencil,
  Plus,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { useEffect, useId, useState } from "react";

import { PersonAvatar } from "../people/person-avatar";
import { Button, Field, Segmented } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import { SaveBar } from "./app-card";
import {
  conditionReady,
  conditionWords,
  readRouting,
  ruleReady,
  RoutingError,
  saveRouting,
  tryRouting,
  type Condition,
  type ConditionField,
  type Routing,
  type RoutingRule,
  type TryResult,
} from "./routing-client";
import styles from "./routing-rules.module.css";

const FIELDS: { key: ConditionField; label: string }[] = [
  { key: "source", label: "Source" },
  { key: "city", label: "City" },
  { key: "language", label: "Language" },
  { key: "interest", label: "Interest" },
  { key: "answer", label: "Form answer" },
  { key: "value", label: "Value" },
];

/** A fresh condition of a field, empty until filled. */
function blank(field: ConditionField, routing: Routing): Condition {
  if (field === "value")
    return { field, op: "at_least", low: null, high: null };
  if (field === "answer")
    return { field, key: routing.questions[0]?.key ?? "", values: [] };
  return { field, values: [] };
}

/** "Pune, Mumbai" → ["Pune", "Mumbai"]. */
const split = (text: string) =>
  text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

function names(routing: Routing, ids: string[]): string {
  const named = ids.map(
    (id) =>
      routing.people.find((person) => person.person_id === id)?.name ??
      "Someone",
  );
  return named.length > 2
    ? `${named.slice(0, 2).join(", ")} and ${named.length - 2} more`
    : named.join(" and ");
}

export function RoutingRules() {
  const titleId = useId();
  const [routing, setRouting] = useState<Routing | "hidden" | null>(null);
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [valueAnswer, setValueAnswer] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{
    index: number | null;
    rule: RoutingRule;
  } | null>(null);

  const take = (next: Routing) => {
    setRouting(next);
    setRules(next.rules);
    setValueAnswer(next.value_answer);
    setDirty(false);
  };
  useEffect(() => {
    const controller = new AbortController();
    readRouting(controller.signal).then(take, () => {
      if (!controller.signal.aborted) setRouting("hidden");
    });
    return () => controller.abort();
  }, []);

  // Not offered here, or not for this person: the rest of Lead rules stands.
  if (routing === "hidden") return null;
  if (!routing)
    return (
      <section
        className={styles.section}
        aria-busy="true"
        aria-label="Who gets which leads"
      />
    );

  const edit = (next: RoutingRule[]) => {
    setRules(next);
    setDirty(true);
    setSaved(false);
    setError(null);
  };
  const move = (index: number, by: -1 | 1) => {
    const next = [...rules];
    const [rule] = next.splice(index, 1);
    next.splice(index + by, 0, rule);
    edit(next);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      take(await saveRouting(routing.revision, valueAnswer, rules));
      setSaved(true);
    } catch (reason) {
      setError(
        reason instanceof RoutingError
          ? reason.message
          : "The rules weren't saved. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <header className={styles.head}>
        <h2 id={titleId}>Who gets which leads</h2>
        <p>
          The first rule that fits a new lead, with someone free, gives it out.
          Leads no rule fits are shared fairly.
        </p>
      </header>

      {rules.length ? (
        <ol className={styles.rules}>
          {rules.map((rule, index) => (
            <li
              key={rule.id ?? `new-${index}`}
              className={styles.rule}
              data-off={rule.enabled ? undefined : ""}
            >
              <div className={styles.ruleHead}>
                <span className={styles.number} aria-hidden="true">
                  {index + 1}
                </span>
                <strong>{rule.name}</strong>
                {routing.can_edit ? (
                  <input
                    type="checkbox"
                    role="switch"
                    className={styles.switch}
                    aria-label={`${rule.name}: ${rule.enabled ? "on" : "off"}`}
                    checked={rule.enabled}
                    onChange={(event) =>
                      edit(
                        rules.map((item, at) =>
                          at === index
                            ? { ...item, enabled: event.target.checked }
                            : item,
                        ),
                      )
                    }
                  />
                ) : null}
              </div>
              <p className={styles.line}>
                <span className={styles.lead}>When</span>
                {rule.when.map((condition, at) => (
                  <span key={at} className={styles.chip}>
                    {conditionWords(condition, routing)}
                  </span>
                ))}
              </p>
              <p className={styles.line}>
                <span className={styles.lead}>Give to</span>
                <span className={styles.faces} aria-hidden="true">
                  {rule.give_to.slice(0, 4).map((id) => (
                    <PersonAvatar
                      key={id}
                      personId={id}
                      name={
                        routing.people.find((person) => person.person_id === id)
                          ?.name ?? "?"
                      }
                      size={24}
                    />
                  ))}
                </span>
                <span>
                  {names(routing, rule.give_to)}
                  {rule.give_to.length > 1 ? ", in turn" : ""}
                </span>
              </p>
              {routing.can_edit ? (
                <div className={styles.ruleActions}>
                  <Button
                    variant="ghost"
                    onClick={() => setEditing({ index, rule })}
                  >
                    <Pencil size={16} aria-hidden="true" />
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    aria-label={`Move ${rule.name} up`}
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp size={16} aria-hidden="true" />
                  </Button>
                  <Button
                    variant="ghost"
                    aria-label={`Move ${rule.name} down`}
                    disabled={index === rules.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown size={16} aria-hidden="true" />
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.empty}>
          No rules yet: new leads go to whoever is free with the fewest open
          leads. Add a rule to send some leads to the right people first.
        </p>
      )}

      {routing.can_edit && rules.length < 30 ? (
        <Button
          onClick={() =>
            setEditing({
              index: null,
              rule: {
                id: null,
                name: "",
                enabled: true,
                when: [blank("source", routing)],
                give_to: [],
              },
            })
          }
        >
          <Plus size={16} aria-hidden="true" />
          Add a rule
        </Button>
      ) : null}

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <SaveBar
        dirty={dirty}
        busy={busy}
        saved={saved}
        savedText="Rules saved. New leads follow them now."
        onSave={() => void save()}
        onDiscard={() => take(routing)}
      />

      <TryLead routing={routing} draft={dirty} />

      <RuleSheet
        key={editing ? `${editing.index ?? "new"}-${rules.length}` : "closed"}
        open={editing !== null}
        routing={routing}
        rule={editing?.rule ?? null}
        isNew={editing?.index === null}
        valueAnswer={valueAnswer}
        onValueAnswer={(key) => {
          setValueAnswer(key);
          setDirty(true);
          setSaved(false);
        }}
        onClose={() => setEditing(null)}
        onDone={(rule) => {
          if (!editing) return;
          edit(
            editing.index === null
              ? [...rules, rule]
              : rules.map((item, at) => (at === editing.index ? rule : item)),
          );
          setEditing(null);
        }}
        onDelete={() => {
          if (editing?.index === null || !editing) return;
          edit(rules.filter((_, at) => at !== editing.index));
          setEditing(null);
        }}
      />
    </section>
  );
}

function RuleSheet({
  open,
  routing,
  rule,
  isNew,
  valueAnswer,
  onValueAnswer,
  onClose,
  onDone,
  onDelete,
}: {
  open: boolean;
  routing: Routing;
  rule: RoutingRule | null;
  isNew: boolean;
  valueAnswer: string | null;
  onValueAnswer: (key: string | null) => void;
  onClose: () => void;
  onDone: (rule: RoutingRule) => void;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState<RoutingRule>(
    () => rule ?? { id: null, name: "", enabled: true, when: [], give_to: [] },
  );
  const set = (patch: Partial<RoutingRule>) =>
    setDraft((current) => ({ ...current, ...patch }));
  const setCondition = (at: number, next: Condition) =>
    set({
      when: draft.when.map((item, index) => (index === at ? next : item)),
    });
  const needsValue =
    draft.when.some((item) => item.field === "value") && !valueAnswer;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={isNew ? "New rule" : "Edit rule"}
      footer={
        <>
          {isNew ? null : (
            <Button variant="ghost" onClick={onDelete}>
              <Trash2 size={16} aria-hidden="true" />
              Delete rule
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!ruleReady(draft) || needsValue}
            onClick={() => onDone({ ...draft, name: draft.name.trim() })}
          >
            Done
          </Button>
        </>
      }
    >
      <div className={styles.sheet}>
        <Field label="Name">
          <input
            value={draft.name}
            maxLength={60}
            placeholder="Big budgets to Priya"
            onChange={(event) => set({ name: event.target.value })}
          />
        </Field>

        <div className={styles.block} role="group" aria-label="When">
          <h3>When a new lead…</h3>
          {draft.when.map((condition, at) => (
            <div key={at} className={styles.condition}>
              <div className={styles.conditionHead}>
                <select
                  aria-label="What to check"
                  value={condition.field}
                  onChange={(event) =>
                    setCondition(
                      at,
                      blank(event.target.value as ConditionField, routing),
                    )
                  }
                >
                  {FIELDS.map((field) => (
                    <option key={field.key} value={field.key}>
                      {field.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className={styles.remove}
                  aria-label="Remove this condition"
                  onClick={() =>
                    set({ when: draft.when.filter((_, index) => index !== at) })
                  }
                >
                  <X size={16} aria-hidden="true" />
                </button>
              </div>
              <ConditionEditor
                condition={condition}
                routing={routing}
                valueAnswer={valueAnswer}
                onValueAnswer={onValueAnswer}
                onChange={(next) => setCondition(at, next)}
              />
              {conditionReady(condition) ? (
                <small className={styles.reads}>
                  {conditionWords(condition, routing)}
                </small>
              ) : null}
            </div>
          ))}
          {draft.when.length < 6 ? (
            <Button
              variant="ghost"
              onClick={() =>
                set({ when: [...draft.when, blank("city", routing)] })
              }
            >
              <Plus size={16} aria-hidden="true" />
              And also…
            </Button>
          ) : null}
        </div>

        <div className={styles.block} role="group" aria-label="Give to">
          <h3>…give it to</h3>
          <p className={styles.hint}>
            <Users size={16} aria-hidden="true" />
            Pick more than one and they take turns.
          </p>
          <ul className={styles.people}>
            {routing.people.map((person) => {
              const on = draft.give_to.includes(person.person_id);
              return (
                <li key={person.person_id}>
                  <label
                    className={styles.person}
                    data-on={on ? "" : undefined}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        set({
                          give_to: on
                            ? draft.give_to.filter(
                                (id) => id !== person.person_id,
                              )
                            : [...draft.give_to, person.person_id],
                        })
                      }
                    />
                    <PersonAvatar
                      personId={person.person_id}
                      name={person.name}
                      size={32}
                    />
                    <span>
                      <strong>{person.name}</strong>
                      <small>
                        {person.available ? "" : "Away · "}
                        {person.max_open === null
                          ? `${person.open_leads} open`
                          : `${person.open_leads}/${person.max_open} open`}
                      </small>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </Sheet>
  );
}

function ConditionEditor({
  condition,
  routing,
  valueAnswer,
  onValueAnswer,
  onChange,
}: {
  condition: Condition;
  routing: Routing;
  valueAnswer: string | null;
  onValueAnswer: (key: string | null) => void;
  onChange: (next: Condition) => void;
}) {
  if (condition.field === "source")
    return (
      <div className={styles.options}>
        {Object.entries(routing.sources).map(([key, words]) => {
          const on = condition.values.includes(key);
          return (
            <label
              key={key}
              className={styles.option}
              data-on={on ? "" : undefined}
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() =>
                  onChange({
                    ...condition,
                    values: on
                      ? condition.values.filter((value) => value !== key)
                      : [...condition.values, key],
                  })
                }
              />
              {words}
            </label>
          );
        })}
      </div>
    );
  if (condition.field === "answer") {
    const question = routing.questions.find(
      (item) => item.key === condition.key,
    );
    return (
      <div className={styles.answer}>
        <select
          aria-label="Which question"
          value={condition.key}
          onChange={(event) =>
            onChange({ field: "answer", key: event.target.value, values: [] })
          }
        >
          {routing.questions.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>
        {question?.examples.length ? (
          <div className={styles.options}>
            {question.examples.map((example) => {
              const on = condition.values.includes(example);
              return (
                <label
                  key={example}
                  className={styles.option}
                  data-on={on ? "" : undefined}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() =>
                      onChange({
                        ...condition,
                        values: on
                          ? condition.values.filter(
                              (value) => value !== example,
                            )
                          : [...condition.values, example],
                      })
                    }
                  />
                  {example}
                </label>
              );
            })}
          </div>
        ) : (
          <input
            aria-label="Answers, separated by commas"
            placeholder="Answers, separated by commas"
            defaultValue={condition.values.join(", ")}
            onChange={(event) =>
              onChange({ ...condition, values: split(event.target.value) })
            }
          />
        )}
      </div>
    );
  }
  if (condition.field === "value") {
    // Digits only; an empty box is no amount yet. Shown grouped: "50,00,000".
    const amount = (text: string) => {
      const digits = text.replace(/[^\d]/g, "");
      return digits ? Number(digits) : null;
    };
    const shown = (rupees: number | null) =>
      rupees === null ? "" : rupees.toLocaleString("en-IN");
    const { op, low, high } = condition;
    return (
      <div className={styles.value}>
        <select
          aria-label="The form question with the lead's value"
          value={valueAnswer ?? ""}
          onChange={(event) => onValueAnswer(event.target.value || null)}
        >
          <option value="">Which form answer is the value?</option>
          {routing.questions.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>
        <Segmented
          label="Value"
          value={op}
          items={[
            { key: "at_least", label: "At least" },
            { key: "below", label: "Under" },
            { key: "between", label: "Between" },
          ]}
          // Both amounts are kept, so switching back loses nothing.
          onChange={(next) => onChange({ ...condition, op: next })}
        />
        <div className={styles.amounts}>
          {op !== "below" ? (
            <input
              inputMode="numeric"
              aria-label="From, in rupees"
              placeholder="₹ from"
              value={shown(low)}
              onChange={(event) =>
                onChange({ ...condition, low: amount(event.target.value) })
              }
            />
          ) : null}
          {op !== "at_least" ? (
            <input
              inputMode="numeric"
              aria-label="Up to, in rupees"
              placeholder="₹ up to"
              value={shown(high)}
              onChange={(event) =>
                onChange({ ...condition, high: amount(event.target.value) })
              }
            />
          ) : null}
        </div>
        {op === "between" && low !== null && high !== null && low > high ? (
          <small className={styles.error}>
            The first amount must be the smaller one.
          </small>
        ) : null}
      </div>
    );
  }
  return (
    <input
      key={condition.field}
      aria-label={`${FIELDS.find((field) => field.key === condition.field)?.label}, separated by commas`}
      placeholder={
        condition.field === "city"
          ? "Pune, Mumbai"
          : condition.field === "language"
            ? "Marathi, Hindi"
            : "2 BHK, Villa"
      }
      defaultValue={condition.values.join(", ")}
      onChange={(event) =>
        onChange({ ...condition, values: split(event.target.value) })
      }
    />
  );
}

/** Who a lead like this would go to now (the saved rules), and why. */
function TryLead({ routing, draft }: { routing: Routing; draft: boolean }) {
  const [source, setSource] = useState(Object.keys(routing.sources)[0] ?? "");
  const [city, setCity] = useState("");
  const [language, setLanguage] = useState("");
  const [value, setValue] = useState("");
  const [result, setResult] = useState<TryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await tryRouting({
          source: source || undefined,
          city: city.trim() || undefined,
          language: language.trim() || undefined,
          value: value.trim() || undefined,
        }),
      );
    } catch (reason) {
      setResult(null);
      setError(
        reason instanceof RoutingError
          ? reason.message
          : "That didn't work. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.try} role="group" aria-label="Try a lead">
      <h3>Try a lead</h3>
      <p className={styles.hint}>
        {draft
          ? "Uses the saved rules: save yours to try them."
          : "See who a lead like this would go to now."}
      </p>
      <div className={styles.tryFields}>
        <select
          aria-label="Source"
          className={styles.trySource}
          value={source}
          onChange={(event) => setSource(event.target.value)}
        >
          {Object.entries(routing.sources).map(([key, words]) => (
            <option key={key} value={key}>
              {words}
            </option>
          ))}
        </select>
        <input
          aria-label="City"
          placeholder="City"
          value={city}
          onChange={(event) => setCity(event.target.value)}
        />
        <input
          aria-label="Language"
          placeholder="Language"
          value={language}
          onChange={(event) => setLanguage(event.target.value)}
        />
        <input
          aria-label="Value"
          placeholder="Value, like 3 lakh"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </div>
      <Button onClick={() => void run()} disabled={busy}>
        {busy ? "Checking…" : "Who gets it?"}
      </Button>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <div className={styles.result} role="status">
          {result.person_id && result.name ? (
            <PersonAvatar
              personId={result.person_id}
              name={result.name}
              size={32}
            />
          ) : null}
          <span>
            <strong>
              {result.name
                ? `${result.name}${result.rule ? ` · rule ${result.rule}${result.rule_name ? `, ${result.rule_name}` : ""}` : " · shared fairly"}`
                : "Nobody free right now"}
            </strong>
            <small>{result.why}</small>
            {result.passed_over.map((line) => (
              <small key={line}>{line}</small>
            ))}
          </span>
        </div>
      ) : null}
    </div>
  );
}
