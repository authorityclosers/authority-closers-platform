"use client";

/**
 * Share out leads (owner program, 25 Oct 2026, section 2, on Lead OS's
 * distribute): the leads with no owner, or chosen ones, given out by a rule
 * the owner picks: the same number each, fewest open first, or each source or
 * city to the sellers picked for it. The plan shows before anything moves,
 * seller by seller, with what stays and why; one tap gives them out.
 */

import { Check, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { Sheet } from "../ui/sheet";
import { Avatar } from "../ui/kit";
import { commandId, readTeam, type RepView } from "./leads-client";
import {
  applyShare,
  leftWords,
  previewShare,
  type Distribution,
  type ShareCommand,
  type ShareRule,
} from "./team-engine-client";
import styles from "./assign-sheet.module.css";

const RULES: { key: ShareRule; title: string; text: string }[] = [
  { key: "even", title: "Even", text: "The same number to each seller." },
  {
    key: "balanced",
    title: "Balanced",
    text: "Fewest open leads first, up to each seller's limit.",
  },
  {
    key: "by_source",
    title: "By source",
    text: "Each source to the sellers you pick for it.",
  },
  {
    key: "by_city",
    title: "By city",
    text: "Each city to the sellers you pick for it.",
  },
];

const PREVIEW_DELAY_MS = 300;

export type ShareTarget =
  | { kind: "unassigned"; count: number }
  | { kind: "chosen"; leadIds: string[] };

export function AssignSheet({
  open,
  target,
  reps,
  onClose,
  onDone,
}: {
  open: boolean;
  target: ShareTarget;
  /** The team's sellers (GET /team). */
  reps: readonly RepView[];
  onClose: () => void;
  onDone: (result: Distribution) => void;
}) {
  // One id for every preview and the apply: a retry returns the first result.
  const [id, setId] = useState(commandId);
  const [rule, setRule] = useState<ShareRule>("even");
  const [chosen, setChosen] = useState<string[]>(() =>
    reps.filter((rep) => rep.available).map((rep) => rep.person_id),
  );
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [spreadAll, setSpreadAll] = useState(false);
  const [plan, setPlan] = useState<Distribution | null>(null);
  const [planFor, setPlanFor] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const byGroup = rule === "by_source" || rule === "by_city";
  const command: ShareCommand = useMemo(
    () => ({
      command_id: id,
      ...(target.kind === "unassigned"
        ? { unassigned: true }
        : { lead_ids: target.leadIds, spread_all: spreadAll }),
      rule,
      ...(byGroup ? { groups } : { sellers: chosen }),
      preview: true,
    }),
    [id, target, rule, byGroup, groups, chosen, spreadAll],
  );
  const key = JSON.stringify(command);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const asked = JSON.parse(key) as ShareCommand;
    const timer = window.setTimeout(() => {
      previewShare(asked, controller.signal)
        .then((next) => {
          setPlan(next);
          setPlanFor(key);
          setFailed(false);
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true);
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, key]);

  const current = plan !== null && planFor === key;
  const toggle = (list: string[], personId: string) =>
    list.includes(personId)
      ? list.filter((item) => item !== personId)
      : [...list, personId];
  const groupNames = Object.entries(
    (rule === "by_city" ? plan?.cities : plan?.sources) ?? {},
  ).sort((a, b) => b[1] - a[1]);

  const give = async () => {
    if (!current || !plan?.moved || busy) return;
    setBusy(true);
    try {
      const done = await applyShare(command);
      notify({
        id: "share-out",
        tone: "success",
        title:
          done.moved === 1
            ? "1 lead given out"
            : `${done.moved} leads given out`,
        message: done.words,
        timeout: 6_000,
      });
      setId(commandId());
      onDone(done);
    } catch {
      notify({
        id: "share-out",
        tone: "error",
        title: "The leads weren't given out",
        message: "Check your connection and try again.",
      });
    }
    setBusy(false);
  };

  const what =
    target.kind === "unassigned"
      ? `${target.count.toLocaleString("en-IN")} ${target.count === 1 ? "lead" : "leads"} with no owner`
      : `${target.leadIds.length} chosen ${target.leadIds.length === 1 ? "lead" : "leads"}`;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Share out leads"
      description={what}
      footer={
        <button
          type="button"
          className={styles.give}
          disabled={!current || !plan?.moved || busy}
          onClick={() => void give()}
        >
          {busy ? (
            <LoaderCircle
              className={styles.spin}
              size={18}
              aria-hidden="true"
            />
          ) : null}
          {current && plan
            ? plan.moved
              ? `Give out ${plan.moved} ${plan.moved === 1 ? "lead" : "leads"}`
              : "Nothing to give out"
            : "Working out the plan…"}
        </button>
      }
    >
      <div className={styles.body}>
        <fieldset className={styles.rules}>
          <legend>How</legend>
          {RULES.map((item) => (
            <label key={item.key} className={styles.rule}>
              <input
                type="radio"
                name="share-rule"
                checked={rule === item.key}
                onChange={() => setRule(item.key)}
              />
              <span>
                <strong>{item.title}</strong>
                <small>{item.text}</small>
              </span>
            </label>
          ))}
        </fieldset>

        {byGroup ? (
          <section className={styles.section} aria-labelledby="share-groups">
            <h3 id="share-groups">
              {rule === "by_city" ? "Each city to" : "Each source to"}
            </h3>
            {groupNames.length ? (
              <ul className={styles.groups}>
                {groupNames.map(([name, count]) => (
                  <li key={name}>
                    <span className={styles.groupName}>
                      {name}
                      <small>{count}</small>
                    </span>
                    <span className={styles.chips}>
                      {reps.map((rep) => {
                        const on = (groups[name] ?? []).includes(rep.person_id);
                        return (
                          <button
                            key={rep.person_id}
                            type="button"
                            className={styles.chip}
                            aria-pressed={on}
                            onClick={() =>
                              setGroups((now) => ({
                                ...now,
                                [name]: toggle(now[name] ?? [], rep.person_id),
                              }))
                            }
                          >
                            {on ? <Check size={14} aria-hidden="true" /> : null}
                            {displayName(rep.name).split(" ")[0]}
                          </button>
                        );
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.quiet}>
                {current
                  ? `These leads have no ${rule === "by_city" ? "city" : "source"} to go by.`
                  : "Reading where these leads came from…"}
              </p>
            )}
          </section>
        ) : (
          <section className={styles.section} aria-labelledby="share-sellers">
            <h3 id="share-sellers">To</h3>
            <ul className={styles.sellers}>
              {reps.map((rep) => (
                <li key={rep.person_id}>
                  <label className={styles.seller}>
                    <input
                      type="checkbox"
                      checked={chosen.includes(rep.person_id)}
                      onChange={() =>
                        setChosen((now) => toggle(now, rep.person_id))
                      }
                    />
                    <Avatar name={rep.name} size={32} />
                    <span>
                      <strong>{displayName(rep.name)}</strong>
                      <small>
                        {rep.available
                          ? `${rep.open_leads} open · limit ${rep.max_open}`
                          : "Not taking leads"}
                      </small>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            {target.kind === "chosen" ? (
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={spreadAll}
                  onChange={(event) => setSpreadAll(event.target.checked)}
                />
                Also move leads a chosen seller already holds
              </label>
            ) : null}
          </section>
        )}

        <section
          className={styles.plan}
          aria-labelledby="share-plan"
          aria-busy={!current}
        >
          <h3 id="share-plan">The plan</h3>
          {failed ? (
            <p className={styles.quiet} role="status">
              The plan didn&apos;t load. Change a choice to try again.
            </p>
          ) : !current || !plan ? (
            <p className={styles.quiet}>Working out who gets what…</p>
          ) : (
            <>
              {plan.given.length ? (
                <ul className={styles.given}>
                  {plan.given.map((row) => (
                    <li key={row.person_id}>
                      <span>{displayName(row.name)}</span>
                      <strong>{`+${row.leads}`}</strong>
                      <small>{`${row.open_after} open of ${row.max_open}`}</small>
                    </li>
                  ))}
                </ul>
              ) : null}
              {leftWords(plan.left).map((line) => (
                <p key={line} className={styles.left}>
                  {line}
                </p>
              ))}
              {plan.more ? (
                <p className={styles.left}>
                  More leads wait than one share-out takes; share out again
                  after this.
                </p>
              ) : null}
            </>
          )}
        </section>
      </div>
    </Sheet>
  );
}

/**
 * Share out from anywhere (Home's "No leads are yours yet", the Leads menu):
 * reads the team's sellers as it opens, then shows the sheet.
 */
export function ShareOut({
  open,
  target,
  onClose,
  onDone,
}: {
  open: boolean;
  target: ShareTarget;
  onClose: () => void;
  onDone: (result: Distribution) => void;
}) {
  const [reps, setReps] = useState<readonly RepView[] | null>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    if (!open || reps) return;
    const controller = new AbortController();
    readTeam(controller.signal)
      .then((team) => setReps(team.reps))
      .catch(() => {
        if (controller.signal.aborted) return;
        notify({
          id: "share-out",
          tone: "error",
          title: "The team didn't load",
          message: "Check your connection and try again.",
        });
        close.current();
      });
    return () => controller.abort();
  }, [open, reps]);
  if (!reps) return null;
  return (
    <AssignSheet
      open={open}
      target={target}
      reps={reps}
      onClose={onClose}
      onDone={onDone}
    />
  );
}
