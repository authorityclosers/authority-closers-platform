import type { MeasurementLanguage } from "./measurement-copy";

type SectionCopy = {
  heading: string;
  title: string;
  strengths: string;
  missed: string;
  improvements: string;
  objections: string;
  closing: string;
  verdict: string;
  empty: string;
  details: string;
  detailNote: string;
  another: string;
};

export const REPORT_SECTION_COPY: Record<MeasurementLanguage, SectionCopy> = {
  en: {
    heading: "YOUR SALES CALL REPORT",
    title: "What to take into your next call.",
    strengths: "What went well",
    missed: "What to improve",
    improvements: "What to say next",
    objections: "Questions and concerns",
    closing: "Next step",
    verdict: "Final takeaway",
    empty: "No supported finding was produced for this section.",
    details: "Report details",
    detailNote:
      "This draft uses evidence from the authorized recording. Speaker labels remain unverified.",
    another: "Analyze another call",
  },
  hi: {
    heading: "आपकी बिक्री कॉल की रिपोर्ट",
    title: "अगली कॉल में क्या अपनाएँ।",
    strengths: "क्या अच्छा रहा",
    missed: "कहाँ सुधार करना है",
    improvements: "आगे क्या कहें",
    objections: "सवाल और चिंताएँ",
    closing: "अगला कदम",
    verdict: "मुख्य सीख",
    empty: "इस हिस्से के लिए सबूत पर आधारित निष्कर्ष नहीं मिला।",
    details: "रिपोर्ट का विवरण",
    detailNote:
      "यह मसौदा अनुमति दी गई रिकॉर्डिंग के सबूत पर आधारित है। बोलने वालों की पहचान की पुष्टि नहीं हुई है।",
    another: "दूसरी कॉल का विश्लेषण करें",
  },
  mr: {
    heading: "तुमच्या विक्री कॉलचा अहवाल",
    title: "पुढच्या कॉलमध्ये काय वापराल.",
    strengths: "काय चांगले झाले",
    missed: "कुठे सुधारणा करावी",
    improvements: "पुढे काय बोलावे",
    objections: "प्रश्न आणि चिंता",
    closing: "पुढचा टप्पा",
    verdict: "मुख्य शिकवण",
    empty: "या भागासाठी पुराव्यावर आधारित निष्कर्ष मिळाला नाही.",
    details: "अहवालाचे तपशील",
    detailNote:
      "हा मसुदा परवानगी दिलेल्या रेकॉर्डिंगमधील पुराव्यावर आधारित आहे. वक्त्यांच्या ओळखीची पुष्टी झालेली नाही.",
    another: "दुसऱ्या कॉलचे विश्लेषण करा",
  },
  "en-hi-mixed": {
    heading: "YOUR SALES CALL REPORT · आपकी कॉल की रिपोर्ट",
    title: "Your next call · अगली कॉल में क्या अपनाएँ।",
    strengths: "What went well · क्या अच्छा रहा",
    missed: "What to improve · कहाँ सुधार करें",
    improvements: "What to say next · आगे क्या कहें",
    objections: "Questions and concerns · सवाल और चिंताएँ",
    closing: "Next step · अगला कदम",
    verdict: "Final takeaway · मुख्य सीख",
    empty: "इस section के लिए evidence-based finding नहीं मिली।",
    details: "Report details · रिपोर्ट का विवरण",
    detailNote:
      "यह draft authorized recording के evidence पर आधारित है। Speaker identities अभी verified नहीं हैं।",
    another: "Analyze another call · दूसरी कॉल चुनें",
  },
};
