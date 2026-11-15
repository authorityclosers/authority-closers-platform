# ruff: noqa: E501, RUF001 - the scripts are dialogue, one spoken line per line
"""The release-call library: 15 fictional phone calls, sales and not sales, with what must happen.

Owner, 13 Nov 2026: "That setup is also talking from the perspective of different types: owner,
buyer, seller… sometimes the call is not even sales. How is that detected, how is it analysed by
our servers?" Every person, company and place here is made up; no phone number is spoken.

Each scenario is a script (who says what: S = our seller, the app's user; P = the other person;
I = a recorded voice, an IVR or the network) and an expectation:

- ``outcome``: what the server must do with the recording. ``report`` (a full report),
  ``short_call`` (held: transcript and lead details only), ``no_conversation`` (held: nothing to
  analyse), ``held`` (either hold) or ``any`` (a report or a hold).
- ``sales``: whether the call is a sales conversation. The checker compares it with what the
  server decided (a hold, or the report's stored call purpose).

The format is the simulation lab's (``scripts/simulation/scenarios.py``), so
``scripts/simulation/synth.py`` renders the audio unchanged. ``python scenarios.py build <dir>``
writes one JSON file per scenario.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "ac.call-testing.scenario/1"
LIBRARY_VERSION = "1"

OUTCOMES = ("report", "short_call", "no_conversation", "held", "any")
PURPOSES = ("sales", "support", "onboarding", "internal", "personal", "unclear")

# Piper voices in the simulation lab (ac:/home/acdev/simlab/voices). The two sides always differ.
EN_SELLER_M, EN_SELLER_F = "en_US-ryan-medium", "en_US-kristin-medium"
EN_P_F, EN_P_M, EN_P_M2 = "en_US-amy-medium", "en_GB-alan-medium", "en_US-joe-medium"
HI_M, HI_F, HI_M2 = "hi_IN-pratham-medium", "hi_IN-priyamvada-medium", "hi_IN-rohan-medium"
MR = "mr_IN-google-medium"
RECORDED = "en_US-hfc_female-medium"

# After every Play release: two sales reports in two languages, a personal call (detection) and
# dead air (a hold that costs almost nothing).
SETS = {
    "smoke": ("R01", "R06", "R10", "R14"),
}


def _turns(text: str) -> list[list[str]]:
    """'S: hello\\nP: hi' -> [['S', 'hello'], ['P', 'hi']]."""
    out: list[list[str]] = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        who, _, said = line.partition(":")
        if who not in {"S", "P", "I"} or not said.strip():
            raise ValueError(f"bad line: {line}")
        out.append([who, said.strip()])
    return out


def scenario(
    sid: str,
    title: str,
    *,
    persona: str,
    language: str,
    voices: dict[str, Any],
    script: str,
    expect: dict[str, Any],
    audio: dict[str, Any] | None = None,
    pad_to_seconds: float | None = None,
    covers: list[str],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "id": sid,
        "title": title,
        "persona": persona,
        "language": language,
        "voices": voices,
        "turns": _turns(script),
        "expect": expect,
        # The Xiaomi recorder writes MP3; synth.py band-limits the far side like a phone line.
        "audio": {"format": "mp3", "rate": 16000, "channels": 1, **(audio or {})},
        "pad_to_seconds": pad_to_seconds,
        "covers": covers,
    }


def library() -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    add = calls.append

    # ---- Sales ----------------------------------------------------------------------------

    add(
        scenario(
            "R01",
            "Builder's executive to a first-time buyer, site visit booked",
            persona="seller: builder's sales executive; other side: first-time home buyer (inbound form)",
            language="english",
            voices={"S": EN_SELLER_M, "P": EN_P_F},
            script="""
S: Hello, am I speaking with Neha? This is Karan from Sunleaf Homes. You filled in our form yesterday about a two bedroom flat. Is this a good time for a few minutes?
P: Yes, hi Karan. I have about five minutes. I'm just leaving the office.
S: Thank you, I'll keep it quick. May I ask what made you start looking right now?
P: We're renting at the moment, and the rent went up again this year. My husband and I feel it's time to buy our own place.
S: That makes sense. And when would you ideally like to move in?
P: By the end of next year. We're not in a hurry, but we don't want to wait for three years either.
S: Understood. The project you saw online has two towers. Tower A is ready by next December, Tower B a year later. So Tower A would suit you.
P: Okay. What about the price? The website said seventy-two lakh onwards.
S: Yes, seventy-two is for the lower floors. Higher floors with the park view are around seventy-six. What budget have the two of you agreed on?
P: We were thinking seventy, all in. Seventy-two is already a stretch for us.
S: I understand. We have a bank partner who can do the home loan paperwork, and this month the registration charges are on us. That brings it close to your seventy.
P: That helps. But my real worry is the area. My husband works on the other side of the city and the traffic is terrible.
S: That's a fair concern. The new metro line has a station about ten minutes' walk away, and it opens next year. Would it help if both of you saw the place and the route yourselves?
P: Yes, he won't decide without seeing it.
S: Then let's plan a site visit for both of you. Does Sunday morning work?
P: Sunday at eleven would be fine.
S: Sunday at eleven, perfect. I'll send you the location and the Tower A floor plans on WhatsApp right after this call.
P: Okay, thank you Karan.
S: Thank you Neha. See you and your husband on Sunday at eleven.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "english", "buyer", "inbound", "site_visit"],
        )
    )

    add(
        scenario(
            "R02",
            "Broker to a flat owner who wants to sell, Hinglish",
            persona="seller: property broker; other side: flat owner selling (listing mandate)",
            language="hinglish",
            voices={"S": HI_M2, "P": HI_M},
            script="""
S: हेलो, अनिल जोशी जी बोल रहे हैं? मैं विक्रम, ब्लूडोर प्रॉपर्टीज़ से बोल रहा हूँ. आपने हमारे पोर्टल पर अपना टू बीएचके सेल के लिए डाला था.
P: हाँ जी, बोलिए. मैंने ही डाला था. तीन हफ्ते हो गए, अभी तक कोई ढंग का खरीदार नहीं आया.
S: समझ सकता हूँ सर. फ्लैट कौन से फ्लोर पर है, और कितना पुराना है?
P: चौथा फ्लोर है, बिल्डिंग आठ साल पुरानी है. पार्किंग भी है, लिफ्ट भी है.
S: बढ़िया. और आप कितने में बेचना चाहते हैं?
P: मुझे पचासी लाख चाहिए. उससे कम नहीं.
S: सर, उस एरिया में पिछले छह महीने में ऐसे फ्लैट अठहत्तर से बयासी लाख में गए हैं. पचासी थोड़ा ऊपर है.
P: लेकिन मेरा फ्लैट कॉर्नर का है, दोनों तरफ से हवा आती है.
S: बिल्कुल, ये प्लस पॉइंट है. इसीलिए मैं कह रहा हूँ, तिरासी पर लिस्ट करें, तो दो तीन हफ्ते में सीरियस खरीदार आ जाएँगे.
P: और आपका कमीशन कितना होगा?
S: एक परसेंट सर, डील होने पर ही. फोटो, वीडियो और सारे विज़िट हम खुद संभालेंगे, आपको बार बार घर पर रहने की ज़रूरत नहीं.
P: पिछले ब्रोकर ने भी यही कहा था, फिर कोई नहीं आया.
S: इसीलिए मैं पहले आपको हमारे पिछले तीन सौदों की डिटेल भेजूँगा, उसी सोसाइटी के पास वाले. फिर आप तय कीजिए.
P: ठीक है, भेजिए. और फोटो के लिए कब आएँगे?
S: शनिवार सुबह दस बजे चलेगा? रोशनी अच्छी रहती है उस वक्त.
P: हाँ, शनिवार दस बजे ठीक है.
S: बहुत बढ़िया. मैं आज शाम तक डील्स की डिटेल व्हाट्सएप पर भेज देता हूँ. धन्यवाद जोशी जी.
P: ठीक है, नमस्ते.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "hinglish", "owner", "listing"],
        )
    )

    add(
        scenario(
            "R03",
            "Broker to an investor, hard price negotiation",
            persona="seller: property broker; other side: investor buying to rent out",
            language="english",
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
S: Good afternoon, Mr. Mehta. This is Pooja from Greenfield Realty. We spoke last week about the one bedroom units near the new IT park.
P: Yes, I remember. I told you I'm only interested if the rental numbers make sense.
S: Exactly, so I've worked them out. The unit is forty-eight lakh. Similar flats in the next building rent for about eighteen thousand a month.
P: Eighteen thousand on forty-eight lakh is not even five percent. I can get more from a fixed deposit.
S: That's true for the rent alone. But the area has gone up about nine percent a year for three years, because of the IT park.
P: Past growth is not a promise. And I've heard the builder delayed his last project.
S: He did, by eight months, on a project in another city. This tower is already at the twelfth floor, and the possession date is in the agreement with a penalty clause.
P: Even so, forty-eight is too much. I'll do forty-two, and I can pay quickly.
S: Forty-two is below what the builder has accepted this quarter. The lowest I've seen go through is forty-five and a half, for a lower floor.
P: Then get me the lower floor at forty-four.
S: I can't promise forty-four. What I can do is ask for forty-five with the parking included, which is usually two lakh extra.
P: Hmm. Forty-five with parking. And who handles the tenant?
S: We have a rental desk. We find the tenant and do the agreement for one month's rent as our fee.
P: Fine. Ask the builder about forty-five with parking and call me back. Not before Thursday, I'm travelling.
S: I'll speak to the builder tomorrow and call you on Thursday afternoon with his answer, along with the rental agreement sample.
P: Thursday afternoon. Okay.
S: Thank you, Mr. Mehta. Talk on Thursday.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "english", "buyer", "investor", "negotiation", "objections"],
        )
    )

    add(
        scenario(
            "R04",
            "Builder's executive to an NRI buyer, video tour booked",
            persona="seller: builder's sales executive; other side: NRI buyer abroad",
            language="english",
            voices={"S": EN_SELLER_M, "P": EN_P_M2},
            script="""
S: Hello, is this Mr. Rao? This is Arjun from Sunleaf Homes in Pune. You asked about a three bedroom flat on our website.
P: Yes, this is Suresh Rao. I'm calling from Dubai, so the timing is a bit tight. Go ahead.
S: Thank you, I'll be brief. Is the flat for your family to live in, or as an investment?
P: For my parents to live in now. My wife and I will move back in about five years.
S: That helps. Your parents would want a lower floor and a lift that works during power cuts, I imagine.
P: Exactly. My father has knee trouble. And they need a hospital close by.
S: There's a large hospital about two kilometres away, and every tower has power backup for the lifts. Second floor units are still available.
P: What's the price for the second floor, three bedroom?
S: One crore twelve lakh, including parking. For NRI buyers we can also do the paperwork through a power of attorney, so you needn't fly down.
P: The price is fine if the quality is good. But I can't see it from here, and my parents can't judge the construction.
S: We can do a live video tour. I walk through the sample flat and the actual second floor unit, and you ask anything you like.
P: That would be useful. My brother in Pune could also visit in person afterwards.
S: Perfect. When is good for the video tour, Dubai time?
P: Saturday, ten in the morning Dubai time.
S: That's eleven thirty in India. Saturday, eleven thirty India time, on a WhatsApp video call. I'll also email you the floor plan and the payment schedule today.
P: Good. Send everything to my email.
S: I will. Thank you, Mr. Rao. Talk on Saturday.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "english", "buyer", "nri", "video_tour"],
        )
    )

    add(
        scenario(
            "R05",
            "Cold call turned down politely",
            persona="seller: builder's sales executive; other side: cold prospect, not interested",
            language="english",
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
S: Hello, good evening. This is Ritu from Sunleaf Homes. Am I speaking with Mr. Iyer?
P: Yes. Who gave you my number?
S: You were on a list of visitors to a property fair last year. I'm calling about our new project with two and three bedroom flats.
P: I visited that fair for my cousin, not for myself. I'm not looking to buy anything.
S: I understand. May I ask, are you renting at the moment, or do you already own a home?
P: I own my flat. I've no plans to buy another one. Interest rates are too high anyway.
S: That's fair. Some of our buyers are investors who rent the flat out. Would that interest you at all?
P: No. I really don't have the time or the money for that right now.
S: No problem at all. Should I check with you again in six months, or would you prefer I don't call?
P: Please don't call again. Take my number off your list.
S: Of course. I'll remove your number today. Sorry to have disturbed you, and thank you for your time.
P: Okay. Bye.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "english", "cold", "rejected"],
        )
    )

    add(
        scenario(
            "R06",
            "Marathi-English call with a Pune family, visit on Saturday",
            persona="seller: builder's sales executive; other side: family buying a 2BHK",
            language="marathi-english",
            voices={"S": {"model": MR, "speaker": 1}, "P": {"model": MR, "speaker": 6}},
            script="""
S: नमस्कार, मी प्रिया बोलते, सनलीफ होम्स मधून. तुम्ही टू बीएचके साठी चौकशी केली होती, बरोबर?
P: हो, मी संदीप पाटील. बोला, पाच मिनिटं आहेत.
S: धन्यवाद. घर स्वतः राहण्यासाठी हवं आहे का?
P: हो. आम्ही चौघे आहोत, मी, बायको आणि दोन मुलं. सध्या भाड्याच्या घरात राहतो.
S: छान. मुलांची शाळा जवळ असणं महत्त्वाचं असेल ना?
P: हो, ते सगळ्यात महत्त्वाचं आहे. आणि बायकोचं ऑफिस हिंजवडी ला आहे.
S: आमचा प्रोजेक्ट हिंजवडी पासून पंधरा मिनिटांवर आहे. शाळा अगदी पाच मिनिटांवर आहे.
P: किंमत किती आहे?
S: टू बीएचके पासष्ट लाखापासून सुरू होतो. पार्किंग सहित.
P: आमचं बजेट साठ लाख आहे. पासष्ट जरा जास्त होतंय.
S: समजलं. या महिन्यात स्टॅम्प ड्युटी वर ऑफर आहे, आणि बँक लोन ची प्रोसेस आम्ही करून देतो. त्यामुळे फरक कमी होतो.
P: लोन किती वर्षांचं मिळेल? आणि EMI किती येईल साधारण?
S: वीस वर्षांचं लोन मिळू शकतं. पन्नास लाखाच्या लोन ला साधारण बेचाळीस हजार EMI येईल. तुमच्या पगारावर बँक नक्की सांगेल.
P: ठीक आहे. आणि पझेशन कधी मिळेल? आम्हाला पुढच्या जून पर्यंत शिफ्ट व्हायचं आहे, मुलांची शाळा सुरू होण्याआधी.
S: बी विंग चं पझेशन एप्रिल मध्ये आहे. म्हणजे जून च्या आधी तुम्ही आरामात शिफ्ट होऊ शकता.
P: बघू. पण आधी प्रत्यक्ष घर बघायचं आहे. बायकोला पण यावं लागेल.
S: नक्की. शनिवारी साईट व्हिजिट ठेवूया का? सकाळी अकरा वाजता?
P: शनिवारी अकरा चालेल. आम्ही दोघं येऊ.
S: ठीक आहे. मी लोकेशन आणि फ्लोअर प्लॅन व्हॉट्सॲप वर पाठवते. धन्यवाद संदीप जी.
P: धन्यवाद, शनिवारी भेटू.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "marathi_english", "buyer", "family", "site_visit"],
        )
    )

    add(
        scenario(
            "R07",
            "Education counsellor to a student's father, Hinglish",
            persona="seller: course counsellor; other side: parent paying the fee (not real estate)",
            language="hinglish",
            voices={"S": HI_F, "P": HI_M},
            script="""
S: नमस्ते, क्या मैं राजेश गुप्ता जी से बात कर रही हूँ? मैं स्नेहा, ब्राइटपाथ एकेडमी से. आपके बेटे ने डेटा एनालिटिक्स कोर्स के लिए फॉर्म भरा था.
P: हाँ, मैं उसका पापा बोल रहा हूँ. उसने बताया था. पहले ये बताइए, कोर्स कितने महीने का है?
S: छह महीने का है सर. हफ्ते में चार दिन ऑनलाइन क्लास, और आखिरी महीने में एक लाइव प्रोजेक्ट.
P: और फीस कितनी है?
S: पूरी फीस एक लाख बीस हज़ार है. लेकिन हम ईएमआई भी देते हैं, दस हज़ार महीना, बिना ब्याज के.
P: एक लाख बीस बहुत ज़्यादा है. यूट्यूब पर तो ये सब फ्री में मिल जाता है.
S: सही बात है सर, जानकारी फ्री में मिल जाती है. लेकिन हमारे यहाँ हर हफ्ते मेंटर से एक घंटा होता है, और प्लेसमेंट टीम इंटरव्यू की तैयारी करवाती है.
P: नौकरी की गारंटी देते हैं?
S: गारंटी नहीं देते सर, ये मैं साफ बता दूँ. पिछले बैच में सत्तर में से बावन बच्चों की नौकरी लगी.
P: ठीक है. पर मुझे पहले देखना है कि पढ़ाते कैसे हैं.
S: बिल्कुल. रविवार को एक फ्री डेमो क्लास है, शाम छह बजे. आप और आपका बेटा दोनों जुड़ सकते हैं.
P: रविवार शाम छह बजे ठीक है. लिंक भेज दीजिए.
S: मैं अभी लिंक और फीस का पूरा ब्रेकअप व्हाट्सएप पर भेजती हूँ. धन्यवाद गुप्ता जी.
P: ठीक है, धन्यवाद.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "hinglish", "education", "parent", "demo"],
        )
    )

    add(
        scenario(
            "R08",
            "Closing call: the buyer confirms the booking amount",
            persona="seller: builder's sales executive; other side: buyer ready to book",
            language="english",
            voices={"S": EN_SELLER_M, "P": EN_P_F},
            script="""
S: Hello Kavita, this is Karan from Sunleaf Homes. You said you'd decide on flat seven-oh-four by today. Have you and your husband had a chance to talk it over?
P: Hi Karan. Yes, we have. We want to go ahead with seven-oh-four.
S: That's wonderful news, congratulations! Let me just go over the final numbers so there are no surprises.
P: Please do. I want it in writing as well.
S: The agreed price is seventy-four lakh, including one covered parking. The booking amount is two lakh, and the balance follows the construction schedule.
P: And the free modular kitchen you mentioned during the visit is included?
S: Yes, the modular kitchen is included, and it will be written into the allotment letter.
P: Good. How do I pay the booking amount?
S: You can transfer it to the project's escrow account. I'll send the account details on email from my official address, so you can verify them.
P: Okay. I'll transfer the two lakh tomorrow morning.
S: Perfect. Once it reaches, we'll send the allotment letter within two working days. Then we fix a date for the agreement registration.
P: Can we do the registration on a Saturday? We both work on weekdays.
S: Yes, Saturday works. I'll book the registration for the Saturday after next, and I'll call you to confirm the time.
P: Great. Thank you for being patient with all our questions, Karan.
S: It was a pleasure. I'll email the account details in the next ten minutes. Congratulations again, Kavita.
P: Thank you. Bye.
""",
            expect={"outcome": "report", "sales": True, "purpose": ["sales"]},
            covers=["sales", "english", "buyer", "closing", "won"],
        )
    )

    # ---- Not sales --------------------------------------------------------------------------

    add(
        scenario(
            "R09",
            "Wrong number",
            persona="seller dials a stored number; the person who answers is someone else",
            language="hinglish",
            voices={"S": HI_M2, "P": HI_F},
            script="""
S: हेलो, शर्मा जी बोल रहे हैं? मैं सनलीफ होम्स से बोल रहा हूँ.
P: नहीं, यहाँ कोई शर्मा जी नहीं हैं. आपको कौन सा नंबर चाहिए था?
S: ये नंबर हमारे पास शर्मा जी के नाम से सेव है. उन्होंने फ्लैट के बारे में पूछा था.
P: नहीं भाई, ये मेरा नंबर है, दो साल से. शायद पहले किसी और का रहा होगा.
S: अच्छा अच्छा, माफ़ कीजिए. मैं अपनी लिस्ट में ठीक कर देता हूँ.
P: ठीक है, कोई बात नहीं.
S: सॉरी फिर से, आपका दिन अच्छा रहे.
P: हाँ, बाय.
""",
            expect={"outcome": "held", "sales": False, "purpose": ["personal", "unclear"]},
            covers=["not_sales", "wrong_number", "hinglish", "short"],
        )
    )

    add(
        scenario(
            "R10",
            "Personal call: family, dinner and a wedding",
            persona="the seller's personal call with a family member, made from the work phone",
            language="hinglish",
            voices={"S": HI_M2, "P": HI_F},
            script="""
S: हेलो माँ, हाँ बोलो. मैं अभी ऑफिस से निकल रहा हूँ.
P: बेटा, आते हुए सब्ज़ी ले आना. टमाटर, प्याज़ और थोड़ा धनिया. घर में कुछ नहीं है.
S: ठीक है, ले आऊँगा. और कुछ चाहिए?
P: हाँ, दूध भी ले आना, दो पैकेट. और सुन, रीना दीदी का फोन आया था.
S: अच्छा, क्या कह रही थी?
P: उसकी बेटी की शादी की तारीख पक्की हो गई है. फरवरी में, बारह तारीख को. हम सबको तीन दिन पहले आना है.
S: फरवरी में? अरे वाह. पर मुझे ऑफिस से छुट्टी लेनी पड़ेगी, तीन दिन की.
P: तो ले लेना ना. साल में एक बार तो सब मिलते हैं. तेरे पापा भी कह रहे थे.
S: हाँ माँ, मैं अगले हफ्ते बॉस से बात कर लूँगा. ट्रेन की टिकट भी जल्दी करनी होगी.
P: हाँ, टिकट तू ही करवा देना, मुझे वो ऐप समझ नहीं आता.
S: ठीक है, मैं रविवार को बैठकर सबकी टिकट कर दूँगा. और खाने में क्या बना रही हो आज?
P: राजमा चावल. तू जल्दी आ जा, ठंडा हो जाएगा.
S: बस आधे घंटे में पहुँच रहा हूँ. सब्ज़ी और दूध लेकर.
P: ठीक है, ध्यान से आना. गाड़ी धीरे चलाना.
S: हाँ माँ, ठीक है. रखता हूँ.
""",
            expect={"outcome": "any", "sales": False, "purpose": ["personal"]},
            covers=["not_sales", "personal", "hinglish", "detection"],
        )
    )

    add(
        scenario(
            "R11",
            "A bank's IVR menu, nobody answers",
            persona="the seller calls a bank's customer care and only hears the menu",
            language="english",
            voices={"S": EN_SELLER_M, "I": RECORDED},
            script="""
I: Welcome to Northstar Bank customer care. Your call may be recorded for quality and training purposes.
I: For English, press one. Hindi ke liye, do dabaaiye.
I: Thank you. To check your account balance, press one. For credit card services, press two. For home loans, press three. To report a lost card, press nine.
S: Home loans.
I: Sorry, I did not understand that. For home loans, press three.
I: You have selected home loans. For a new home loan, press one. For an existing loan account, press two. To speak to an officer, press zero.
I: All our officers are busy at the moment. Please stay on the line, your call is important to us.
I: You can also apply for a home loan on our website or mobile app, at any time of the day.
I: All our officers are still busy. Please call back between nine in the morning and six in the evening. Thank you for calling Northstar Bank.
""",
            expect={"outcome": "any", "sales": False, "purpose": ["support", "unclear"]},
            covers=["not_sales", "ivr", "english", "one_sided"],
        )
    )

    add(
        scenario(
            "R12",
            "Internal call: the sales manager and the seller about the week",
            persona="internal: the seller's manager checks targets and site visits",
            language="english",
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
P: Hi Ritu, it's Manish. Do you have two minutes before the team meeting?
S: Sure, Manish. Go ahead.
P: I'm putting the weekly numbers together for the director. How many site visits did you have this week?
S: Six visits done, and two more on Sunday. One of them looks very likely to book.
P: Good. The target for the month is ten bookings for the team, and we're at four. So Sunday matters.
S: I know. I've also got three follow-ups pending from last week's open house.
P: Close those out by Friday, please. Either they come for a visit, or we mark them lost and move on.
S: Okay. Also, the sample flat's air conditioner isn't working. Two visitors complained about the heat.
P: I'll tell the facilities team today. Anything else?
S: I wanted to ask about leave. I need three days in February for a family wedding.
P: Put it in the system and I'll approve it. Just make sure someone covers your Sunday visits that week.
S: Thanks. I'll ask Karan to cover.
P: Great. And please update the lead stages before the meeting. The director looks at the dashboard.
S: Will do. See you in ten minutes.
P: See you.
""",
            expect={"outcome": "any", "sales": False, "purpose": ["internal"]},
            covers=["not_sales", "internal", "english", "detection"],
        )
    )

    add(
        scenario(
            "R13",
            "Support call: an existing buyer complains about seepage and delay",
            persona="support: an existing buyer with a complaint; nothing is being sold",
            language="english",
            voices={"S": EN_SELLER_M, "P": EN_P_M2},
            script="""
P: Hello, is this Karan from Sunleaf Homes? This is Vinod Bhatia, I bought flat five-oh-two in Tower B last year.
S: Yes, Mr. Bhatia, good morning. How can I help?
P: I'm calling with a complaint, again. There's water seeping through the bedroom wall since the rains, and nobody has come to fix it.
S: I'm sorry to hear that. When did you first report it?
P: Three weeks ago, through your customer portal. I got a ticket number and then nothing happened.
S: I apologise. I'll escalate it to the maintenance head today and ask them to visit within forty-eight hours.
P: Please do. The paint is peeling and there's a damp smell in the room where my daughter sleeps.
S: That's not acceptable, I agree. I'll also ask them to check the outer wall, because seepage usually comes from there.
P: And the second thing: the clubhouse was supposed to open in June. It's November now.
S: The clubhouse is waiting for the fire safety certificate. The latest date I have from the project team is the end of December.
P: You've been saying end of the month for five months.
S: I understand your frustration. I'll ask the project head to send all the owners a written update this week, with the reason and a firm date.
P: Fine. And please call me once the maintenance visit is fixed.
S: I will. I'll call you by this evening with the visit time. Again, I'm sorry for the trouble.
P: Okay. Thank you.
""",
            expect={"outcome": "any", "sales": False, "purpose": ["support"]},
            covers=["not_sales", "support", "english", "existing_customer", "detection"],
        )
    )

    add(
        scenario(
            "R14",
            "Dead air: the call connects and nobody speaks",
            persona="the call connects but the other side stays silent",
            language="english",
            voices={"S": EN_SELLER_M, "P": EN_P_F},
            script="""
S: Hello?
S: Hello, can you hear me?
S: Hello? I think the line is not clear.
S: I'll call you back in a few minutes.
""",
            expect={"outcome": "no_conversation", "sales": False, "purpose": ["unclear"]},
            audio={"noise": True, "snr_db": 18},
            pad_to_seconds=65.0,
            covers=["not_sales", "silence", "no_conversation"],
        )
    )

    add(
        scenario(
            "R15",
            "The network's 'switched off' message",
            persona="the phone network plays a recorded message; no person",
            language="english",
            voices={"S": EN_SELLER_M, "I": RECORDED},
            script="""
I: The number you have dialled is currently switched off. Please try again later.
I: The number you have dialled is currently switched off. Please try again later.
""",
            expect={"outcome": "no_conversation", "sales": False, "purpose": ["unclear"]},
            covers=["not_sales", "network_message", "no_conversation"],
        )
    )
    return calls


def pick(name: str) -> list[dict[str, Any]]:
    """A named set (``smoke``, ``full``) or a comma list of ids, in library order."""
    calls = library()
    if name == "full":
        return calls
    wanted = SETS.get(name) or tuple(part.strip() for part in name.split(",") if part.strip())
    known = {call["id"] for call in calls}
    unknown = [sid for sid in wanted if sid not in known]
    if unknown:
        raise SystemExit(f"unknown scenarios: {', '.join(unknown)}")
    return [call for call in calls if call["id"] in wanted]


def library_sha256() -> str:
    """Changes whenever a script, voice or expectation changes, so audio is re-rendered."""
    text = json.dumps(library(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def words(call: dict[str, Any]) -> int:
    return sum(len(text.split()) for _, text in call["turns"])


def build(out_dir: str) -> None:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    for call in library():
        (root / f"{call['id']}.json").write_text(
            json.dumps(call, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(call["id"], call["language"], words(call), "words", call["title"])


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "build":
        raise SystemExit("usage: scenarios.py build <out-dir>")
    build(sys.argv[2])
