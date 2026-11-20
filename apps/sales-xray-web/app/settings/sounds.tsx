"use client";

/**
 * Sounds & alerts (owner's round-2 board 4, option B, 20 Nov 2026): one row per
 * moment, grouped as the sound library groups them (Calls · Messages & leads ·
 * Reminders · Feedback). A row says the sound and whether it is the team's
 * or the person's own; a tap opens a tall sheet of that moment's sounds,
 * grouped by pack, each with ▶ to hear it, and picking one plays it once.
 * "Test all" plays every moment in turn.
 *
 * The owner's page (TeamSounds) sets the sound for everyone with one dropdown
 * per moment and ▶ beside it, whether sellers may pick their own, and a reset
 * to the library's. Choices are library ids, never files (SOUND-PICKER.md).
 */
import {
  CalendarClock,
  Check,
  CircleCheck,
  MessageCircle,
  Pause,
  PhoneIncoming,
  Play,
  RotateCcw,
  TriangleAlert,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button, IconTile, Tag, type Hue } from "../ds";
import { DsScope } from "../ds/scope";
import { notify } from "../notice-center";
import {
  CATEGORIES,
  KINDS,
  SX_EVENTS,
  type SoundEvent,
  type SxEventId,
} from "../sounds/library";
import { isPlaying, playSound, stopSound } from "../sounds/player";
import {
  readSounds,
  saveMine,
  saveTeam,
  SoundsError,
  type SoundRow,
  type SoundsView,
} from "../sounds/prefs";
import {
  choiceLabel,
  NONE,
  soundFiles,
  soundsOfKind,
  SYSTEM,
  type SoundChoice,
} from "../sounds/sounds";
import { Picker } from "../ui/picker";
import { Sheet } from "../ui/sheet";
import { Skeleton } from "../ui/kit";
import { soundPicked, soundPreviewed } from "../sounds/telemetry";
import { savedFor, ScopeChip, useOrgName } from "./scope-chip";
import styles from "./sounds.module.css";

const ICON: Record<SxEventId, { icon: ReactNode; hue: Hue }> = {
  "sx.incoming_call": { icon: <PhoneIncoming />, hue: "sky" },
  "sx.new_lead": { icon: <UsersRound />, hue: "green" },
  "sx.new_message": { icon: <MessageCircle />, hue: "indigo" },
  "sx.follow_up_due": { icon: <CalendarClock />, hue: "orange" },
  "sx.report_ready": { icon: <CircleCheck />, hue: "teal" },
  "sx.upload_failed": { icon: <TriangleAlert />, hue: "pink" },
};

/** When the picked sound is next heard, in the words of its moment. */
const NEXT: Record<SxEventId, string> = {
  "sx.incoming_call": "your next incoming call",
  "sx.new_lead": "your next new lead",
  "sx.new_message": "your next message",
  "sx.follow_up_due": "your next follow-up",
  "sx.report_ready": "your next call report",
  "sx.upload_failed": "the next recording problem",
};

const failed = (error: unknown) =>
  notify({
    id: "sounds",
    tone: "error",
    title: "That wasn’t saved",
    message:
      error instanceof SoundsError && error.status < 500
        ? error.message
        : "Check your connection and try again.",
  });

/** Re-renders while a sound plays, so ▶ turns into ❚❚ and back. */
function usePlaying(): [
  SoundChoice | null,
  (choice: SoundChoice, event?: SxEventId) => void,
] {
  const [now, setNow] = useState<SoundChoice | null>(null);
  useEffect(() => stopSound, []);
  const toggle = (choice: SoundChoice, event?: SxEventId) => {
    if (isPlaying(choice)) {
      stopSound();
      setNow(null);
      return;
    }
    const started = playSound(choice, {
      ended: () => setNow((was) => (was === choice ? null : was)),
    });
    setNow(started ? choice : null);
    if (started) soundPreviewed(event, choice);
  };
  return [now, toggle];
}

/** ▶ for one sound; none and the phone's own have nothing to hear here. */
function PlayButton({
  choice,
  playing,
  onToggle,
  name,
  feature,
}: {
  choice: SoundChoice;
  playing: boolean;
  onToggle: () => void;
  name: string;
  feature: string;
}) {
  const silent = !soundFiles(choice);
  return (
    <button
      type="button"
      className={styles.play}
      data-playing={playing ? "" : undefined}
      aria-label={playing ? `Stop ${name}` : `Play ${name}`}
      title={silent ? "Nothing to hear here" : undefined}
      disabled={silent}
      data-sx-feature={feature}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
    >
      {playing ? (
        <Pause size={16} aria-hidden="true" />
      ) : (
        <Play size={16} aria-hidden="true" />
      )}
    </button>
  );
}

/** A moment's sounds in a tall sheet, grouped by pack, each with ▶. */
function PickSheet({
  event,
  row,
  team,
  onClose,
  onSave,
}: {
  event: SoundEvent;
  row: SoundRow;
  /** Whether there is a team default to go back to (none in a personal workspace). */
  team: boolean;
  onClose: () => void;
  onSave: (choice: SoundChoice | null) => Promise<boolean>;
}) {
  const [chosen, setChosen] = useState<SoundChoice>(row.plays);
  const [saving, setSaving] = useState(false);
  const [playing, toggle] = usePlaying();
  const pick = (choice: SoundChoice) => {
    setChosen(choice);
    // Picking plays it once (SOUND-PICKER.md rule 1).
    if (!isPlaying(choice)) toggle(choice, event.id);
  };
  /** Saves the pick: the team's own sound is no pick of one's own. */
  const done = async (choice: SoundChoice | null) => {
    const next = choice === row.team ? null : choice;
    if (next === row.mine) {
      onClose();
      return;
    }
    setSaving(true);
    const ok = await onSave(next);
    setSaving(false);
    if (ok) onClose();
  };
  const option = (choice: SoundChoice, label: string) => (
    <li key={choice}>
      <div
        className={styles.option}
        aria-selected={chosen === choice}
        role="option"
      >
        <PlayButton
          choice={choice}
          playing={playing === choice}
          onToggle={() => toggle(choice, event.id)}
          name={label}
          feature="sound_preview"
        />
        <button
          type="button"
          className={styles.optionPick}
          data-sx-feature="sound_pick"
          onClick={() => pick(choice)}
        >
          <span>{label}</span>
          {playing === choice ? (
            <span className={styles.playingNote} aria-hidden="true">
              <span className={styles.wave} />
              Playing
            </span>
          ) : null}
          {chosen === choice ? (
            <Check size={18} aria-hidden="true" className={styles.check} />
          ) : null}
        </button>
      </div>
    </li>
  );
  return (
    <Sheet
      open
      onClose={onClose}
      title={event.label}
      description="Tap ▶ to hear a sound, tap its name to pick it."
      footer={
        <div className={styles.sheetFoot}>
          {team && row.mine ? (
            <Button
              variant="secondary"
              disabled={saving}
              data-sx-feature="sound_use_team"
              onClick={() => void done(null)}
            >
              Use team default
            </Button>
          ) : null}
          <Button
            variant="primary"
            disabled={saving}
            data-sx-feature="sound_done"
            onClick={() => void done(chosen)}
          >
            {saving ? "Saving…" : "Done"}
          </Button>
        </div>
      }
    >
      <div className={styles.sheetBody} role="listbox" aria-label={event.label}>
        {soundsOfKind(event.kind).map((group) => (
          <section
            key={group.family}
            className={styles.pack}
            aria-label={group.label}
          >
            <h3>{group.label}</h3>
            <ul>
              {group.sounds.map((sound) => option(sound.id, sound.label))}
            </ul>
          </section>
        ))}
        <section className={styles.pack} aria-label="Other">
          <ul>
            {option(SYSTEM, "Phone default")}
            {option(NONE, "None")}
          </ul>
        </section>
      </div>
    </Sheet>
  );
}

function RowsReading() {
  return (
    <div className={styles.groups} aria-busy="true">
      {CATEGORIES.map((category) => (
        <section key={category.id} className={styles.group}>
          <h2>{category.label}</h2>
          <div className={styles.card}>
            <div className={styles.bone}>
              <Skeleton width={44} height={44} radius={12} />
              <Skeleton width={180} height={18} />
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}

const byCategory = (view: SoundsView) =>
  CATEGORIES.map((category) => ({
    ...category,
    rows: SX_EVENTS.filter(
      (event) => KINDS[event.kind].category === category.id,
    ).map((event) => ({
      event,
      row: view.events.find((item) => item.id === event.id) as SoundRow,
    })),
  })).filter((group) => group.rows.length > 0);

/** Plays every moment in turn; the ringtone a few seconds only. */
function useTestAll(view: SoundsView | null) {
  const [running, setRunning] = useState<SxEventId | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
      stopSound();
    },
    [],
  );
  const stop = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
    stopSound();
    setRunning(null);
  };
  const start = () => {
    if (!view) return;
    if (running) {
      stop();
      return;
    }
    const queue = view.events.filter((row) => soundFiles(row.plays));
    const next = (index: number) => {
      const row = queue[index];
      if (!row) {
        setRunning(null);
        timer.current = null;
        return;
      }
      setRunning(row.id);
      playSound(row.plays);
      timer.current = window.setTimeout(
        () => next(index + 1),
        row.id === "sx.incoming_call" ? 3_500 : 2_000,
      );
    };
    next(0);
  };
  return { running, start };
}

/** The person's own sounds: Settings › Sounds & alerts (Just me). */
export function MySounds() {
  const [view, setView] = useState<SoundsView | null>(null);
  const [away, setAway] = useState(false);
  const [open, setOpen] = useState<SxEventId | null>(null);
  const { running, start } = useTestAll(view);
  useEffect(() => {
    const controller = new AbortController();
    readSounds(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setView(value);
      },
      () => {
        if (!controller.signal.aborted) setAway(true);
      },
    );
    return () => controller.abort();
  }, []);
  if (away)
    return (
      <p className={styles.note}>
        Sounds can’t be read just now. Check your connection and open this page
        again.
      </p>
    );
  const team = view ? !view.local : true;
  const locked = view ? !view.sellers_pick && !view.manager : false;
  const openEvent = open ? SX_EVENTS.find((event) => event.id === open) : null;
  const openRow =
    open && view ? view.events.find((row) => row.id === open) : null;

  const save = async (id: SxEventId, choice: SoundChoice | null) => {
    if (!view) return false;
    try {
      setView(await saveMine(view, { [id]: choice }));
      const plays = choice ?? view.events.find((row) => row.id === id)?.team;
      if (plays) soundPicked(id, plays, view.local ? "phone" : "me");
      notify({
        id: "sounds",
        tone: "success",
        title: savedFor(view.local ? "phone" : "me", null),
        message: plays
          ? `${choiceLabel(plays)} plays on ${NEXT[id]}.`
          : undefined,
        timeout: 4_000,
      });
      return true;
    } catch (error) {
      failed(error);
      return false;
    }
  };

  return (
    <DsScope className={styles.page}>
      <div className={styles.lead}>
        <p>Pick a sound for each moment. Tap ▶ to hear it.</p>
        <ScopeChip scope={view?.local ? "phone" : "me"} />
      </div>
      <div className={styles.actions}>
        <Button
          variant="secondary"
          icon={running ? <Pause size={16} /> : <Play size={16} />}
          disabled={!view}
          onClick={start}
          data-sx-feature="sound_test_all"
        >
          {running ? "Stop" : "Test all"}
        </Button>
        {view?.manager ? (
          <Button
            href="/settings/team-sounds"
            variant="ghost"
            data-sx-feature="sound_team_open"
          >
            Sounds for everyone
          </Button>
        ) : null}
      </div>
      {locked ? (
        <p className={styles.note}>
          Your team uses the same sounds for everyone, so these are set by your
          owner.
        </p>
      ) : null}
      {!view ? (
        <RowsReading />
      ) : (
        <div className={styles.groups}>
          {byCategory(view).map((group) => (
            <section
              key={group.id}
              className={styles.group}
              aria-label={group.label}
            >
              <h2>{group.label}</h2>
              <ul className={styles.card}>
                {group.rows.map(({ event, row }) => {
                  const look = ICON[event.id];
                  const body = (
                    <>
                      <IconTile icon={look.icon} hue={look.hue} size="lg" />
                      <span className={styles.rowText}>
                        <strong>{event.label}</strong>
                        <small>{choiceLabel(row.plays)}</small>
                      </span>
                      <span className={styles.rowMeta}>
                        {running === event.id ? (
                          <Tag hue="green">Playing</Tag>
                        ) : row.mine ? (
                          <Tag hue="green">Mine</Tag>
                        ) : (
                          <Tag>{team ? "Team default" : "Default"}</Tag>
                        )}
                      </span>
                    </>
                  );
                  return (
                    <li key={event.id}>
                      {locked ? (
                        <div className={styles.row}>{body}</div>
                      ) : (
                        <button
                          type="button"
                          className={styles.row}
                          data-sx-feature="sound_open"
                          aria-haspopup="dialog"
                          onClick={() => setOpen(event.id)}
                        >
                          {body}
                          <span className={styles.chevron} aria-hidden="true">
                            ›
                          </span>
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
      <p className={styles.note}>
        On some phones (Redmi, Oppo, Samsung) the phone’s own notification
        settings can change these sounds. If a sound isn’t what you picked,
        check Sales X-Ray’s notifications in the phone’s settings.
      </p>
      {openEvent && openRow ? (
        <PickSheet
          key={openEvent.id}
          event={openEvent}
          row={openRow}
          team={team}
          onClose={() => {
            stopSound();
            setOpen(null);
          }}
          onSave={(choice) => save(openEvent.id, choice)}
        />
      ) : null}
    </DsScope>
  );
}

/** The team's sounds: Settings › Sounds for everyone (owners, admins, managers). */
export function TeamSounds() {
  const org = useOrgName();
  const [view, setView] = useState<SoundsView | null>(null);
  const [away, setAway] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [playing, toggle] = usePlaying();
  useEffect(() => {
    const controller = new AbortController();
    readSounds(controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return;
        if (value.local)
          setAway(
            "Team sounds are for an organisation. Your own sounds are in Sounds & alerts.",
          );
        else if (!value.manager)
          setAway("Your owner or an admin sets the team’s sounds.");
        else setView(value);
      },
      () => {
        if (!controller.signal.aborted)
          setAway(
            "Sounds can’t be read just now. Check your connection and open this page again.",
          );
      },
    );
    return () => controller.abort();
  }, []);
  if (away)
    return (
      <p className={styles.note}>
        {away}{" "}
        <Link href="/settings/sounds" className={styles.link}>
          Your sounds
        </Link>
      </p>
    );

  const save = async (
    team: Partial<Record<SxEventId, SoundChoice>>,
    sellersPick: boolean,
  ) => {
    if (!view) return;
    setBusy(true);
    try {
      setView(await saveTeam(team, sellersPick));
      notify({
        id: "sounds",
        tone: "success",
        title: savedFor("everyone", org),
        timeout: 4_000,
      });
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  };
  const teamOf = (id: SxEventId) =>
    view?.events.find((row) => row.id === id)?.team ?? NONE;

  return (
    <DsScope className={styles.page}>
      <div className={styles.lead}>
        <p>Sellers hear these unless they pick their own.</p>
        <ScopeChip scope="everyone" org={org} />
      </div>
      {view ? (
        <p className={styles.count}>
          {view.own_picks === 0
            ? "Everyone uses the team’s sounds."
            : view.own_picks === 1
              ? "1 person picked sounds of their own."
              : `${view.own_picks} people picked sounds of their own.`}
        </p>
      ) : null}
      {!view ? (
        <RowsReading />
      ) : (
        <div className={styles.groups}>
          {byCategory(view).map((group) => (
            <section
              key={group.id}
              className={styles.group}
              aria-label={group.label}
            >
              <h2>{group.label}</h2>
              <ul className={styles.card}>
                {group.rows.map(({ event }) => {
                  const look = ICON[event.id];
                  const current = teamOf(event.id);
                  return (
                    <li key={event.id} className={styles.teamRow}>
                      <IconTile icon={look.icon} hue={look.hue} size="lg" />
                      <strong className={styles.teamLabel}>
                        {event.label}
                      </strong>
                      <span
                        className={styles.teamPick}
                        data-sx-feature="team_sound_pick"
                      >
                        <Picker
                          title={event.label}
                          ariaLabel={`Sound for ${event.label}`}
                          value={current}
                          disabled={busy}
                          options={[
                            ...soundsOfKind(event.kind).flatMap((g) =>
                              g.sounds.map((sound) => ({
                                key: sound.id,
                                label: sound.label,
                              })),
                            ),
                            { key: SYSTEM, label: "Phone default" },
                            { key: NONE, label: "None" },
                          ]}
                          onChange={(key) => {
                            if (!key || key === current) return;
                            // Picking plays it once (SOUND-PICKER.md rule 1).
                            if (soundFiles(key)) playSound(key);
                            soundPicked(event.id, key, "team");
                            void save({ [event.id]: key }, view.sellers_pick);
                          }}
                        />
                      </span>
                      <PlayButton
                        choice={current}
                        playing={playing === current}
                        onToggle={() => toggle(current, event.id)}
                        name={choiceLabel(current)}
                        feature="team_sound_preview"
                      />
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
      {view ? (
        <div className={styles.teamFoot}>
          <label className={styles.switchRow}>
            <button
              type="button"
              role="switch"
              aria-checked={view.sellers_pick}
              aria-label="Sellers can pick their own sounds"
              className={styles.toggle}
              disabled={busy}
              data-sx-feature="team_sound_sellers_pick"
              onClick={() => void save({}, !view.sellers_pick)}
            >
              <span aria-hidden="true" />
            </button>
            <span>
              <strong>Sellers can pick their own sounds</strong>
              <small>
                {view.sellers_pick
                  ? "On: a seller’s own pick plays on their phone."
                  : "Off: everyone hears the sounds above."}
              </small>
            </span>
          </label>
          <Button
            variant="secondary"
            icon={<RotateCcw size={16} />}
            disabled={busy}
            data-sx-feature="team_sound_reset"
            onClick={() =>
              void save(
                Object.fromEntries(
                  SX_EVENTS.map((event) => [event.id, event.default]),
                ),
                view.sellers_pick,
              )
            }
          >
            Reset to library default
          </Button>
        </div>
      ) : null}
    </DsScope>
  );
}
