"use client";

/**
 * Share out leads (owner program, 25 Oct 2026, section 2, on Lead OS's
 * distribute): the leads with no owner, or chosen ones, given out by a rule
 * the owner picks: the same number each, fewest open first, or each source or
 * city to the sellers picked for it. The plan shows before anything moves,
 * seller by seller, with what stays and why; one tap gives them out.
 *
 * Owner bug #55 (28 Oct 2026, "confusion of this feature"): the sheet says
 * what it does in one line, each choice shows what it would do with this
 * team's real numbers, and when nothing can move it says why and what next.
 */

import { Check, LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { settingsPath } from "../settings/settings-sections";
import { leavingOverlay } from "../ui/back-close";
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

const firstName = (rep: RepView) => displayName(rep.name).split(" ")[0];
const leadsWord = (count: number) =>
  `${count} ${count === 1 ? "lead" : "leads"}`;

/**
 * What one choice would do here, from the team's real numbers: "40 leads → 20
 * each for 2 sellers", "Priya has 2 open, Rohan 9: Priya gets leads first",
 * "Facebook leads to Priya, Website to Rohan". With no leads waiting, an
 * example with the team's own sellers. `sellers` are the ones it would use.
 */
export function ruleExample(
  rule: ShareRule,
  leads: number,
  sellers: readonly RepView[],
  plan: Distribution | null,
): string | null {
  const [one, two] = sellers;
  if (!one) return null;
  if (rule === "even") {
    const count = sellers.length;
    const many = leads || count * 3;
    const lead = leads ? leadsWord(many) : `For example, ${many} new leads`;
    if (count === 1) return `${lead} → all to ${firstName(one)}`;
    const each = Math.floor(many / count);
    if (many === 1) return `${lead} → one of your ${count} sellers`;
    if (!each) return `${lead} → 1 each to ${many} of your ${count} sellers`;
    const share = many % count ? `${each} or ${each + 1}` : `${each}`;
    return `${lead} → ${share} each for ${count} sellers`;
  }
  if (rule === "balanced") {
    const byLoad = [...sellers].sort((a, b) => a.open_leads - b.open_leads);
    const light = byLoad[0];
    const heavy = byLoad[byLoad.length - 1];
    if (light === heavy) return null;
    if (light.open_leads === heavy.open_leads)
      return `Everyone has ${light.open_leads} open now, so it shares like Even`;
    return `${firstName(light)} has ${light.open_leads} open, ${firstName(heavy)} ${heavy.open_leads}: ${firstName(light)} gets leads first`;
  }
  const city = rule === "by_city";
  if (!leads) {
    if (!two) return null;
    return city
      ? `For example, one city's leads to ${firstName(one)}, another's to ${firstName(two)}`
      : `For example, Facebook leads to ${firstName(one)}, website leads to ${firstName(two)}`;
  }
  if (!plan) return null;
  const names = Object.entries(city ? plan.cities : plan.sources)
    .sort((a, b) => b[1] - a[1])
    .map(([name]) => name);
  if (!names.length)
    return `None of these leads has a ${city ? "city" : "source"} to go by`;
  if (names.length === 1 || !two)
    return `${names[0]} leads to ${firstName(one)}`;
  return `${names[0]} leads to ${firstName(one)}, ${names[1]} to ${firstName(two)}`;
}

/** The one line under the title: what this sheet does, here and now. */
export function introLine(target: ShareTarget): string {
  if (target.kind === "unassigned" && !target.count)
    return "New leads go out by your lead rules. A lead nobody can take yet waits with no owner, and you share it out here.";
  return "This gives them out once, the way you pick below. New leads keep going out by your lead rules.";
}

/**
 * Why a plan moves nothing, and what the button says instead of a bare
 * "Nothing to give out". `picked` counts the sellers chosen for the rule.
 */
export function nothingWhy(
  plan: Distribution,
  picked: number,
  rule: ShareRule,
): { line: string; button: string } {
  const word = rule === "by_city" ? "city" : "source";
  const byGroup = rule === "by_source" || rule === "by_city";
  if (!picked)
    return byGroup
      ? {
          line: `Pick a seller for at least one ${word}.`,
          button: "Pick sellers first",
        }
      : {
          line: "Tick at least one seller under To.",
          button: "Pick a seller first",
        };
  const { left } = plan;
  if (left.everyone_at_cap)
    return {
      line: "Everyone you picked is at their open-lead limit. Pick more sellers, or raise a limit in lead rules.",
      button: "Everyone is full",
    };
  if (left.no_seller_for_it)
    return {
      line: `No seller is picked for these leads' ${rule === "by_city" ? "cities" : "sources"} yet.`,
      button: "Pick sellers first",
    };
  if (left.already_theirs)
    return {
      line: "These leads are already with the sellers you picked.",
      button: "Nothing to give out",
    };
  if (left.closed)
    return {
      line: "These leads are won, lost or junk. Closed leads stay where they are.",
      button: "Nothing to give out",
    };
  return {
    line: "None of these leads can move now.",
    button: "Nothing to give out",
  };
}

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
  const router = useRouter();

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
      ? target.count
        ? `${target.count.toLocaleString("en-IN")} ${target.count === 1 ? "lead" : "leads"} with no owner`
        : "Every open lead has an owner"
      : `${target.leadIds.length} chosen ${target.leadIds.length === 1 ? "lead" : "leads"}`;

  // The examples use the sellers ticked under To, or everyone taking leads.
  const leads =
    target.kind === "unassigned" ? target.count : target.leadIds.length;
  const taking = reps.filter((rep) => rep.available);
  const ticked = reps.filter((rep) => chosen.includes(rep.person_id));
  const pool = ticked.length ? ticked : taking.length ? taking : reps;
  const groupPool = taking.length ? taking : reps;
  const picked = byGroup
    ? Object.values(groups).filter((list) => list.length).length
    : chosen.length;
  // Nothing waits with no owner: the one action is where new leads are set.
  const allOwned =
    target.kind === "unassigned" &&
    (!target.count || (current && plan?.leads === 0));
  const why =
    current && plan && !plan.moved && !allOwned
      ? nothingWhy(plan, picked, rule)
      : null;
  const openRules = () => {
    onClose();
    leavingOverlay();
    router.push(settingsPath("lead-rules"));
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Share out leads"
      description={what}
      footer={
        allOwned ? (
          <button type="button" className={styles.give} onClick={openRules}>
            Open lead rules
          </button>
        ) : (
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
                : (why?.button ?? "Nothing to give out")
              : "Working out the plan…"}
          </button>
        )
      }
    >
      <div className={styles.body}>
        <p className={styles.intro}>{introLine(target)}</p>
        <fieldset className={styles.rules}>
          <legend>How</legend>
          {RULES.map((item) => {
            const example = ruleExample(
              item.key,
              leads,
              item.key === "by_source" || item.key === "by_city"
                ? groupPool
                : pool,
              plan,
            );
            return (
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
                  {example ? (
                    <small className={styles.example}>{example}</small>
                  ) : null}
                </span>
              </label>
            );
          })}
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
                          ? rep.max_open === null
                            ? `${rep.open_leads} open · no limit`
                            : `${rep.open_leads} open · limit ${rep.max_open}`
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
          ) : allOwned ? (
            <p className={styles.why} role="status">
              Nothing to share right now. Leads that wait with no owner also
              show on Leads under No owner.
            </p>
          ) : !current || !plan ? (
            <p className={styles.quiet}>Working out who gets what…</p>
          ) : why ? (
            <p className={styles.why} role="status">
              {why.line}
            </p>
          ) : (
            <>
              {plan.given.length ? (
                <ul className={styles.given}>
                  {plan.given.map((row) => (
                    <li key={row.person_id}>
                      <span>{displayName(row.name)}</span>
                      <strong>{`+${row.leads}`}</strong>
                      <small>
                        {row.max_open === null
                          ? `${row.open_after} open`
                          : `${row.open_after} open of ${row.max_open}`}
                      </small>
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
