import { BRANDS, type Brand } from "./brands/brand-registry";

// Finds what a piece of text mentions (brands, programs, money, documents,
// places, dates, people's roles...) in English, Hindi and Marathi, so any
// screen can show those mentions as icon chips. Pure text matching: no AI
// call, nothing invented, and the words shown are always the words written.

export type EntityKind =
  | "brand"
  | "program"
  | "money"
  | "percent"
  | "document"
  | "video"
  | "date"
  | "time"
  | "person"
  | "team"
  | "place"
  | "email"
  | "website";

export type Entity = Readonly<{
  kind: EntityKind;
  text: string;
  /** Set for brand mentions. */
  brand?: Brand;
}>;

export type TextPart = string | Entity;

// Unicode-aware word edges: \b only knows ASCII, and Devanagari vowel signs
// are marks (\p{M}), so "गूगल" must not match inside a longer word.
const START = String.raw`(?<![\p{L}\p{M}\p{N}_])`;
const END = String.raw`(?![\p{L}\p{M}\p{N}_])`;
const word = (pattern: string) => `${START}(?:${pattern})${END}`;
const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** An alias as a pattern: spaces may be missing or repeated ("phone pe"). */
const alias = (value: string) =>
  value
    .trim()
    .split(/\s+/)
    .map(escape)
    .join(String.raw`\s*`);

const PLACES = [
  "Ahmedabad|अहमदाबाद",
  "Mumbai|Bombay|मुंबई|मुम्बई",
  "Pune|पुणे",
  "Delhi|New Delhi|दिल्ली",
  "Bengaluru|Bangalore|बेंगलुरु|बैंगलोर",
  "Hyderabad|हैदराबाद",
  "Chennai|चेन्नई",
  "Kolkata|कोलकाता",
  "Surat|सूरत",
  "Jaipur|जयपुर",
  "Lucknow|लखनऊ",
  "Kanpur|कानपुर",
  "Nagpur|नागपुर",
  "Indore|इंदौर",
  "Bhopal|भोपाल",
  "Nashik|नाशिक",
  "Rajkot|राजकोट",
  "Vadodara|Baroda|वडोदरा",
  "Noida|नोएडा",
  "Gurugram|Gurgaon|गुरुग्राम|गुड़गांव",
  "Chandigarh|चंडीगढ़",
  "Kochi|Coimbatore|Visakhapatnam|Bhubaneswar",
  "Patna|पटना",
  "Ludhiana|लुधियाना",
  "Agra|आगरा",
  "Varanasi|वाराणसी",
  "Goa|गोवा",
  "Thane|ठाणे",
  "Aurangabad|औरंगाबाद",
  "Kolhapur|कोल्हापुर",
  "Raipur|रायपुर",
  "Ranchi|रांची",
  "Dehradun|देहरादून",
  "Amritsar|अमृतसर",
  "Udaipur|उदयपुर",
  "Jodhpur|जोधपुर",
  "Gujarat|गुजरात",
  "Maharashtra|महाराष्ट्र",
  "Rajasthan|राजस्थान",
  "Punjab|पंजाब",
  "Karnataka|Kerala|केरल|Tamil Nadu|Bihar|बिहार",
  "Dubai|दुबई",
  "America|अमेरिका|USA",
  "London|लंदन",
  "Singapore|सिंगापुर",
  "Canada|कनाडा",
  "Australia|ऑस्ट्रेलिया",
].join("|");

const NUMBER = String.raw`\d+(?:[,.]\d+)*`;
const AMOUNT = `${NUMBER}(?:\\s?(?:to|-|–|से)\\s?${NUMBER})?`;

// Case matters on purpose: only capitalised names read as a program, and
// only "Zoom" (not "zoom in") reads as a brand.
const PATTERNS: Array<[EntityKind, string]> = [
  [
    "program",
    [
      String.raw`\b\d+[- ][Dd]ay\s+(?:\p{Lu}[\w-]*\s+){0,4}(?:[Pp]rogram(?:me)?|[Cc]ourse|[Ww]orkshop|[Tt]raining|[Bb]ootcamp|[Ee]vent|[Ww]ebinar|[Ss]eminar)\b`,
      String.raw`\b(?:\p{Lu}[\w-]*\s+){1,4}(?:Program(?:me)?|Course|Workshop|Bootcamp|Masterclass|Webinar|Seminar|Summit)\b`,
      word(
        "webinar|masterclass|bootcamp|वेबिनार|सेमिनार|वर्कशॉप|मास्टरक्लास|प्रोग्राम|कोर्स|ट्रेनिंग",
      ),
    ].join("|"),
  ],
  [
    "money",
    [
      String.raw`₹\s?${AMOUNT}(?:\s?(?:lakhs?|lacs?|crores?|cr|k|K|लाख|करोड़|करोड))?`,
      String.raw`\$\s?${AMOUNT}(?:\s?(?:k|K|m|M|million|billion))?`,
      String.raw`\b(?:Rs\.?|INR|USD|dollars?)\s?${AMOUNT}(?:\s?(?:lakhs?|lacs?|crores?|cr|k|K|m|M|million|billion))?`,
      `${START}${AMOUNT}\\s?(?:rupees|रुपये|रुपए|रुपया|dollars?|USD)(?:\\s+(?:rupees|रुपये|रुपए))?${END}`,
      String.raw`\b(?:[Uu]npaid\s+)?[Rr]eceivables?\b|\b[Rr]evenue\b|\b[Tt]urnover\b|\b[Pp]rofit margins?\b`,
      word("टर्नओवर|रेवेन्यू|प्रॉफिट"),
    ].join("|"),
  ],
  [
    "percent",
    `${START}\\d+(?:\\.\\d+)?\\s?(?:%|percent|per cent|प्रतिशत|टक्के|परसेंट)`,
  ],
  [
    "document",
    [
      String.raw`\b[Ss]yllabus\b|\b[Ww]orkbooks?\b|\b[Bb]rochures?\b|\b[Pp]roposals?\b|\bPDFs?\b|\b[Qq]uotations?\b|\b[Ii]nvoices?\b|\b[Cc]ontracts?\b|\bGST\b`,
      word("सिलेबस|ब्रोशर|पीडीएफ|प्रपोज़ल|प्रपोजल|कोटेशन|इनवॉइस|कॉन्ट्रैक्ट"),
    ].join("|"),
  ],
  [
    "video",
    [
      String.raw`\b[Vv]ideos?\b|\b[Rr]ecordings?\b|\b[Rr]eels?\b`,
      word("वीडियो|रिकॉर्डिंग|रील"),
    ].join("|"),
  ],
  [
    "date",
    [
      String.raw`\b[Nn]ext day\b|\b[Tt]omorrow\b|\b[Nn]ext (?:week|month|year)\b|\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b`,
      String.raw`\b\d{1,2}(?:st|nd|rd|th)?\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b`,
      word(
        "परसों|अगले हफ्ते|अगले हफ़्ते|अगले महीने|सोमवार|मंगलवार|बुधवार|गुरुवार|शुक्रवार|शनिवार|रविवार|उद्या|पुढच्या आठवड्यात",
      ),
    ].join("|"),
  ],
  [
    "time",
    [
      String.raw`\b\d{1,2}(?::\d{2})?\s?(?:am|pm|AM|PM)\b`,
      `${START}\\d+[- ]?(?:minutes?|mins?|hours?|hrs?|मिनट|घंटे|घंटा|मिनिटे|तास)${END}`,
      `${START}\\d{1,2}\\s?बजे${END}`,
    ].join("|"),
  ],
  [
    "team",
    `${START}\\d+\\s?(?:staff|employees|workers|people|team members|लोग|कर्मचारी|स्टाफ|कामगार)${END}`,
  ],
  [
    "person",
    [
      String.raw`\b[Ss]enior manager\b|\b[Dd]ecision[- ]maker\b|\b[Bb]usiness partner\b|\b[Cc]o-?founder\b|\b[Ff]ounder\b|\b(?:CEO|CFO|COO|CTO|MD|HR)\b|\b[Cc]hartered [Aa]ccountant\b`,
      word("मालिक|डायरेक्टर|मैनेजर|पार्टनर|फाउंडर|सीए"),
    ].join("|"),
  ],
  ["place", word(PLACES)],
  [
    "email",
    String.raw`[\w.+-]+@[\w-]+\.[\w.]+|\b[Ee]-?mails?\b|${word("ईमेल")}`,
  ],
  [
    "website",
    String.raw`\b[Ww]ebsites?\b|\b[Ll]anding pages?\b|${word("वेबसाइट|लैंडिंग पेज")}`,
  ],
];

type Span = Entity & { start: number; end: number };

const byAlias = new Map<string, Brand>();
const exactAliases: string[] = [];
const anyCaseAliases: string[] = [];
for (const brand of BRANDS) {
  for (const name of brand.words) {
    byAlias.set(name.toLocaleLowerCase().replace(/\s+/g, ""), brand);
    anyCaseAliases.push(name);
  }
  for (const name of brand.exact) {
    byAlias.set(name.toLocaleLowerCase().replace(/\s+/g, ""), brand);
    exactAliases.push(name);
  }
}
// Longest first, so "google meet" wins over "google".
const longest = (a: string, b: string) => b.length - a.length;
// Marathi (and sometimes Hindi) joins case endings to the word:
// "व्हॉट्सॲपवर" is "on WhatsApp". The chip keeps the word as written.
const ENDING = "वरून|वरती|वर|मध्ये|च्या|चा|ची|चे|ला|ने|नी|त|पे|पर|में|से";
const brandWord = (aliases: string[]) =>
  `${START}(?<a>${aliases.sort(longest).map(alias).join("|")})(?:${ENDING})?${END}`;
const BRAND_ANY_CASE = new RegExp(brandWord(anyCaseAliases), "giu");
const BRAND_EXACT = new RegExp(brandWord(exactAliases), "gu");
const MATCHER = new RegExp(
  PATTERNS.map(([kind, pattern]) => `(?<${kind}>${pattern})`).join("|"),
  "gu",
);

function brandOf(text: string) {
  return byAlias.get(text.toLocaleLowerCase().replace(/\s+/g, ""));
}

function collect(text: string): Span[] {
  const spans: Span[] = [];
  for (const matcher of [BRAND_ANY_CASE, BRAND_EXACT])
    for (const match of text.matchAll(matcher)) {
      const brand = brandOf(match.groups?.a ?? match[0]);
      if (!brand) continue;
      const start = match.index ?? 0;
      spans.push({
        kind: "brand",
        text: match[0],
        brand,
        start,
        end: start + match[0].length,
      });
    }
  for (const match of text.matchAll(MATCHER)) {
    const kind = Object.entries(match.groups ?? {}).find(
      ([, value]) => value !== undefined,
    )?.[0] as EntityKind | undefined;
    if (!kind || !match[0].trim()) continue;
    const start = match.index ?? 0;
    spans.push({ kind, text: match[0], start, end: start + match[0].length });
  }
  // Earliest first; at the same start the longer mention (then a brand) wins.
  return spans.sort(
    (a, b) =>
      a.start - b.start ||
      b.end - a.end ||
      Number(b.kind === "brand") - Number(a.kind === "brand"),
  );
}

/** Splits text into plain runs and the mentions found in it. */
export function findEntities(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;
  for (const span of collect(text)) {
    if (span.start < last) continue;
    if (span.start > last) parts.push(text.slice(last, span.start));
    parts.push(
      span.brand
        ? { kind: span.kind, text: span.text, brand: span.brand }
        : { kind: span.kind, text: span.text },
    );
    last = span.end;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** Just the mentions, in order. */
export function mentions(text: string): Entity[] {
  return findEntities(text).filter(
    (part): part is Entity => typeof part !== "string",
  );
}

/** A curated brand by any of its names, in any case. */
export function brandNamed(name: string): Brand | null {
  return brandOf(name) ?? null;
}
