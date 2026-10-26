"use client";

/**
 * "Taking new leads" (UX study item 8, 18 Oct): a seller's own switch, like
 * Privyr's duty status and TeleCRM's On leave. While it is off the lead rules
 * give them nothing new and their open leads stay with them. It is the same
 * flag a manager sets on Team ("Takes leads").
 *
 * On the kit's StateSwitch (owner, 23 Oct 2026: "the user must feel the
 * importance of that, and a popup"): the state is said in words, turning it
 * off asks first, and the chip on Leads opens the switch in a sheet instead of
 * flipping on a tap. Outside the team's work hours (with the pause on) new
 * leads wait for everyone: the switch says so and until when, and an owner or
 * admin can hand leads out after hours from here.
 */

import { UserRoundCheck, UserRoundX } from "lucide-react";
import { useEffect, useState } from "react";

import { StateSwitch, type SwitchHold } from "../ui/state-switch";
import {
  readTeam,
  saveWorkHours,
  setTaking,
  when,
  type Team,
} from "./leads-client";

export function TakingSwitch({
  initial,
  place,
  onChanged,
  pausedUntil = null,
}: {
  initial: boolean;
  place: "header" | "row" | "chip";
  onChanged?: () => void;
  /** Outside the team's work hours, new leads wait until this time. */
  pausedUntil?: string | null;
}) {
  const [on, setOn] = useState(initial);
  const [until, setUntil] = useState(pausedUntil);
  // While paused, owners and admins can read the work hours and lift the
  // pause; a seller's read is refused and the row says who sets them.
  const [team, setTeam] = useState<Team | null>(null);
  useEffect(() => {
    if (!until) return;
    const controller = new AbortController();
    readTeam(controller.signal)
      .then(setTeam)
      .catch(() => setTeam(null));
    return () => controller.abort();
  }, [until]);

  const change = async (next: boolean) => {
    setOn(next);
    try {
      const me = await setTaking(next);
      setOn(me.taking_leads ?? next);
      setUntil(me.paused_until ?? null);
      onChanged?.();
    } catch (reason) {
      setOn(!next);
      throw reason;
    }
  };

  const hours = team?.settings.work_hours ?? null;
  const hold: SwitchHold | null = until
    ? {
        title: "Paused for work hours",
        reason: `Outside work hours${
          hours ? ` (${hours.start} to ${hours.end})` : ""
        }. New leads wait until ${when(until)}, then come to you.`,
        chip: "Paused, after hours",
        override:
          team && hours?.pause_leads
            ? {
                label: "Hand out leads after hours",
                note: "For the whole team, until you turn the pause back on.",
                confirm: {
                  title: "Hand out new leads after hours?",
                  points: [
                    "New leads go out at any hour to sellers who are taking leads.",
                    "This turns off the work-hours pause for the whole team.",
                    "Turn it back on in Settings, Lead rules, Work hours.",
                  ],
                  confirm: "Hand out leads now",
                  keep: "Keep the pause",
                },
                run: async () => {
                  const saved = await saveWorkHours(team.settings.revision, {
                    days: hours.days,
                    start: hours.start,
                    end: hours.end,
                    pause_leads: false,
                  });
                  setTeam(saved);
                  setUntil(null);
                  onChanged?.();
                },
              }
            : undefined,
        who: team ? undefined : "Your owner or admin sets the work hours.",
      }
    : null;

  return (
    <StateSwitch
      icon={on ? <UserRoundCheck size={20} /> : <UserRoundX size={20} />}
      label="Taking new leads"
      meaning="While this is on, the lead rules can give you new leads. Your open leads stay with you either way."
      onText="You're receiving new leads"
      offText="Paused: new leads go to others. Your open leads stay with you."
      chipOn="Taking leads"
      chipOff="Not taking leads"
      on={on}
      hold={hold}
      confirmOff={{
        title: "Stop taking new leads?",
        points: [
          "New leads go to other sellers until you turn this back on.",
          "Your open leads and follow-ups stay with you.",
          "Turn it back on any time, from Leads or Settings, Selling.",
        ],
        confirm: "Stop taking leads",
        keep: "Keep taking leads",
      }}
      onChange={change}
      place={place === "chip" ? "chip" : "row"}
    />
  );
}
