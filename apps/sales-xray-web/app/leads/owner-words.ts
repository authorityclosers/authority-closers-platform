/**
 * Who a lead is with, in plain words (owner, 18 Oct: "0 open leads (fewest)"
 * and "Move to…" were "not that intuitive"). The lead rules store a short
 * note when they pick an owner (lead_desk/allocation.py); leads keep that
 * note, so it is reworded here when shown, old leads included.
 */

const VERB: Readonly<Record<string, string>> = {
  speaks: "speak",
  covers: "cover",
  sells: "sell",
};

function joined(parts: string[]): string {
  return parts.length < 2
    ? (parts[0] ?? "")
    : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLocaleLowerCase() + text.slice(1);
}

function upperFirst(text: string): string {
  return text.charAt(0).toLocaleUpperCase() + text.slice(1);
}

function reword(text: string): string {
  const moved = /^Moved by (.+?)\.?$/.exec(text);
  if (moved) return `Reassigned by ${moved[1]}.`;
  const gap =
    /^Nobody free speaks (.+?); \d+ open leads?, the fewest\.?$/i.exec(text);
  if (gap)
    return `Picked automatically: nobody free speaks ${gap[1]}, so it went to whoever had the fewest open leads.`;
  const rules = /^(.*?)(?:,\s*)?\d+ open leads?( \(fewest\))?\.?$/i.exec(text);
  if (!rules) return text;
  const clauses = rules[1]
    .split(/,\s*/)
    .map((part) => lowerFirst(part.trim()))
    .filter(Boolean);
  const relaxed = clauses.filter((part) => part.startsWith("nobody free"));
  const fits = clauses
    .filter((part) => !part.startsWith("nobody free"))
    .map((part) => part.replace(/^(\w+)/, (verb) => VERB[verb] ?? verb));
  fits.push(
    rules[2]
      ? "had the fewest open leads"
      : "were the only seller who could take it",
  );
  const sentence = `Picked automatically because they ${joined(fits)}.`;
  return relaxed.length
    ? `${sentence} ${upperFirst(joined(relaxed))}.`
    : sentence;
}

/** The lead rules' note for an owner, reworded for people; null when none. */
export function ownerNote(reason: string | null | undefined): string | null {
  const text = reason?.trim();
  if (!text) return null;
  const late = /^No call in (\d+) minutes?\.\s*/i.exec(text);
  const rest = late ? text.slice(late[0].length) : text;
  const note = [
    late ? `Moved on after ${late[1]} min with no call.` : "",
    rest ? reword(rest) : "",
  ]
    .filter(Boolean)
    .join(" ");
  return note || null;
}

/** How fast the first call came, or that none has yet. */
export function firstCallWords(
  minutes: number | null | undefined,
  cameIn: string,
): string {
  if (minutes == null) return `Not called yet · came in ${cameIn}`;
  if (minutes < 1) return "Called within a minute of coming in";
  if (minutes < 60) return `Called ${minutes} min after it came in`;
  const hours = Math.round(minutes / 60);
  if (hours < 48)
    return `Called ${hours} hour${hours === 1 ? "" : "s"} after it came in`;
  return `Called ${Math.round(hours / 24)} days after it came in`;
}
