export type ReportDisplayLanguage = "en" | "hi" | "mr" | "en-hi-mixed";

export type ReportUiCopy = {
  factorsLabel: string;
  factorsTitle: string;
  factorsNote: string;
  factorStatus: Record<string, string>;
  transcriptTitle: string;
  segmentsLabel: string;
  searchLabel: string;
  searchInputLabel: string;
  searchPlaceholder: string;
  speakerLabel: string;
  speakerFilterLabel: string;
  allSpeakers: string;
  unlabelledSpeaker: string;
  speakerNote: string;
  matchingSegments: string;
  showing: string;
  noMatches: string;
  loadMore: (count: number) => string;
};

const EN_COPY: ReportUiCopy = {
  factorsLabel: "Sales factors",
  factorsTitle: "Explore the sales factors",
  factorsNote:
    "Open a factor to read the draft observation. Evidence found does not mean a positive or negative score.",
  factorStatus: {
    observed: "Evidence found",
    insufficient_evidence: "Need more evidence",
    not_applicable: "Not relevant here",
    conflicted: "Mixed evidence",
    unknown: "Not assessed",
  },
  transcriptTitle: "Read full transcript",
  segmentsLabel: "segments",
  searchLabel: "Search transcript",
  searchInputLabel: "Search transcript phrases",
  searchPlaceholder: "Find a phrase",
  speakerLabel: "Speaker",
  speakerFilterLabel: "Filter transcript by speaker",
  allSpeakers: "All speakers",
  unlabelledSpeaker: "Unlabelled speaker",
  speakerNote:
    "Speaker labels come from the source and are unverified. Filter labels may be IDs rather than names.",
  matchingSegments: "matching segments",
  showing: "showing",
  noMatches: "No transcript segments match.",
  loadMore: (count) => `Load ${count} more`,
};

const HI_COPY: ReportUiCopy = {
  factorsLabel: "बिक्री के आयाम",
  factorsTitle: "बिक्री के आयाम देखें",
  factorsNote:
    "ड्राफ्ट निरीक्षण पढ़ने के लिए कोई आयाम खोलें। साक्ष्य मिलना सकारात्मक या नकारात्मक परिणाम नहीं बताता।",
  factorStatus: {
    observed: "साक्ष्य मिला",
    insufficient_evidence: "और साक्ष्य चाहिए",
    not_applicable: "यहाँ लागू नहीं",
    conflicted: "मिश्रित साक्ष्य",
    unknown: "आकलन नहीं हुआ",
  },
  transcriptTitle: "पूरा ट्रांसक्रिप्ट पढ़ें",
  segmentsLabel: "खंड",
  searchLabel: "ट्रांसक्रिप्ट खोजें",
  searchInputLabel: "ट्रांसक्रिप्ट में वाक्यांश खोजें",
  searchPlaceholder: "वाक्यांश खोजें",
  speakerLabel: "वक्ता",
  speakerFilterLabel: "वक्ता के अनुसार ट्रांसक्रिप्ट फ़िल्टर करें",
  allSpeakers: "सभी वक्ता",
  unlabelledSpeaker: "बिना लेबल का वक्ता",
  speakerNote:
    "वक्ता लेबल स्रोत से आते हैं और अप्रमाणित हैं। फ़िल्टर लेबल नामों की जगह ID हो सकते हैं।",
  matchingSegments: "मिलते हुए खंड",
  showing: "दिख रहे हैं",
  noMatches: "कोई ट्रांसक्रिप्ट खंड मेल नहीं खाता।",
  loadMore: (count) => `और ${count} दिखाएँ`,
};

const MR_COPY: ReportUiCopy = {
  factorsLabel: "विक्रीचे आयाम",
  factorsTitle: "विक्रीचे आयाम पाहा",
  factorsNote:
    "ड्राफ्ट निरीक्षण वाचण्यासाठी आयाम उघडा. पुरावा मिळाला म्हणजे सकारात्मक किंवा नकारात्मक परिणाम ठरत नाही.",
  factorStatus: {
    observed: "पुरावा मिळाला",
    insufficient_evidence: "अधिक पुरावा हवा",
    not_applicable: "इथे लागू नाही",
    conflicted: "मिश्र पुरावा",
    unknown: "मूल्यांकन झालेले नाही",
  },
  transcriptTitle: "संपूर्ण ट्रान्सक्रिप्ट वाचा",
  segmentsLabel: "खंड",
  searchLabel: "ट्रान्सक्रिप्ट शोधा",
  searchInputLabel: "ट्रान्सक्रिप्टमधील वाक्यांश शोधा",
  searchPlaceholder: "वाक्यांश शोधा",
  speakerLabel: "वक्ता",
  speakerFilterLabel: "वक्त्यानुसार ट्रान्सक्रिप्ट फिल्टर करा",
  allSpeakers: "सर्व वक्ते",
  unlabelledSpeaker: "लेबल नसलेला वक्ता",
  speakerNote:
    "वक्त्यांची लेबले स्रोतामधून आली आहेत आणि पडताळलेली नाहीत. फिल्टर लेबले नावांऐवजी ID असू शकतात.",
  matchingSegments: "जुळणारे खंड",
  showing: "दाखवत आहे",
  noMatches: "कोणतेही ट्रान्सक्रिप्ट खंड जुळले नाहीत.",
  loadMore: (count) => `आणखी ${count} दाखवा`,
};

const MIXED_COPY: ReportUiCopy = {
  factorsLabel: "Sales factors · बिक्री के आयाम",
  factorsTitle: "Explore sales factors · बिक्री के आयाम देखें",
  factorsNote:
    "Open a factor to read the draft observation · ड्राफ्ट निरीक्षण पढ़ें। Evidence found does not mean a positive or negative result · साक्ष्य मिलना सकारात्मक या नकारात्मक परिणाम नहीं बताता।",
  factorStatus: {
    observed: "Evidence found · साक्ष्य मिला",
    insufficient_evidence: "Need more evidence · और साक्ष्य चाहिए",
    not_applicable: "Not relevant here · यहाँ लागू नहीं",
    conflicted: "Mixed evidence · मिश्रित साक्ष्य",
    unknown: "Not assessed · आकलन नहीं हुआ",
  },
  transcriptTitle: "Read full transcript · पूरा ट्रांसक्रिप्ट पढ़ें",
  segmentsLabel: "segments · खंड",
  searchLabel: "Search transcript · ट्रांसक्रिप्ट खोजें",
  searchInputLabel:
    "Search transcript phrases · ट्रांसक्रिप्ट के वाक्यांश खोजें",
  searchPlaceholder: "Find a phrase · वाक्यांश खोजें",
  speakerLabel: "Speaker · वक्ता",
  speakerFilterLabel:
    "Filter transcript by speaker · वक्ता के अनुसार ट्रांसक्रिप्ट फ़िल्टर करें",
  allSpeakers: "All speakers · सभी वक्ता",
  unlabelledSpeaker: "Unlabelled speaker · बिना लेबल का वक्ता",
  speakerNote:
    "Speaker labels come from the source and are unverified · वक्ता लेबल स्रोत से आते हैं और अप्रमाणित हैं। Filter labels may be IDs rather than names · फ़िल्टर लेबल नामों की जगह ID हो सकते हैं।",
  matchingSegments: "matching segments · मिलते हुए खंड",
  showing: "showing · दिख रहे हैं",
  noMatches:
    "No transcript segments match · कोई ट्रांसक्रिप्ट खंड मेल नहीं खाता।",
  loadMore: (count) => `Load ${count} more · ${count} और दिखाएँ`,
};

const COPY_BY_LANGUAGE: Record<ReportDisplayLanguage, ReportUiCopy> = {
  en: EN_COPY,
  hi: HI_COPY,
  mr: MR_COPY,
  "en-hi-mixed": MIXED_COPY,
};

export function getReportUiCopy(
  language: ReportDisplayLanguage = "en",
): ReportUiCopy {
  return COPY_BY_LANGUAGE[language];
}
