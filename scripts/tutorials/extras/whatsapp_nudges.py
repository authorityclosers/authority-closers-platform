# ruff: noqa: E501
# (message text is kept whole, one paragraph per line)
"""WhatsApp nudges for Sales X-Ray Play testers (day 1, 3, 7, 14) in English, Hindi and Marathi, with
Roman-script versions of the Hindi and Marathi. Writes .txt and .md per language (and a .docx through
docx_script-style python-docx when run under uv) into <out>. {name} is the only slot; never put a
tester's name or number in this file."""

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
OPT_IN = "https://play.google.com/apps/testing/com.authorityclosers.salesxray"
PLAY = "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray"

DAYS = [
    {
        "day": 1,
        "when": "The day they're added to the tester list",
        "videos": [
            "T1 Join the testers",
            "T2 Install from Google Play",
            "T3 Sign in inside the app",
        ],
        "en": f"""Hi {{name}}! 👋 Thank you for testing Sales X-Ray, our AI sales coach app.

Please do this today:
1. Open this link on your Android phone, signed in with the Google account we added: {OPT_IN}
2. Tap "Become a tester".
3. Install "Sales X-Ray: AI Sales Coach" from Google Play: {PLAY}
4. Open the app and tap "Continue with Google".

Had our older app from a download link? Open it, wait until it says "All changes saved", uninstall it, then install from Google Play. Your leads and calls stay safe.

The short videos with this message show each step.

Important 🙏 Please stay a tester and keep the app installed for 14 days. Google needs this before the app can go live for everyone.""",
        "hi": f"""नमस्ते {{name}}! 👋 Sales X-Ray, हमारा AI sales coach app, test करने के लिए धन्यवाद.

आज बस इतना कीजिए:
1. ये link अपने Android phone पे खोलिए, उसी Google account से जो हमने add किया है: {OPT_IN}
2. "Become a tester" दबाइए.
3. Google Play से "Sales X-Ray: AI Sales Coach" install कीजिए: {PLAY}
4. App खोलिए और "Continue with Google" दबाइए.

पहले download link वाला पुराना app था? उसे खोलिए, "All changes saved" आने तक रुकिए, फिर उसे uninstall कीजिए और Google Play से install कीजिए. आपके leads और calls safe रहते हैं.

इस message के साथ भेजे छोटे videos में हर step दिखाया है.

ज़रूरी 🙏 14 दिन तक tester बने रहिए और app phone पे रखिए. App सबके लिए live होने से पहले Google को यही चाहिए.""",
        "hi_latn": f"""Namaste {{name}}! 👋 Sales X-Ray, hamara AI sales coach app, test karne ke liye dhanyavaad.

Aaj bas itna kijiye:
1. Yeh link apne Android phone pe kholiye, usi Google account se jo humne add kiya hai: {OPT_IN}
2. "Become a tester" dabaiye.
3. Google Play se "Sales X-Ray: AI Sales Coach" install kijiye: {PLAY}
4. App kholiye aur "Continue with Google" dabaiye.

Pehle download link wala purana app tha? Use kholiye, "All changes saved" aane tak rukiye, phir use uninstall kijiye aur Google Play se install kijiye. Aapke leads aur calls safe rehte hain.

Is message ke saath bheje chhote videos mein har step dikhaya hai.

Zaroori 🙏 14 din tak tester bane rahiye aur app phone pe rakhiye. App sabke liye live hone se pehle Google ko yahi chahiye.""",
        "mr": f"""नमस्कार {{name}}! 👋 Sales X-Ray, आमचं AI sales coach app, test करत असल्याबद्दल धन्यवाद.

आज फक्त एवढं करा:
1. ही link तुमच्या Android phone वर उघडा, त्याच Google account ने जो आम्ही add केलाय: {OPT_IN}
2. "Become a tester" दाबा.
3. Google Play मधून "Sales X-Ray: AI Sales Coach" install करा: {PLAY}
4. App उघडा आणि "Continue with Google" दाबा.

आधी download link वाला जुना app होता? तो उघडा, "All changes saved" येईपर्यंत थांबा, मग तो uninstall करा आणि Google Play मधून install करा. तुमचे leads आणि calls safe राहतात.

या message सोबत पाठवलेल्या छोट्या videos मध्ये प्रत्येक step दाखवली आहे.

महत्त्वाचं 🙏 14 दिवस tester राहा आणि app phone वर ठेवा. App सगळ्यांसाठी live होण्याआधी Google ला हेच हवंय.""",
        "mr_latn": f"""Namaskar {{name}}! 👋 Sales X-Ray, aamcha AI sales coach app, test karat asalyabaddal dhanyavaad.

Aaj fakta evdha kara:
1. Hi link tumchya Android phone var ughda, tyach Google account ne jo aamhi add kelay: {OPT_IN}
2. "Become a tester" daba.
3. Google Play madhun "Sales X-Ray: AI Sales Coach" install kara: {PLAY}
4. App ughda aani "Continue with Google" daba.

Aadhi download link wala juna app hota? To ughda, "All changes saved" yeiparyant thamba, mag to uninstall kara aani Google Play madhun install kara. Tumche leads aani calls safe rahtat.

Ya message sobat pathavlelya chhotya videos madhye pratyek step dakhavli aahe.

Mahatvacha 🙏 14 divas tester raha aani app phone var theva. App saglyansaathi live honyaadhi Google la hech havay.""",
    },
    {
        "day": 3,
        "when": "Two days later",
        "videos": ["T4 First steps", "04 Call a lead and log how it went", "T5 If something hangs"],
        "en": """Hi {name}, how is Sales X-Ray going? 😊 Today, please try the basics:
1. Add 3 leads: tap +, then Add lead. A name and a number is enough.
2. Call one of them from the app. When you're back, answer "How did it go?".
3. Allow notifications, so you hear about new leads and replies.

Something stuck? Please don't reinstall. Go to Settings → Phone & alerts → Refresh app data. You stay signed in and nothing is lost.

Videos attached: first steps, and calling a lead.""",
        "hi": """नमस्ते {name}, Sales X-Ray कैसा चल रहा है? 😊 आज ये basics try कीजिए:
1. 3 leads add कीजिए: + दबाइए, फिर Add lead. बस नाम और number काफ़ी है.
2. उनमें से एक को app से call कीजिए. वापस आकर "How did it go?" का जवाब दीजिए.
3. Notifications allow कीजिए, ताकि नए leads और replies की ख़बर मिले.

कुछ अटक गया? Reinstall मत कीजिए. Settings → Phone & alerts → Refresh app data. आप signed in रहते हैं और कुछ नहीं खोता.

Videos साथ में हैं: पहले steps, और lead को call करना.""",
        "hi_latn": """Namaste {name}, Sales X-Ray kaisa chal raha hai? 😊 Aaj yeh basics try kijiye:
1. 3 leads add kijiye: + dabaiye, phir Add lead. Bas naam aur number kaafi hai.
2. Unmein se ek ko app se call kijiye. Wapas aakar "How did it go?" ka jawaab dijiye.
3. Notifications allow kijiye, taaki naye leads aur replies ki khabar mile.

Kuch atak gaya? Reinstall mat kijiye. Settings → Phone & alerts → Refresh app data. Aap signed in rehte hain aur kuch nahi khota.

Videos saath mein hain: pehle steps, aur lead ko call karna.""",
        "mr": """नमस्कार {name}, Sales X-Ray कसा चाललाय? 😊 आज हे basics try करा:
1. 3 leads add करा: + दाबा, मग Add lead. फक्त नाव आणि number पुरेसा आहे.
2. त्यातल्या एकाला app मधून call करा. परत आल्यावर "How did it go?" चं उत्तर द्या.
3. Notifications allow करा, म्हणजे नवीन leads आणि replies ची खबर मिळेल.

काही अडकलं? Reinstall करू नका. Settings → Phone & alerts → Refresh app data. तुम्ही signed in राहता आणि काहीच हरवत नाही.

Videos सोबत आहेत: पहिले steps, आणि lead ला call करणं.""",
        "mr_latn": """Namaskar {name}, Sales X-Ray kasa chalalay? 😊 Aaj he basics try kara:
1. 3 leads add kara: + daba, mag Add lead. Fakta naav aani number puresa aahe.
2. Tyatlya ekala app madhun call kara. Parat aalyavar "How did it go?" cha uttar dya.
3. Notifications allow kara, mhanje navin leads aani replies chi khabar milel.

Kahi adakla? Reinstall karu naka. Settings → Phone & alerts → Refresh app data. Tumhi signed in rahta aani kaahich harvat nahi.

Videos sobat aahet: pahile steps, aani lead la call karna.""",
    },
    {
        "day": 7,
        "when": "One week in",
        "videos": ["13 Lead stages and the Board", "16 Never lose a change"],
        "en": """Hi {name}! One week done, thank you 🙏 This week:
1. Open a call's Report: see your coaching score and the one thing to improve.
2. Try the Board in Leads: every lead in its stage, with one-tap Call.
3. Tell us one thing that felt wrong or confusing: in the app, tap You → Report a problem. A screenshot helps.

Please keep the app installed and stay a tester: 7 more days to go.""",
        "hi": """नमस्ते {name}! एक हफ़्ता पूरा, धन्यवाद 🙏 इस हफ़्ते:
1. किसी call की Report खोलिए: अपना coaching score और सुधारने वाली एक चीज़ देखिए.
2. Leads में Board try कीजिए: हर lead अपने stage में, one-tap Call के साथ.
3. एक चीज़ बताइए जो गलत या confusing लगी: app में You → Report a problem. Screenshot हो तो और अच्छा.

App phone पे रखिए और tester बने रहिए: बस 7 दिन और.""",
        "hi_latn": """Namaste {name}! Ek hafta poora, dhanyavaad 🙏 Is hafte:
1. Kisi call ki Report kholiye: apna coaching score aur sudharne wali ek cheez dekhiye.
2. Leads mein Board try kijiye: har lead apne stage mein, one-tap Call ke saath.
3. Ek cheez bataiye jo galat ya confusing lagi: app mein You → Report a problem. Screenshot ho toh aur achha.

App phone pe rakhiye aur tester bane rahiye: bas 7 din aur.""",
        "mr": """नमस्कार {name}! एक आठवडा पूर्ण, धन्यवाद 🙏 या आठवड्यात:
1. एखाद्या call ची Report उघडा: तुमचा coaching score आणि सुधारायची एक गोष्ट बघा.
2. Leads मध्ये Board try करा: प्रत्येक lead त्याच्या stage मध्ये, one-tap Call सकट.
3. एक गोष्ट सांगा जी चुकीची किंवा confusing वाटली: app मध्ये You → Report a problem. Screenshot असेल तर अजून छान.

App phone वर ठेवा आणि tester राहा: फक्त 7 दिवस अजून.""",
        "mr_latn": """Namaskar {name}! Ek athavda poorna, dhanyavaad 🙏 Ya athavdyat:
1. Ekhadya call chi Report ughda: tumcha coaching score aani sudharaychi ek goshta bagha.
2. Leads madhye Board try kara: pratyek lead tyachya stage madhye, one-tap Call sakat.
3. Ek goshta sanga ji chukichi kinva confusing vatli: app madhye You → Report a problem. Screenshot asel tar ajun chhan.

App phone var theva aani tester raha: fakta 7 divas ajun.""",
    },
    {
        "day": 14,
        "when": "Day 14",
        "videos": [],
        "en": """Hi {name}, that's 14 days with Sales X-Ray. Thank you so much! 🎉 You've helped us bring the app to Google Play for everyone.

One last request: reply here with one thing you liked, and one thing we should fix.

You can stay a tester to get new features first. Please keep the app; there's no need to uninstall.""",
        "hi": """नमस्ते {name}, Sales X-Ray के साथ 14 दिन पूरे. बहुत धन्यवाद! 🎉 आपकी वजह से app सबके लिए Google Play पे आ रहा है.

आख़िरी request: यहीं reply कीजिए, एक चीज़ जो अच्छी लगी, और एक जो हमें ठीक करनी चाहिए.

चाहें तो tester बने रहिए, नए features सबसे पहले मिलेंगे. App रखिए, uninstall करने की ज़रूरत नहीं.""",
        "hi_latn": """Namaste {name}, Sales X-Ray ke saath 14 din poore. Bahut dhanyavaad! 🎉 Aapki wajah se app sabke liye Google Play pe aa raha hai.

Aakhri request: yahin reply kijiye, ek cheez jo achhi lagi, aur ek jo humein theek karni chahiye.

Chahein toh tester bane rahiye, naye features sabse pehle milenge. App rakhiye, uninstall karne ki zaroorat nahi.""",
        "mr": """नमस्कार {name}, Sales X-Ray सोबत 14 दिवस पूर्ण. खूप खूप धन्यवाद! 🎉 तुमच्यामुळे app सगळ्यांसाठी Google Play वर येतोय.

शेवटची विनंती: इथेच reply करा, एक गोष्ट जी आवडली, आणि एक जी आम्ही ठीक करायला हवी.

हवं तर tester राहा, नवीन features सगळ्यात आधी मिळतील. App ठेवा, uninstall करायची गरज नाही.""",
        "mr_latn": """Namaskar {name}, Sales X-Ray sobat 14 divas poorna. Khup khup dhanyavaad! 🎉 Tumchyamule app saglyansaathi Google Play var yetoy.

Shevatchi vinanti: ithech reply kara, ek goshta ji aavadli, aani ek ji aamhi theek karayla havi.

Hava tar tester raha, navin features saglyat aadhi miltil. App theva, uninstall karaychi garaj nahi.""",
    },
]

LABEL = {"en": "English", "hi": "Hindi", "mr": "Marathi"}
OUT.mkdir(parents=True, exist_ok=True)
for lang in ("en", "hi", "mr"):
    parts = [
        f"Sales X-Ray testers: WhatsApp messages ({LABEL[lang]})",
        "",
        "Replace {name}. Send each message with the videos listed (the 9x16 files of this language).",
        "Play needs 12 or more testers opted in to Alpha for 14 days in a row.",
        "",
    ]
    for d in DAYS:
        parts += [
            f"=== Day {d['day']} · {d['when']}",
            "Attach: " + (", ".join(d["videos"]) or "no video"),
            "",
            d[lang],
            "",
        ]
        if lang != "en":
            parts += ["--- Roman script", "", d[f"{lang}_latn"], ""]
    text = "\n".join(parts)
    (OUT / f"whatsapp-testers-{lang}.txt").write_text(text, encoding="utf-8")
(OUT / "whatsapp-testers.json").write_text(
    json.dumps(DAYS, ensure_ascii=False, indent=1), encoding="utf-8"
)
print("written", sorted(p.name for p in OUT.iterdir()))
