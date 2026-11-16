/**
 * Ask Dipak's screen words, as Dipak's spec and sample have them (13 Nov
 * 2026), in his Hindi-English voice; nothing is translated or rewritten.
 * The sample's notes about itself ("this clickable sample", "demo
 * placeholders") are left out; the one line written here is NOT_READY, for a
 * question whose lesson isn't in the library yet (spec section 24).
 */
export const COPY = {
  title: "Ask Dipak",
  eyebrow: "DIPAK VISHWAKARMA · YOUR SALES MENTOR",
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
  missionTodo: "Relevant call में try करके complete mark करें।",
  missionDone: "Practice marked for this sample.",
  related: "इसके बाद क्या सीखें?",
  save: "Save lesson",
  unsave: "Remove saved lesson",
  markMission: "Mark mission as practised",
  undoMission: "Undo completed mission",
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
} as const;
