import type { MeasurementLanguage } from "./measurement-copy";

type NavigationCopy = {
  label: string;
  overview: string;
  transcript: string;
  moments: string;
  analysis: string;
  coaching: string;
  factors: string;
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
    transcript: "Transcript",
    moments: "Call moments",
    analysis: "Analysis",
    coaching: "Coaching",
    factors: "Sales factors",
    sound: "Sound",
    next: "Next steps",
  },
  hi: {
    label: "अपनी रिपोर्ट देखें",
    overview: "सारांश",
    transcript: "पूरी बातचीत",
    moments: "कॉल के पल",
    analysis: "विश्लेषण",
    coaching: "कोचिंग",
    factors: "बिक्री के पहलू",
    sound: "आवाज़",
    next: "अगले कदम",
  },
  mr: {
    label: "तुमचा अहवाल पाहा",
    overview: "सारांश",
    transcript: "संपूर्ण संभाषण",
    moments: "कॉलमधील क्षण",
    analysis: "विश्लेषण",
    coaching: "कोचिंग",
    factors: "विक्रीचे पैलू",
    sound: "आवाज",
    next: "पुढचे टप्पे",
  },
  "en-hi-mixed": {
    label: "Explore report · रिपोर्ट देखें",
    overview: "Overview · सारांश",
    transcript: "Transcript · पूरी बातचीत",
    moments: "Call moments · कॉल के पल",
    analysis: "Analysis · विश्लेषण",
    coaching: "Coaching · कोचिंग",
    factors: "Sales factors · बिक्री के पहलू",
    sound: "Sound · आवाज़",
    next: "Next steps · अगले कदम",
  },
};
