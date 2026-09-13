type Copy = {
  title: string;
  intro: string;
  unavailable: string;
  noValues: string;
  level: string;
  pitch: string;
  inspectLevel: string;
  inspectPitch: string;
  chartRange: string;
  clockNote: string;
  channel: string;
  typicalLevel: string;
  typicalPitch: string;
  median: string;
  noCoverage: string;
  coverage: string;
  measurement: string;
  soundLevel: string;
  meaning: string;
  loading: string;
  error: string;
  retry: string;
};

export type MeasurementLanguage = "en" | "hi" | "mr" | "en-hi-mixed";

export const MEASUREMENT_COPY: Record<MeasurementLanguage, Copy> = {
  en: {
    title: "Sound of the recording",
    intro: "Explore saved sound level and pitch estimates",
    unavailable: "Not available",
    noValues:
      "No usable values for this measurement. Missing values are not zero.",
    level: "Recorded level",
    pitch: "Pitch estimate",
    inspectLevel: "Inspect recorded level over time",
    inspectPitch: "Inspect pitch estimate over time",
    chartRange:
      "{label} over the decoded recording. Displayed range {low} to {high} {unit}. Missing values remain gaps.",
    clockNote:
      "Move through the saved overview. This chart uses the decoded audio clock; it does not control playback.",
    channel: "Audio channel",
    typicalLevel: "Typical recorded level",
    typicalPitch: "Typical pitch estimate",
    median: "Median of usable audio windows",
    noCoverage: "Estimate coverage is unavailable",
    coverage: "Estimate available in {value}% of windows",
    measurement: "Audio measurement",
    soundLevel: "Sound level",
    meaning:
      "Audio channels are not speaker identities. These measurements describe the recording, not emotion, confidence or sales ability. Microphones and recording settings affect the values.",
    loading: "Loading saved measurements…",
    error:
      "Saved sound measurements are unavailable for this call. Your sales report is still available.",
    retry: "Try loading again",
  },
  hi: {
    title: "रिकॉर्डिंग की आवाज़",
    intro: "आवाज़ का स्तर और पिच के सहेजे गए अनुमान देखें",
    unavailable: "उपलब्ध नहीं",
    noValues:
      "इस माप के लिए उपयोगी आँकड़े नहीं मिले। गायब मानों का अर्थ शून्य नहीं है।",
    level: "रिकॉर्ड की गई आवाज़ का स्तर",
    pitch: "पिच का अनुमान",
    inspectLevel: "समय के साथ आवाज़ का स्तर देखें",
    inspectPitch: "समय के साथ पिच का अनुमान देखें",
    chartRange:
      "रिकॉर्डिंग में {label}। दिखाई गई सीमा {low} से {high} {unit} है। गायब मानों की जगह खाली है।",
    clockNote:
      "सहेजे गए आँकड़ों को समय के अनुसार देखें। इस चार्ट का समय डिकोड किए गए ऑडियो से आता है; यह प्लेबैक नहीं चलाता।",
    channel: "ऑडियो चैनल",
    typicalLevel: "आवाज़ का सामान्य रिकॉर्ड किया गया स्तर",
    typicalPitch: "पिच का सामान्य अनुमान",
    median: "उपयोगी ऑडियो खंडों का मध्य मान",
    noCoverage: "अनुमान की उपलब्धता का आँकड़ा नहीं है",
    coverage: "{value}% खंडों में अनुमान उपलब्ध है",
    measurement: "आवाज़ का माप",
    soundLevel: "आवाज़ का स्तर",
    meaning:
      "ऑडियो चैनल बोलने वाले की पहचान नहीं बताते। ये माप रिकॉर्डिंग के हैं, भावना, आत्मविश्वास या बिक्री क्षमता के नहीं। माइक्रोफ़ोन और रिकॉर्डिंग की सेटिंग से मान बदल सकते हैं।",
    loading: "सहेजे गए माप लोड हो रहे हैं…",
    error:
      "इस कॉल के सहेजे गए आवाज़ के माप उपलब्ध नहीं हैं। आपकी बिक्री रिपोर्ट उपलब्ध है।",
    retry: "फिर लोड करें",
  },
  mr: {
    title: "रेकॉर्डिंगचा आवाज",
    intro: "आवाजाची पातळी आणि पिचचे जतन केलेले अंदाज पाहा",
    unavailable: "उपलब्ध नाही",
    noValues:
      "या मोजमापासाठी वापरण्याजोगी मूल्ये नाहीत. नसलेली मूल्ये म्हणजे शून्य नाही.",
    level: "रेकॉर्ड केलेल्या आवाजाची पातळी",
    pitch: "पिचचा अंदाज",
    inspectLevel: "वेळेनुसार आवाजाची पातळी पाहा",
    inspectPitch: "वेळेनुसार पिचचा अंदाज पाहा",
    chartRange:
      "रेकॉर्डिंगमधील {label}. दाखवलेली मर्यादा {low} ते {high} {unit} आहे. नसलेल्या मूल्यांच्या जागा रिकाम्या आहेत.",
    clockNote:
      "जतन केलेली मोजमापे वेळेनुसार पाहा. चार्टची वेळ डिकोड केलेल्या ऑडिओवर आधारित आहे; तो प्लेबॅक नियंत्रित करत नाही.",
    channel: "ऑडिओ चॅनेल",
    typicalLevel: "आवाजाची सामान्य रेकॉर्ड केलेली पातळी",
    typicalPitch: "पिचचा सामान्य अंदाज",
    median: "वापरण्याजोग्या ऑडिओ भागांचे मध्यम मूल्य",
    noCoverage: "अंदाजाच्या उपलब्धतेचे मोजमाप नाही",
    coverage: "{value}% भागांमध्ये अंदाज उपलब्ध आहे",
    measurement: "आवाजाचे मोजमाप",
    soundLevel: "आवाजाची पातळी",
    meaning:
      "ऑडिओ चॅनेल म्हणजे वक्त्यांची ओळख नाही. ही मोजमापे रेकॉर्डिंगची आहेत, भावना, आत्मविश्वास किंवा विक्री कौशल्याची नाहीत. मायक्रोफोन आणि रेकॉर्डिंगच्या सेटिंगमुळे मूल्ये बदलतात.",
    loading: "जतन केलेली मोजमापे लोड होत आहेत…",
    error:
      "या कॉलची जतन केलेली आवाजाची मोजमापे उपलब्ध नाहीत. तुमचा विक्री अहवाल उपलब्ध आहे.",
    retry: "पुन्हा लोड करा",
  },
  "en-hi-mixed": {
    title: "Sound of the recording · रिकॉर्डिंग की आवाज़",
    intro: "Saved sound level और pitch estimates देखें",
    unavailable: "Not available · उपलब्ध नहीं",
    noValues:
      "इस measurement के usable values नहीं हैं। Missing values का मतलब zero नहीं है।",
    level: "Recorded level · आवाज़ का स्तर",
    pitch: "Pitch estimate · पिच का अनुमान",
    inspectLevel: "Recorded level समय के साथ देखें",
    inspectPitch: "Pitch estimate समय के साथ देखें",
    chartRange:
      "{label}: {low} से {high} {unit}। Missing values की जगह gaps हैं।",
    clockNote:
      "Saved overview समय के अनुसार देखें। Chart decoded audio की clock इस्तेमाल करता है; playback control नहीं करता।",
    channel: "Audio channel · ऑडियो चैनल",
    typicalLevel: "Typical recorded level · सामान्य स्तर",
    typicalPitch: "Typical pitch estimate · सामान्य पिच",
    median: "Usable audio windows का median",
    noCoverage: "Estimate coverage उपलब्ध नहीं है",
    coverage: "{value}% windows में estimate उपलब्ध है",
    measurement: "Audio measurement · आवाज़ का माप",
    soundLevel: "Sound level · आवाज़ का स्तर",
    meaning:
      "Audio channels speaker identity नहीं हैं। ये recording के measurements हैं, emotion, confidence या sales ability के scores नहीं। Microphone और recording settings values बदलते हैं।",
    loading: "Saved measurements लोड हो रहे हैं…",
    error:
      "इस call के saved sound measurements उपलब्ध नहीं हैं। Sales report उपलब्ध है।",
    retry: "Load again · फिर लोड करें",
  },
};
