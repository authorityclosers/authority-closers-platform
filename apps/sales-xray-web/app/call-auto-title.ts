/**
 * Owner 18 Oct: a new call is named from its report instead of "Untitled
 * call" — the prospect's company, their name or the topic, read from the
 * report's own summary. Words only; no AI call. When nothing clear is said
 * (or the summary is not in English) the call keeps its dated default name.
 */

const COMPANY_ENDS = new Set(
  (
    "services enterprise enterprises limited ltd ltd. pvt pvt. industries " +
    "traders trading solutions builders developers realty realtors group " +
    "company co co. corp corporation llp agency associates technologies " +
    "tech infra infrastructure construction constructions motors foods " +
    "exports consultants consultancy ventures properties estates homes " +
    "labs studio studios systems logistics pharma clinic hospital academy " +
    "institute school"
  ).split(" "),
);
const JOINERS = new Set(["and", "&", "of"]);
const NOT_NAMES = new Set(
  (
    "a an the his her their its this that prospect client customer owner " +
    "founder director manager team you your them him"
  ).split(" "),
);
const TOPIC_AFTER =
  /\b(?:regarding|about|covering|concerning|detailing|into)\s+([^.,;:()]+)/i;
const TOPIC_STOP =
  /\s+(?:for|with|in|at|from|to|while|and then|and agreed|and secured|where|which|who|including|before|after|under|by)\s+.*$/i;
const LEADING =
  /^(?:the prospect['’]s|the client['’]s|the customer['’]s|their|his|her|its|the|a|an)\s+/i;
const MAX_TITLE = 80;

const capitalised = (word: string) => /^[A-Z][\p{L}\p{N}&'’.-]*$/u.test(word);

function clean(word: string) {
  return word.replace(/[,.;:!?)]+$/, "").replace(/^[(]+/, "");
}

/** "Bloom and Building Material Enterprise" from "... owner of Bloom and ...". */
function company(words: string[]): string | null {
  for (let end = 0; end < words.length; end += 1) {
    const last = clean(words[end]);
    if (!COMPANY_ENDS.has(last.toLowerCase()) || !capitalised(last)) continue;
    let start = end;
    while (start > 0) {
      const before = clean(words[start - 1]);
      if (words[start - 1] !== before) break; // punctuation ends the name
      if (capitalised(before) && !NOT_NAMES.has(before.toLowerCase()))
        start -= 1;
      else if (
        JOINERS.has(before) &&
        start - 2 >= 0 &&
        capitalised(clean(words[start - 2]))
      )
        start -= 1;
      else break;
    }
    while (start < end && JOINERS.has(clean(words[start]))) start += 1;
    // "... Services Private Limited": keep the whole legal name.
    while (
      end + 1 < words.length &&
      words[end] === clean(words[end]) &&
      (COMPANY_ENDS.has(clean(words[end + 1]).toLowerCase()) ||
        clean(words[end + 1]) === "Private") &&
      capitalised(clean(words[end + 1]))
    )
      end += 1;
    if (start === end) continue; // "Services" alone is not a name
    return words
      .slice(start, end + 1)
      .map(clean)
      .join(" ");
  }
  return null;
}

/** "Ira Ransurikar" from "... conversation with Ira Ransurikar." */
function person(summary: string, companyName: string | null): string | null {
  const match =
    /\b(?:with|to|for)\s+((?:(?:Mr|Mrs|Ms|Dr)\.?\s+)?[A-Z][\p{L}-]+(?:\s+[A-Z][\p{L}-]+)?)/u.exec(
      summary,
    );
  if (!match) return null;
  const name = match[1];
  if (companyName && companyName.startsWith(name)) return null;
  const first = name.split(/\s+/)[0].toLowerCase();
  if (NOT_NAMES.has(first) || first === "you") return null;
  const lastWord = name.split(/\s+/).at(-1)!.toLowerCase();
  if (COMPANY_ENDS.has(lastWord)) return null;
  return name;
}

/** "Brindle Cart" from "... with Daryl Pell, sales lead at Brindle Cart." */
function workplace(summary: string, who: string): string | null {
  const after = summary.slice(summary.indexOf(who) + who.length);
  const match =
    /^[^.;]{0,60}?\bat\s+([A-Z][\p{L}&-]+(?:\s+[A-Z][\p{L}&-]+){0,3})/u.exec(
      after,
    );
  return match ? match[1] : null;
}

/** "environmental permissions" from "... regarding environmental permissions for a ...". */
function topic(summary: string): string | null {
  const match = TOPIC_AFTER.exec(summary);
  if (!match) return null;
  let phrase = match[1].replace(TOPIC_STOP, "").trim();
  for (let i = 0; i < 3; i += 1) phrase = phrase.replace(LEADING, "");
  const words = phrase.split(/\s+/).filter(Boolean);
  if (words.length === 0 || words.length > 6 || /^\d/.test(words[0]))
    return null;
  if (/^(?:you|them|him|her|it|this|that)$/i.test(words[0])) return null;
  return words.join(" ");
}

function sentenceCase(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function fit(title: string) {
  return [...title].length > MAX_TITLE
    ? `${[...title]
        .slice(0, MAX_TITLE - 1)
        .join("")
        .trimEnd()}…`
    : title;
}

/** A short name for a call from its report summary, or null to keep the default. */
export function autoCallTitle(
  summary: string | null | undefined,
): string | null {
  const text = (summary ?? "").replace(/\s+/g, " ").trim();
  if (!text) return null;
  // English words only: a Hindi or Marathi summary keeps the default name.
  const latin = text.replace(/[^\p{L}]/gu, "");
  if (!latin || (latin.match(/[A-Za-z]/g)?.length ?? 0) / latin.length < 0.9)
    return null;
  const sentences = text.split(
    /(?<!\b(?:Mr|Mrs|Ms|Dr)\.)(?<=[.!?])\s+(?=[A-Z])/,
  );
  const first = sentences[0];
  const business =
    company(first.split(" ")) ??
    // "Synthetic test call. X discussed Y for Z Private Limited."
    (sentences[1] ? company(sentences[1].split(" ")) : null);
  const who = person(first, business);
  const place = who && !business ? workplace(first, who) : null;
  if (who && place) return fit(`${who} · ${place}`);
  if (business) return fit(who ? `${who} · ${business}` : business);
  const about = topic(first);
  if (who && about) return fit(`${who} · ${sentenceCase(about)}`);
  if (who) return fit(`Call with ${who}`);
  if (about) return fit(sentenceCase(about));
  return null;
}
