"use client";

/**
 * Settings → AI on calls: the organisation's default level for every seller's
 * recorded calls, and who has their own. Owners and admins choose; everyone
 * else sees what applies to their calls. Errors are corner cards.
 */

import { Sparkles, Users } from "lucide-react";
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

/** One choice per level, its plain words underneath. */
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
          <span className={styles.choiceText}>
            <strong>{level.name}</strong>
            <small>{level.hint}</small>
          </span>
        </label>
      ))}
    </div>
  );
}

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
            How much AI reads each recorded call. Every call is still saved and
            logged on its lead. Changes apply to calls from now on.
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
                <Button
                  variant="primary"
                  disabled={saving || selected === settings.default}
                  onClick={() => void save()}
                >
                  {saving ? "Saving…" : "Save default"}
                </Button>
                {choice !== null && choice !== settings.default ? (
                  <Button
                    variant="ghost"
                    disabled={saving}
                    onClick={() => setChoice(null)}
                  >
                    Cancel
                  </Button>
                ) : null}
              </div>
            </>
          ) : (
            <p className={styles.yours}>
              Your calls: <strong>{LEVEL_NAMES[settings.you.level]}</strong>
              {settings.you.source === "person"
                ? " (set for you by an owner or admin)."
                : " (your organisation's default)."}
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
                <span>{person.name}</span>
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
          <p className={styles.foot}>
            Set one seller&apos;s level in{" "}
            <Link href="/leads?tab=team">Leads → Team</Link>: tap their name.
          </p>
        ) : null}
      </Panel>
    </div>
  );
}
