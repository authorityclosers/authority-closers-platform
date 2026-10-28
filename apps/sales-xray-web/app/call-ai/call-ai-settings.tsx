"use client";

/**
 * Settings → AI on calls: the organisation's default level for every seller's
 * recorded calls, and who has their own. Owners and admins choose; everyone
 * else sees what applies to their calls. Errors are corner cards.
 */

import {
  ChevronRight,
  CircleOff,
  FileText,
  Sparkles,
  Users,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { notify } from "../notice-center";
import { Badge, Button, Empty, Panel, Skeleton } from "../ui/kit";
import {
  CallAiError,
  LEVEL_NAMES,
  readCallAi,
  saveCallAiDefault,
  type CallAiLevel,
  type CallAiSettings,
} from "./call-ai-client";
import styles from "./call-ai.module.css";

/** Each level's mark, so the four rows read at a glance. */
const LEVEL_ICON: Record<CallAiLevel, LucideIcon> = {
  off: CircleOff,
  data_only: FileText,
  auto: WandSparkles,
  full: Sparkles,
};

/**
 * One choice per level as rows of one grouped list (owner, 29 Oct 2026: calm
 * and clean like Insights): its mark, name and plain words, a check on the
 * chosen one. The radio stays the control, so keys and screen readers work.
 */
export function LevelChoices({
  settings,
  value,
  onChange,
  disabled,
  name,
}: {
  settings: CallAiSettings;
  value: CallAiLevel;
  onChange: (level: CallAiLevel) => void;
  disabled?: boolean;
  name: string;
}) {
  return (
    <div className={styles.choices} role="radiogroup" aria-label={name}>
      {settings.levels.map((level) => (
        <label
          key={level.id}
          className={styles.choice}
          data-checked={level.id === value ? "" : undefined}
        >
          <input
            type="radio"
            name={name}
            value={level.id}
            checked={level.id === value}
            disabled={disabled}
            onChange={() => onChange(level.id)}
          />
          <LevelMark level={level.id} />
          <span className={styles.choiceText}>
            <strong>{level.name}</strong>
            <small>{level.hint}</small>
          </span>
        </label>
      ))}
    </div>
  );
}

function LevelMark({ level }: { level: CallAiLevel }) {
  const Icon = LEVEL_ICON[level];
  return (
    <span className={styles.mark} data-level={level} aria-hidden="true">
      <Icon size={18} />
    </span>
  );
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

export function CallAiSettingsSection() {
  const [settings, setSettings] = useState<CallAiSettings | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [choice, setChoice] = useState<CallAiLevel | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    readCallAi(controller.signal)
      .then(setSettings)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setFailed(
          reason instanceof CallAiError
            ? reason.message
            : "AI on calls didn't load.",
        );
      });
    return () => controller.abort();
  }, []);

  if (failed)
    return (
      <Empty icon={Sparkles} title="AI on calls didn't load" text={failed} />
    );
  if (!settings)
    return (
      <div aria-busy="true" aria-label="Loading AI on calls">
        <Skeleton height={320} />
      </div>
    );

  const selected = choice ?? settings.default;
  const save = async () => {
    setSaving(true);
    try {
      const next = await saveCallAiDefault(settings.revision, selected);
      setSettings(next);
      setChoice(null);
      notify({
        id: "call-ai-default",
        tone: "success",
        title: "Saved",
        message: `New calls now run on ${LEVEL_NAMES[next.default]}.`,
      });
    } catch (reason) {
      notify({
        id: "call-ai-default",
        tone: "error",
        title: "Not saved",
        message:
          reason instanceof CallAiError
            ? reason.message
            : "Not saved. Try again.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.stack}>
      <Panel
        title="AI on calls"
        sub={`Default: ${LEVEL_NAMES[settings.default]}`}
      >
        <div className={styles.body}>
          <p className={styles.lead}>
            How much AI reads each recorded call. Calls are always saved on
            their lead; changes apply from now on.
          </p>
          {settings.can_edit ? (
            <>
              <LevelChoices
                settings={settings}
                value={selected}
                onChange={setChoice}
                disabled={saving}
                name="Organisation default"
              />
              <div className={styles.actions}>
                {choice !== null && choice !== settings.default ? (
                  <Button
                    variant="ghost"
                    disabled={saving}
                    onClick={() => setChoice(null)}
                  >
                    Cancel
                  </Button>
                ) : null}
                <Button
                  variant="primary"
                  disabled={saving || selected === settings.default}
                  onClick={() => void save()}
                >
                  {saving ? "Saving…" : "Save default"}
                </Button>
              </div>
            </>
          ) : (
            <p className={styles.yours}>
              <LevelMark level={settings.you.level} />
              <span>
                Your calls: <strong>{LEVEL_NAMES[settings.you.level]}</strong>
                <small>
                  {settings.you.source === "person"
                    ? "Set for you by an owner or admin."
                    : "Your organisation's default."}
                </small>
              </span>
            </p>
          )}
        </div>
      </Panel>

      <Panel
        title="Sellers with their own level"
        sub={`${settings.people.length}`}
      >
        {settings.people.length ? (
          <ul className={styles.people}>
            {settings.people.map((person) => (
              <li key={person.person_id}>
                <span className={styles.who}>
                  <i aria-hidden="true">{initials(person.name)}</i>
                  <span>{person.name}</span>
                </span>
                <Badge tone={person.level === "full" ? "good" : "neutral"}>
                  {LEVEL_NAMES[person.level]}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>
            <Users size={16} aria-hidden="true" /> Everyone follows the default.
          </p>
        )}
        {settings.can_edit ? (
          <Link href="/leads?tab=team" className={styles.foot}>
            <span>
              Set one seller&apos;s level
              <small>Leads → Team, then tap their name</small>
            </span>
            <ChevronRight size={18} aria-hidden="true" />
          </Link>
        ) : null}
      </Panel>
    </div>
  );
}
