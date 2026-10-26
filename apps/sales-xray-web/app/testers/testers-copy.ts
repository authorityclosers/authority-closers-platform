/**
 * The /testers page's words in English, Hindi and Marathi (tester programme
 * kit, 26 Oct 2026: notes 01 and 02 §6). Every language has every line, so
 * the switcher changes the whole page. The Hindi and Marathi drafts covered
 * the title and the steps; the other lines follow them, for a native speaker
 * to read before the programme starts. No prices on this page.
 */
export type Lang = "en" | "hi" | "mr";

export const LANGS: readonly { key: Lang; name: string }[] = [
  { key: "en", name: "English" },
  { key: "hi", name: "हिन्दी" },
  { key: "mr", name: "मराठी" },
];

export type TestersCopy = Readonly<{
  title: string;
  lead: string;
  groupTitle: string;
  groupLine: string;
  groupButton: string;
  gmailTitle: string;
  gmailLine: string;
  gmailButton: string;
  gmailMessage: string;
  optInTitle: string;
  optInLine: string;
  optInButton: string;
  installTitle: string;
  installLine: string;
  installButton: string;
  done: string;
  stayTitle: string;
  stayText: string;
  rewardsTitle: string;
  rewardsText: string;
  stuckTitle: string;
  stuck: readonly { q: string; a: string }[];
  stillStuck: string;
  askButton: string;
  footer: string;
  privacy: string;
  language: string;
}>;

export const COPY: Record<Lang, TestersCopy> = {
  en: {
    title: "Help us test Sales X-Ray",
    lead: "Three steps, five minutes. Use the same Google account (the one on your phone) for every step.",
    groupTitle: "Join the tester group",
    groupLine: "One tap with your Gmail. You won’t get emails from it.",
    groupButton: "Join the group",
    gmailTitle: "Send us your Gmail",
    gmailLine:
      "Use the Gmail that’s on your phone. We’ll add you and reply within a few hours.",
    gmailButton: "Send my Gmail on WhatsApp",
    gmailMessage: "Please add me as a Sales X-Ray tester. My Gmail: ",
    optInTitle: "Turn on testing in Google Play",
    optInLine: "Tap “Become a tester” on the page that opens.",
    optInButton: "Become a tester",
    installTitle: "Install and sign in",
    installLine:
      "Install Sales X-Ray from Google Play, open it and sign in with Google. If Play doesn’t show it yet, wait an hour and try again.",
    installButton: "Open in Google Play",
    done: "Done",
    stayTitle: "Stay with us for 14 days",
    stayText:
      "Google counts testers who stay in for 14 days in a row. Please don’t leave the group or the test, even if you don’t use the app every day.",
    rewardsTitle: "Rewards for real bugs",
    rewardsText:
      "Report bugs from the app: shake the phone, or press Ctrl B on a computer. Each real bug we accept is rewarded, paid every Friday by UPI. The full rules are in the tester group.",
    stuckTitle: "Stuck?",
    stuck: [
      {
        q: "Play says “not available”",
        a: "Check your photo at the top of Play. It must be the Gmail you joined with.",
      },
      {
        q: "“Item not found” right after step 2",
        a: "It can take a few hours. Try again later.",
      },
      {
        q: "“Your device isn’t compatible”",
        a: "Send us your phone’s brand, model and Android version.",
      },
      {
        q: "“App not installed”",
        a: "Remove the old Sales X-Ray app first, then install from Play.",
      },
      {
        q: "Joined with the wrong Gmail",
        a: "Join again with the right one; you can leave the other.",
      },
    ],
    stillStuck: "Still stuck?",
    askButton: "Ask on WhatsApp",
    footer:
      "Sales X-Ray is a sales app for teams. Testers use their own phone; we never see your contacts or calls unless you use them in the app.",
    privacy: "Privacy",
    language: "Language",
  },
  hi: {
    title: "Sales X-Ray टेस्ट करने में हमारी मदद करें",
    lead: "तीन कदम, पाँच मिनट। हर कदम पर वही Google अकाउंट इस्तेमाल करें (जो आपके फ़ोन में है)।",
    groupTitle: "टेस्टर ग्रुप जॉइन करें",
    groupLine: "अपने Gmail से एक टैप। इससे आपको ईमेल नहीं आएँगे।",
    groupButton: "ग्रुप जॉइन करें",
    gmailTitle: "हमें अपना Gmail भेजें",
    gmailLine:
      "वही Gmail भेजें जो आपके फ़ोन में है। हम आपको जोड़कर कुछ घंटों में जवाब देंगे।",
    gmailButton: "WhatsApp पर मेरा Gmail भेजें",
    gmailMessage:
      "कृपया मुझे Sales X-Ray टेस्टर के रूप में जोड़ें। मेरा Gmail: ",
    optInTitle: "Google Play में टेस्टिंग चालू करें",
    optInLine: "खुले पेज पर “Become a tester” दबाएँ।",
    optInButton: "Become a tester",
    installTitle: "इंस्टॉल करें और साइन इन करें",
    installLine:
      "Google Play से Sales X-Ray इंस्टॉल करें, खोलें और Google से साइन इन करें। अगर Play में अभी न दिखे, तो एक घंटे बाद फिर कोशिश करें।",
    installButton: "Google Play में खोलें",
    done: "हो गया",
    stayTitle: "14 दिन जुड़े रहें",
    stayText:
      "Google उन्हीं टेस्टरों को गिनता है जो लगातार 14 दिन जुड़े रहते हैं। कृपया ग्रुप या टेस्ट न छोड़ें, भले ही आप हर दिन ऐप इस्तेमाल न करें।",
    rewardsTitle: "असली बग के लिए इनाम",
    rewardsText:
      "ऐप से बग रिपोर्ट करें: फ़ोन हिलाएँ, या कंप्यूटर पर Ctrl B दबाएँ। हर मंज़ूर बग पर इनाम, हर शुक्रवार UPI से। पूरे नियम टेस्टर ग्रुप में हैं।",
    stuckTitle: "अटक गए?",
    stuck: [
      {
        q: "Play में “not available” दिखे",
        a: "Play में ऊपर अपनी फ़ोटो देखें। वह वही Gmail होना चाहिए जिससे आपने जॉइन किया।",
      },
      {
        q: "कदम 2 के तुरंत बाद “Item not found”",
        a: "इसमें कुछ घंटे लग सकते हैं। बाद में फिर कोशिश करें।",
      },
      {
        q: "“Your device isn’t compatible”",
        a: "हमें अपने फ़ोन का ब्रांड, मॉडल और Android वर्ज़न भेजें।",
      },
      {
        q: "“App not installed”",
        a: "पहले पुराना Sales X-Ray ऐप हटाएँ, फिर Play से इंस्टॉल करें।",
      },
      {
        q: "गलत Gmail से जॉइन कर लिया",
        a: "सही Gmail से फिर जॉइन करें; दूसरा छोड़ सकते हैं।",
      },
    ],
    stillStuck: "अब भी अटके हैं?",
    askButton: "WhatsApp पर पूछें",
    footer:
      "Sales X-Ray टीमों के लिए एक सेल्स ऐप है। टेस्टर अपना फ़ोन इस्तेमाल करते हैं; जब तक आप ऐप में इस्तेमाल न करें, हम आपके कॉन्टैक्ट या कॉल नहीं देखते।",
    privacy: "प्राइवेसी",
    language: "भाषा",
  },
  mr: {
    title: "Sales X-Ray टेस्ट करायला आम्हाला मदत करा",
    lead: "तीन पायऱ्या, पाच मिनिटं. प्रत्येक पायरीवर तेच Google अकाउंट वापरा (जे तुमच्या फोनमध्ये आहे).",
    groupTitle: "टेस्टर ग्रुप जॉइन करा",
    groupLine: "तुमच्या Gmail ने एक टॅप. यातून तुम्हाला ईमेल येणार नाहीत.",
    groupButton: "ग्रुप जॉइन करा",
    gmailTitle: "आम्हाला तुमचं Gmail पाठवा",
    gmailLine:
      "तुमच्या फोनमधलंच Gmail पाठवा. आम्ही तुम्हाला जोडून काही तासांत उत्तर देऊ.",
    gmailButton: "WhatsApp वर माझं Gmail पाठवा",
    gmailMessage: "कृपया मला Sales X-Ray टेस्टर म्हणून जोडा. माझं Gmail: ",
    optInTitle: "Google Play मध्ये टेस्टिंग सुरू करा",
    optInLine: "उघडलेल्या पानावर “Become a tester” दाबा.",
    optInButton: "Become a tester",
    installTitle: "इन्स्टॉल करा आणि साइन इन करा",
    installLine:
      "Google Play वरून Sales X-Ray इन्स्टॉल करा, उघडा आणि Google ने साइन इन करा. Play मध्ये अजून दिसत नसेल, तर एक तासाने पुन्हा प्रयत्न करा.",
    installButton: "Google Play मध्ये उघडा",
    done: "झालं",
    stayTitle: "14 दिवस सोबत राहा",
    stayText:
      "सलग 14 दिवस सोबत राहणाऱ्या टेस्टरनाच Google मोजतं. रोज ॲप वापरलं नाहीत तरी कृपया ग्रुप किंवा टेस्ट सोडू नका.",
    rewardsTitle: "खऱ्या बगसाठी बक्षीस",
    rewardsText:
      "ॲपमधून बग रिपोर्ट करा: फोन हलवा, किंवा कॉम्प्युटरवर Ctrl B दाबा. प्रत्येक मंजूर बगसाठी बक्षीस, दर शुक्रवारी UPI ने. सगळे नियम टेस्टर ग्रुपमध्ये आहेत.",
    stuckTitle: "अडकलात?",
    stuck: [
      {
        q: "Play मध्ये “not available” दिसतंय",
        a: "Play मध्ये वर तुमचा फोटो तपासा. ज्या Gmail ने जॉइन केलं, तेच असायला हवं.",
      },
      {
        q: "पायरी 2 नंतर लगेच “Item not found”",
        a: "याला काही तास लागू शकतात. नंतर पुन्हा प्रयत्न करा.",
      },
      {
        q: "“Your device isn’t compatible”",
        a: "आम्हाला तुमच्या फोनचा ब्रँड, मॉडेल आणि Android व्हर्जन पाठवा.",
      },
      {
        q: "“App not installed”",
        a: "आधी जुनं Sales X-Ray ॲप काढून टाका, मग Play वरून इन्स्टॉल करा.",
      },
      {
        q: "चुकीच्या Gmail ने जॉइन केलं",
        a: "योग्य Gmail ने पुन्हा जॉइन करा; दुसरं सोडू शकता.",
      },
    ],
    stillStuck: "अजूनही अडकलात?",
    askButton: "WhatsApp वर विचारा",
    footer:
      "Sales X-Ray हे टीमसाठी सेल्स ॲप आहे. टेस्टर स्वतःचा फोन वापरतात; तुम्ही ॲपमध्ये वापरल्याशिवाय आम्ही तुमचे कॉन्टॅक्ट किंवा कॉल पाहत नाही.",
    privacy: "प्रायव्हसी",
    language: "भाषा",
  },
};
