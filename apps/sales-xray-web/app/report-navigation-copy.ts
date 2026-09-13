import type { MeasurementLanguage } from "./measurement-copy";

type NavigationCopy = {
  label: string;
  overview: string;
  factors: string;
  moments: string;
  transcript: string;
  sound: string;
  next: string;
};

export const REPORT_NAVIGATION_COPY: Record<
  MeasurementLanguage,
  NavigationCopy
> = {
  en: {
    label: "Explore your report",
    overview: "Overview",
    factors: "Sales factors",
    moments: "Call moments",
    transcript: "Transcript",
    sound: "Sound",
    next: "Next steps",
  },
  hi: {
    label: "अपनी रिपोर्ट देखें",
    overview: "सारांश",
    factors: "बिक्री के पहलू",
    moments: "कॉल के पल",
    transcript: "पूरी बातचीत",
    sound: "आवाज़",
    next: "अगले कदम",
  },
  mr: {
    label: "तुमचा अहवाल पाहा",
    overview: "सारांश",
    factors: "विक्रीचे पैलू",
    moments: "कॉलमधील क्षण",
    transcript: "संपूर्ण संभाषण",
    sound: "आवाज",
    next: "पुढचे टप्पे",
  },
  "en-hi-mixed": {
    label: "Explore report · रिपोर्ट देखें",
    overview: "Overview · सारांश",
    factors: "Sales factors · बिक्री के पहलू",
    moments: "Call moments · कॉल के पल",
    transcript: "Transcript · पूरी बातचीत",
    sound: "Sound · आवाज़",
    next: "Next steps · अगले कदम",
  },
};
