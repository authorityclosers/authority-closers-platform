"use client";

/**
 * A salesperson's profile (owner, 21 Oct 2026: "we need the profile of the sales person"),
 * built on the AC design system Pulse uses (../../ds): one header strip of who they are
 * today, then at most five tabs with icons. Overview is the person page's calls, charts and
 * coaching; Leads is the leads they hold; Settings (owners and admins) holds their lead
 * rules and how much AI reads their calls. Errors are corner cards; no prices anywhere.
 */

import {
  CircleUserRound,
  LayoutDashboard,
  ListChecks,
  SlidersHorizontal,
  Smartphone,
  Users,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import {
  CallAiError,
  LEVEL_NAMES,
  levelFor,
  readCallAi,
  saveCallAiPerson,
  type CallAiLevel,
  type CallAiSettings,
} from "../../call-ai/call-ai-client";
import choice from "../../call-ai/call-ai.module.css";
import {
  Button,
  Card,
  EmptyState,
  List,
  ListRow,
  Tabs,
  Tag,
  type Hue,
} from "../../ds";
import { DsScope } from "../../ds/scope";
import {
  LeadsError,
  readLeads,
  readTeam,
  saveRep,
  splitList,
  type LeadRow,
  type RepView,
  type Team,
} from "../../leads/leads-client";
import {
  LIMIT_RULE,
  LimitField,
  limitDraft,
  overBy,
  readLimit,
} from "../../leads/limit-field";
import { phoneDot } from "../../leads/phone-setup-words";
import { notify } from "../../notice-center";
import styles from "./seller-profile.module.css";

export type SellerTab = "overview" | "leads" | "settings";
const TABS: SellerTab[] = ["overview", "leads", "settings"];

const STAGE_HUE: Record<string, Hue> = {
  new: "sky",
  not_connected: "slate",
  follow_up: "amber",
  interested: "green",
  won: "teal",
  lost: "pink",
};
const LEVEL_HUE: Record<CallAiLevel, Hue> = {
  off: "slate",
  data_only: "amber",
  auto: "sky",
  full: "green",
};

/** The tab in the address (?tab=), read in the browser only and kept there on change. */
function askedTab(): SellerTab {
  if (typeof window === "undefined") return "overview";
  const asked = new URLSearchParams(window.location.search).get("tab");
  return asked && (TABS as string[]).includes(asked)
    ? (asked as SellerTab)
    : "overview";
}

function useTab(): [SellerTab, (tab: SellerTab) => void] {
  // The profile draws in the browser only (after the account check), so the
  // address can be read for the first render.
  const [tab, setTab] = useState<SellerTab>(askedTab);
  const choose = (next: SellerTab) => {
    setTab(next);
    const url = new URL(window.location.href);
    if (next === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url);
  };
  return [tab, choose];
}

const problem = (id: string, title: string, reason: unknown) =>
  notify({
    id,
    tone: "error",
    title,
    message:
      reason instanceof LeadsError || reason instanceof CallAiError
        ? reason.message
        : "Check your connection and try again.",
  });

export function SellerSections({
  personId,
  firstName,
  isYou,
  canManage,
  canSeeTeam = canManage,
  overview,
}: {
  personId: string;
  firstName: string;
  isYou: boolean;
  canManage: boolean;
  canSeeTeam?: boolean;
  overview: ReactNode;
}) {
  const [tab, setTab] = useTab();
  const [team, setTeam] = useState<Team | null>(null);
  const [callAi, setCallAi] = useState<CallAiSettings | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    // The team read is for owners and admins; a seller sees their own level only.
    if (canManage)
      readTeam(controller.signal)
        .then(setTeam)
        .catch(() => undefined);
    readCallAi(controller.signal)
      .then(setCallAi)
      .catch(() => undefined);
    return () => controller.abort();
  }, [canManage]);

  const rep = team?.reps.find((item) => item.person_id === personId) ?? null;
  const level = callAi
    ? canManage
      ? levelFor(callAi, personId)
      : isYou
        ? { level: callAi.you.level, own: callAi.you.source === "person" }
        : null
    : null;
  const items = [
    {
      key: "overview",
      label: "Overview",
      icon: <LayoutDashboard aria-hidden />,
    },
    {
      key: "leads",
      label: "Leads",
      icon: <ListChecks aria-hidden />,
      count: rep?.open_leads,
    },
    ...(canManage
      ? [
          {
            key: "settings",
            label: "Settings",
            icon: <SlidersHorizontal aria-hidden />,
          },
        ]
      : []),
  ];

  return (
    <DsScope className={styles.scope}>
      {rep || (level && !canManage) ? (
        <div className={styles.today}>
          {/* Quiet chips (owner, 25 Oct 2026): only what needs a look. A
              manager finds the phone app and AI on calls under Settings. */}
          {(rep && !rep.available) || (level && !canManage) ? (
            <div className={styles.tags}>
              {rep && !rep.available ? (
                <Tag hue="slate">Not taking leads</Tag>
              ) : null}
              {level && !canManage ? (
                <Tag hue={LEVEL_HUE[level.level]}>
                  AI on calls: {LEVEL_NAMES[level.level]}
                  {level.own ? "" : " (default)"}
                </Tag>
              ) : null}
            </div>
          ) : null}
          {rep && overBy(rep) > 0 ? (
            <p className={styles.over} role="status">
              {`Over limit by ${overBy(rep)}`}
              {canManage ? (
                <>
                  <span aria-hidden="true">·</span>
                  <button
                    type="button"
                    className={styles.overChange}
                    onClick={() => setTab("settings")}
                  >
                    Change
                  </button>
                </>
              ) : null}
            </p>
          ) : null}
          {rep ? (
            <p className={styles.workload}>
              <span>
                <strong>{rep.open_leads}</strong>{" "}
                {rep.max_open === null ? "Open leads, no limit" : "Open leads"}
              </span>
              <span>
                <strong>{rep.due_now}</strong> Due now
              </span>
            </p>
          ) : null}
        </div>
      ) : null}
      <Tabs
        items={items}
        current={tab === "settings" && !canManage ? "overview" : tab}
        onSelect={(key) => setTab(key as SellerTab)}
        label={`${firstName}'s profile`}
      />
      <div className={styles.panel}>
        {tab === "leads" ? (
          <SellerLeads
            personId={personId}
            firstName={firstName}
            isYou={isYou}
            canManage={canSeeTeam}
          />
        ) : tab === "settings" && canManage ? (
          <SellerSettings
            firstName={firstName}
            rep={rep}
            callAi={callAi}
            personId={personId}
            onTeam={setTeam}
            onCallAi={setCallAi}
          />
        ) : (
          overview
        )}
      </div>
    </DsScope>
  );
}

function SellerLeads({
  personId,
  firstName,
  isYou,
  canManage,
}: {
  personId: string;
  firstName: string;
  isYou: boolean;
  canManage: boolean;
}) {
  const [page, setPage] = useState<{ leads: LeadRow[]; total: number } | null>(
    null,
  );
  const [failed, setFailed] = useState(false);
  const [clock] = useState(() => Date.now());
  const [filter, setFilter] = useState(() =>
    typeof window === "undefined"
      ? "open"
      : (new URLSearchParams(window.location.search).get("insight") ?? "open"),
  );
  const [visible, setVisible] = useState(20);
  useEffect(() => {
    if (!canManage && !isYou) return;
    const controller = new AbortController();
    async function load() {
      const rows: LeadRow[] = [];
      // Read every page before calculating insights. A first page is never a total.
      for (const stage of ["open", "won", "lost"]) {
        let offset = 0;
        while (!controller.signal.aborted) {
          const next = await readLeads(
            canManage
              ? { scope: "team", owner: personId, stage, offset }
              : { scope: "mine", stage, offset },
            controller.signal,
          );
          rows.push(...next.leads);
          offset += next.leads.length;
          if (offset >= next.total || !next.leads.length) break;
        }
      }
      if (!controller.signal.aborted)
        setPage({
          leads: [
            ...new Map(rows.map((lead) => [lead.lead_id, lead])).values(),
          ],
          total: rows.length,
        });
    }
    load().catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setFailed(true);
      problem("seller-leads", "Leads didn't load", reason);
    });
    return () => controller.abort();
  }, [personId, canManage, isYou]);

  if (!canManage && !isYou)
    return (
      <EmptyState
        icon={<Users aria-hidden />}
        hue="slate"
        title="Only owners and admins see a teammate's leads"
      />
    );
  if (failed)
    return (
      <EmptyState
        icon={<ListChecks aria-hidden />}
        hue="slate"
        title="Leads didn't load"
      />
    );
  if (!page)
    return (
      <div
        className={styles.loading}
        aria-busy="true"
        aria-label="Loading leads"
      />
    );
  if (!page.leads.length)
    return (
      <EmptyState
        icon={<ListChecks aria-hidden />}
        title={isYou ? "No open leads" : `${firstName} has no open leads`}
        action={<Button href="/leads?tab=all">All leads</Button>}
      >
        New leads go to whoever fits the lead rules and has the fewest open
        leads.
      </EmptyState>
    );
  const open = (lead: LeadRow) =>
    !["won", "lost", "junk"].includes(lead.group ?? lead.stage);
  const weekStart = new Date();
  // The desk uses India time; Monday starts the calendar working week.
  const local = new Date(clock + 330 * 60000);
  weekStart.setTime(
    Date.UTC(
      local.getUTCFullYear(),
      local.getUTCMonth(),
      local.getUTCDate() - ((local.getUTCDay() + 6) % 7),
    ) -
      330 * 60000,
  );
  const thisWeek = (lead: LeadRow) =>
    !!lead.stage_at && Date.parse(lead.stage_at) >= weekStart.getTime();
  const matches = (lead: LeadRow, key: string) =>
    key === "open"
      ? open(lead)
      : key === "late"
        ? open(lead) && !!lead.overdue
        : key === "untouched"
          ? lead.stage === "new" && lead.last_contact_at == null
          : key === "won" || key === "lost"
            ? (lead.group ?? lead.stage) === key && thisWeek(lead)
            : open(lead) && (lead.step ?? lead.stage) === key;
  const stages = [
    ...new Map(
      page.leads
        .filter(open)
        .map((lead) => [lead.step ?? lead.stage, lead.stage_label]),
    ).entries(),
  ];
  const insights = [
    ["open", "Open leads"],
    ["late", "Late follow-ups"],
    ["untouched", "Untouched new leads"],
    ["won", "Won this week"],
    ["lost", "Lost this week"],
    ...stages,
  ];
  const filtered = page.leads.filter((lead) => matches(lead, filter));
  const choose = (key: string) => {
    setFilter(key);
    setVisible(20);
    const url = new URL(window.location.href);
    url.searchParams.set("insight", key);
    window.history.replaceState(window.history.state, "", url);
  };
  return (
    <>
      <div className={styles.insights} aria-label="Seller lead insights">
        {insights.map(([key, label]) => (
          <button
            type="button"
            key={key}
            aria-pressed={filter === key}
            onClick={() => choose(key)}
          >
            <strong>
              {page.leads.filter((lead) => matches(lead, key)).length}
            </strong>
            <span>{label}</span>
          </button>
        ))}
      </div>
      <Card
        title={insights.find(([key]) => key === filter)?.[1] ?? "Leads"}
        sub={`${filtered.length} leads, next call first`}
        pad="md"
      >
        {filtered.length ? (
          <List label="Seller leads">
            {filtered.slice(0, visible).map((lead) => (
              <ListRow
                key={lead.lead_id}
                href={`/leads#lead=${encodeURIComponent(lead.lead_id)}`}
                title={lead.name}
                sub={
                  [lead.city, lead.interest].filter(Boolean).join(" · ") ||
                  lead.source_label
                }
                meta={
                  <Tag hue={STAGE_HUE[lead.stage] ?? "slate"}>
                    {lead.overdue ? "Late · " : ""}
                    {lead.stage_label}
                  </Tag>
                }
                chevron
              />
            ))}
          </List>
        ) : (
          <p className={styles.quiet}>
            No leads match this view.{" "}
            <button type="button" onClick={() => choose("open")}>
              Show open leads
            </button>
          </p>
        )}
        {filtered.length > visible ? (
          <Button variant="ghost" onClick={() => setVisible((n) => n + 20)}>
            Show more
          </Button>
        ) : null}
      </Card>
    </>
  );
}

function SellerSettings({
  firstName,
  rep,
  callAi,
  personId,
  onTeam,
  onCallAi,
}: {
  firstName: string;
  rep: RepView | null;
  callAi: CallAiSettings | null;
  personId: string;
  onTeam: (team: Team) => void;
  onCallAi: (settings: CallAiSettings) => void;
}) {
  return (
    <div className={styles.settings}>
      {rep ? (
        <RulesCard
          key={`${rep.person_id}:${rep.revision}`}
          rep={rep}
          onTeam={onTeam}
        />
      ) : (
        <Card
          title="Lead rules"
          icon={<CircleUserRound aria-hidden />}
          hue="sky"
        >
          <p className={styles.quiet}>
            {firstName} isn&apos;t on the Leads team yet. Their rules appear
            once they can take leads.
          </p>
        </Card>
      )}
      {callAi ? (
        <AiCard
          key={`${personId}:${callAi.revision ?? 0}`}
          callAi={callAi}
          personId={personId}
          firstName={firstName}
          onSaved={onCallAi}
        />
      ) : null}
      {rep ? (
        <Card title="Phone app" icon={<Smartphone aria-hidden />} hue="sky">
          <p className={styles.quiet}>{phoneWords(rep)}</p>
        </Card>
      ) : null}
    </div>
  );
}

/** The phone app's state in one line, with what is left to set up. */
function phoneWords(rep: RepView): string {
  const dot = phoneDot(rep.phone);
  return dot.missing.length
    ? `${dot.label} · To finish: ${dot.missing.join(", ")}`
    : dot.label;
}

function RulesCard({
  rep,
  onTeam,
}: {
  rep: RepView;
  onTeam: (team: Team) => void;
}) {
  const [available, setAvailable] = useState(rep.available);
  const [cap, setCap] = useState(() => limitDraft(rep.max_open));
  const [languages, setLanguages] = useState(rep.languages.join(", "));
  const [areas, setAreas] = useState(rep.areas.join(", "));
  const [interests, setInterests] = useState(rep.interests.join(", "));
  const [saving, setSaving] = useState(false);
  const save = async () => {
    const max = readLimit(cap);
    if (max === undefined) {
      problem("seller-rules", "Not saved", new LeadsError(LIMIT_RULE, 422));
      return;
    }
    setSaving(true);
    try {
      onTeam(
        await saveRep(rep, {
          available,
          max_open: max,
          languages: splitList(languages).slice(0, 12),
          areas: splitList(areas),
          interests: splitList(interests),
        }),
      );
      notify({
        id: "seller-rules",
        tone: "success",
        title: "Lead rules saved",
        timeout: 3000,
      });
    } catch (reason) {
      problem("seller-rules", "Lead rules not saved", reason);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Card
      title="Lead rules"
      sub="Empty boxes mean no limit. New leads go to whoever fits and has the fewest open leads."
      icon={<ListChecks aria-hidden />}
      hue="sky"
    >
      <label className={styles.toggle}>
        <input
          type="checkbox"
          checked={available}
          onChange={(event) => setAvailable(event.target.checked)}
        />
        Takes new leads now
      </label>
      <div className={styles.fields}>
        <LimitField
          id={`limit-${rep.person_id}`}
          label="Most open leads at once"
          hint={rep.default_cap ? "Organisation default" : undefined}
          draft={cap}
          onChange={setCap}
        />
        <label className={styles.field}>
          <span>Languages</span>
          <input
            value={languages}
            placeholder="Hindi, Marathi, English"
            onChange={(event) => setLanguages(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>Areas</span>
          <input
            value={areas}
            placeholder="Cities or regions"
            onChange={(event) => setAreas(event.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>Products</span>
          <input
            value={interests}
            placeholder="What they sell, as leads name it"
            onChange={(event) => setInterests(event.target.value)}
          />
        </label>
      </div>
      <div>
        <Button variant="primary" disabled={saving} onClick={() => void save()}>
          {saving ? "Saving…" : "Save rules"}
        </Button>
      </div>
    </Card>
  );
}

function AiCard({
  callAi,
  personId,
  firstName,
  onSaved,
}: {
  callAi: CallAiSettings;
  personId: string;
  firstName: string;
  onSaved: (settings: CallAiSettings) => void;
}) {
  const own = levelFor(callAi, personId);
  const start: CallAiLevel | "" = own.own ? own.level : "";
  const [chosen, setChosen] = useState<CallAiLevel | "">(start);
  const [saving, setSaving] = useState(false);
  const options: { id: CallAiLevel | ""; name: string; hint: string }[] = [
    {
      id: "",
      name: `Organisation default (${LEVEL_NAMES[callAi.default]})`,
      hint: "Follows the level in Settings → AI on calls.",
    },
    ...callAi.levels,
  ];
  const save = async () => {
    setSaving(true);
    try {
      onSaved(
        await saveCallAiPerson(callAi.revision, personId, chosen || null),
      );
      notify({
        id: "seller-ai",
        tone: "success",
        title: "AI on calls saved",
        timeout: 3000,
      });
    } catch (reason) {
      problem("seller-ai", "AI on calls not saved", reason);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Card
      title="AI on calls"
      sub={`How much AI reads ${firstName}'s recorded calls. Changes apply to calls from now on.`}
      icon={<SlidersHorizontal aria-hidden />}
      hue="green"
    >
      <div
        className={choice.choices}
        role="radiogroup"
        aria-label={`AI on ${firstName}'s calls`}
      >
        {options.map((option) => (
          <label
            key={option.id || "default"}
            className={choice.choice}
            data-checked={option.id === chosen ? "" : undefined}
          >
            <input
              type="radio"
              name={`ai-${personId}`}
              value={option.id}
              checked={option.id === chosen}
              disabled={saving}
              onChange={() => setChosen(option.id)}
            />
            <span className={choice.choiceText}>
              <strong>{option.name}</strong>
              <small>{option.hint}</small>
            </span>
          </label>
        ))}
      </div>
      <div>
        <Button
          variant="primary"
          disabled={saving || chosen === start}
          onClick={() => void save()}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </Card>
  );
}
