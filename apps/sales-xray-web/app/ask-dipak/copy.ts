/**
 * Ask Dipak's screen words, as Dipak's spec and sample have them (13 Nov
 * 2026), in his Hindi-English voice; nothing is translated or rewritten.
 * The sample's notes about itself ("this clickable sample", "demo
 * placeholders") are left out; the one line written here is NOT_READY, for a
 * question whose lesson isn't in the library yet (spec section 24).
 */
export const COPY = {
  title: "Ask Dipak",
  // Sentence case: no ALL CAPS Latin beside Hindi (redesign study §4).
  eyebrow: "Dipak Vishwakarma · Your sales mentor",
  hello: "Hey! Dipak this side. 👋",
  intro: [
    "Sales में 10+ years और दो businesses build करने के दौरान एक बात बार-बार समझ आई है।",
    "कभी-कभी एक सही question पूरी sales conversation बदल देता है।",
    "यहाँ हम real situations explore करेंगे, decisions लेंगे और practical चीजें समझेंगे — एक-एक करके।",
  ],
  introAsk: "तो बताओ, आज क्या समझना चाहते हो?",
  // The compact greeting's fold (owner, 16 Nov 2026); Dipak's lines unchanged.
  introMore: "Dipak के बारे में",
  introLess: "कम दिखाएँ",
  savedLessons: "Saved lessons",
  searchPlaceholder: "Search questions or topics",
  explore: "Explore topics",
  seeAll: "See all",
  real: "Start with a real situation",
  parts: "Quick answer · Deep lesson · MCQ",
  notice:
    "Choose a topic or describe your situation in search. Answers are curated from Dipak's lessons.",
  allTitle: "Explore by topic",
  allSub: "Pick the area you want to improve today.",
  topicChip: "Explore topics",
  topicSub: "अपनी situation से जुड़ा सवाल चुनिए।",
  categorySub: "जो सवाल आज आपके काम का हो, उसे खोलिए।",
  searchTitle: "क्या समझना चाहते हो?",
  searchSub: "अपनी sales situation या कोई topic search कीजिए।",
  noMatch: "अभी matching lesson नहीं मिला",
  noMatchHint:
    "एक और word या topic try करें—जैसे price, objection, trust या closing.",
  savedTitle: "Saved lessons",
  savedSub: "अपने जरूरी questions फिर से खोलिए।",
  savedEmpty: "अभी कुछ save नहीं किया",
  savedEmptyHint: "किसी lesson का bookmark tap करके उसे यहाँ रख सकते हैं।",
  // His words above the before/after lines (doc 01), for every lesson's pair.
  shift: "इस answer से कौन-सी सोच बदलनी है",
  before: "पहले की गलत सोच",
  after: "नई सोच",
  better: "Better सोच",
  // A lesson comes from the API when opened (16 Nov 2026); words to redesign.
  loading: "Lesson खुल रहा है…",
  loadFailed: "यह lesson अभी नहीं खुल पाया। Internet check करके फिर try करें।",
  retry: "फिर try करें",
  quick: "Dipak का quick answer",
  turn: "अब आपकी बारी",
  feedback: "Dipak की बात",
  compare: "बाकी options भी चुनकर उनकी reasoning देखिए।",
  deep: "Deep lesson",
  deepSub: "पूरी situation को example से समझिए",
  cue: "याद रखने वाली बात",
  mission: "Next-call mission",
  // The mission as a plan (redesign study §5 S4.7, N-A): commit, then say after calls.
  missionTodo:
    "अगली relevant calls में try करेंगे? Commit करें, calls के बाद हम पूछेंगे।",
  related: "इसके बाद क्या सीखें?",
  save: "Save lesson",
  unsave: "Remove saved lesson",
  markMission: "I’ll try this mission on my next calls",
  undoMission: "Take this mission off",
  searchTool: "Search questions",
  savedTool: "Saved questions",
  backToQuestions: "Back to questions",
  notFound: "Lesson not found.",
  // The coaching loop's way in (13 Nov 2026 meeting); words to redesign.
  myMissions: "My Next-call missions",
  myMissionsMeta: "Your active missions and calls to answer",
  // A lesson drafted for Dipak to confirm (owner, 16 Nov 2026).
  draftTag: "Draft · Dipak to confirm",
  draftMission: "Dipak के confirm करने के बाद यह mission mark कर पाएँगे।",
  notReadyChip: "Lesson not ready yet",
  notReady: "यह lesson अभी तैयार नहीं है। आप दूसरा सवाल खोल सकते हैं।",
  // The Coach's desk (owner's pick H-A, 17 Nov 2026; redesign study §5 S1).
  // Our own screen words, never shown as Dipak's.
  continue: "Continue",
  libraryTitle: "Dipak's lessons",
  libraryMeta: (lessons: number, topics: number) =>
    `${lessons} lessons · ${topics} topics · Start anywhere`,
  libraryGo: "Explore",
  missionLabel: "Your next-call mission",
  missionAsk: "Did you try it?",
  checkinAsk: (lead: string, at: string) =>
    `${lead} वाली call${at ? ` (${at})` : ""} में try किया?`,
  checkinYes: "हाँ, try किया",
  checkinNo: "मौका नहीं मिला",
  checkinNote: "यह आपकी अपनी report है, score नहीं।",
  checkinFailed: "Save नहीं हुआ। Internet check करके फिर try करें।",
  checkinThanks: (tried: number) =>
    `Noted. Tried on ${tried} ${tried === 1 ? "call" : "calls"} so far.`,
  triedOn: (tried: number) =>
    `Tried on ${tried} ${tried === 1 ? "call" : "calls"} so far.`,
  // The lesson (owner's pick, 17 Nov 2026; redesign study §5 S3-S4). Our
  // screen words around his lesson, never shown as his.
  trackLabel: "Lesson parts",
  now: "अभी",
  pickHint: "कोई भी option चुनिए — हर एक पर Dipak की बात है।",
  seen: "देखा",
  seeOption: "Option देखें",
  why: "क्यों",
  allSeen: "तीनों नज़रिए देख लिए।",
  deepClose: "बंद करें",
  missionCommit: "मैं try करूँगा",
  missionOff: "Mission हटाएँ",
  missionOn: "Mission on",
  missionAfter: "आपकी अगली calls के बाद हम पूछेंगे।",
  lessonCount: (count: number) =>
    `${count} ${count === 1 ? "lesson" : "lessons"}`,
  missionFull:
    "3 missions पहले से active हैं। My missions में एक हटाकर इसे active करें।",
} as const;
