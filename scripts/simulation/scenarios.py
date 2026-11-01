# ruff: noqa: E501 - the scripts are dialogue, one spoken line per line
"""The synthetic call library: 30 fictional Indian SMB sales calls with answer keys.

Every person, company and number here is made up. Lead phones are +91 00000 3xxxx
(AC Sales Sandbox) and +91 00000 4xxxx (Fortline Cyber Institute (Sandbox)): no Indian
number starts with 0 after +91, so none can ring anyone.

Each scenario is a script (who says what: S = the seller, P = the prospect, I = an IVR or
recorded voice) plus an answer key in the call data engine's own words
(packages/python/ac_platform/call_data/taxonomy.py) and the nine stages of the sandbox
organisations. ``python scenarios.py build <out>`` writes one JSON file per scenario.

Long calls (45 minutes, 2 hours) are composed from discovery blocks with a fixed seed, with
the key facts placed deep inside, so the answer key still holds.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

SCHEMA = "ac.simulation.scenario/1"

ORGS = {
    "ac": {"tenant_id": "3100ddbc-4549-4a5e-85b8-421af6edd588", "name": "AC Sales Sandbox"},
    "cy": {
        "tenant_id": "37c71e51-22aa-412a-8a0a-fbb589a29e14",
        "name": "Fortline Cyber Institute (Sandbox)",
    },
}
# Voices (piper): seller and prospect always differ in voice and, where it fits, gender.
EN_SELLER_F, EN_SELLER_M = "en_US-kristin-medium", "en_US-ryan-medium"
EN_P_F, EN_P_M, EN_P_M2 = "en_US-amy-medium", "en_GB-alan-medium", "en_US-joe-medium"
HI_M, HI_F, HI_M2 = "hi_IN-pratham-medium", "hi_IN-priyamvada-medium", "hi_IN-rohan-medium"
MR = "mr_IN-google-medium"
IVR = "en_US-hfc_female-medium"

ALL_STAGES = (
    "new",
    "open_leads",
    "not_connected",
    "interested",
    "meeting_scheduled",
    "meeting_done",
    "won",
    "lost",
    "junk",
)


def _turns(text: str) -> list[list[str]]:
    """'S: hello\\nP: hi' -> [['S', 'hello'], ['P', 'hi']]."""
    out: list[list[str]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        who, _, said = line.partition(":")
        assert who in {"S", "P", "I"}, line
        out.append([who, said.strip()])
    return out


def scenario(
    sid: str,
    title: str,
    *,
    org: str,
    seller: str,
    path: str,
    language: str,
    lead: dict[str, Any],
    voices: dict[str, Any],
    script: str | list[list[str]],
    key: dict[str, Any],
    expect: dict[str, Any],
    audio: dict[str, Any] | None = None,
    covers: list[str],
) -> dict[str, Any]:
    turns = _turns(script) if isinstance(script, str) else script
    return {
        "schema": SCHEMA,
        "id": sid,
        "title": title,
        "org": org,
        "tenant_id": ORGS[org]["tenant_id"],
        "seller": seller,
        "path": path,
        "language": language,
        "lead": lead,
        "voices": voices,
        "turns": turns,
        "key": key,
        "expect": expect,
        "audio": {"format": "m4a", "rate": 16000, "channels": 1, **(audio or {})},
        "covers": covers,
    }


# The seller's own offers (fictional).
AC_OFFER = (
    "Closing Bootcamp, a six-week sales coaching programme for small business teams, "
    "forty-five thousand rupees per seat"
)


def _long_call(
    seed: int,
    minutes: int,
    *,
    seller: str,
    prospect: str,
    company: str,
    city: str,
    anchors: list[tuple[float, list[list[str]]]],
    opening: list[list[str]],
    closing: list[list[str]],
) -> list[list[str]]:
    """A long discovery call: blocks drawn with a fixed seed until the word budget is
    reached; ``anchors`` (fraction, turns) land at that point of the call."""
    rng = random.Random(seed)  # noqa: S311 - a fixed seed composes the same call every time
    words_per_minute = 150
    budget = minutes * words_per_minute
    departments = [
        "the shop floor",
        "the dealer network",
        "the inside sales desk",
        "the field team in Nashik",
        "the distributor desk",
        "the new Aurangabad branch",
        "the export enquiries",
        "the online orders",
        "the institutional buyers",
        "the retail counter",
    ]
    products = [
        "the premium range",
        "the bulk packs",
        "the festive hampers",
        "the annual contracts",
        "the spare parts",
        "the installation service",
        "the maintenance plan",
        "the starter kits",
    ]
    months = ["June", "July", "August", "September", "October", "November", "December"]
    numbers = ["twelve", "fifteen", "eighteen", "twenty", "twenty-five", "thirty", "forty"]

    def block() -> list[list[str]]:
        d, p, m, n = (
            rng.choice(departments),
            rng.choice(products),
            rng.choice(months),
            rng.choice(numbers),
        )
        n2 = rng.choice(numbers)
        kinds = [
            [
                [
                    "S",
                    f"Let us talk about {d}. How does an enquiry move there today, step by step?",
                ],
                [
                    "P",
                    f"Someone calls or messages, the person on {d} notes it in a register, and then "
                    f"whoever is free calls back. Honestly some days it is the same day, some days it "
                    f"is two or three days later, depending on how busy we are with {p}.",
                ],
                ["S", "And who checks that the call back actually happened?"],
                [
                    "P",
                    "Nobody really. I look at the register on Saturdays if I get time. Most weeks I "
                    "do not get time.",
                ],
                [
                    "S",
                    "That is very common. In most teams we work with, about a third of enquiries never "
                    "get a second call. Do you have a feel for your number?",
                ],
                [
                    "P",
                    f"If I am honest, maybe {n} out of a hundred never hear from us again. Especially "
                    f"in {m}, which is our busy month.",
                ],
            ],
            [
                ["S", f"What do your best people do differently when they sell {p}?"],
                [
                    "P",
                    "They ask more questions. They do not jump to the price. My weaker people say the "
                    "price in the first minute and then the customer just says I will think about it.",
                ],
                [
                    "S",
                    "How many of your people would you call strong, and how many are still learning?",
                ],
                [
                    "P",
                    f"Out of the team, maybe three are strong. The rest joined in the last year. In "
                    f"{m} we hired {n2} percent more people than last year.",
                ],
                [
                    "S",
                    "So the gap is mostly in the newer people. Do they get any training when they join?",
                ],
                [
                    "P",
                    "They sit with a senior for a week. That is all. There is no proper system. "
                    "Everybody learns from whoever they sit next to.",
                ],
            ],
            [
                [
                    "S",
                    f"When a customer says it is too expensive for {p}, what does your team say?",
                ],
                [
                    "P",
                    "Mostly they offer a discount. Five percent, sometimes ten. I keep telling them not "
                    "to, but they want to close the deal.",
                ],
                ["S", "How much margin do you lose to that in a month, roughly?"],
                [
                    "P",
                    f"I have never calculated it exactly. If I think about {m}, maybe {n} thousand "
                    f"rupees across the team. It adds up.",
                ],
                [
                    "S",
                    "We can come back to that. A big part of the bootcamp is holding the price without "
                    "losing the customer.",
                ],
                ["P", "That part alone would be useful, to be frank."],
            ],
            [
                [
                    "S",
                    f"Tell me about follow-ups on {d}. Do you use any software, or is it phone and WhatsApp?",
                ],
                [
                    "P",
                    "Phone and WhatsApp. We tried a CRM two years back. People did not update it, so it "
                    "died in three months.",
                ],
                ["S", "Why do you think they did not update it?"],
                [
                    "P",
                    "Too many fields. And nobody asked them about it. If the owner does not look at it, "
                    "the team will not fill it.",
                ],
                ["S", "That is a very honest answer. Who would look at it this time?"],
                ["P", f"I would. And my operations head, for {d} at least."],
            ],
            [
                ["S", f"How do you plan targets for {p} each month?"],
                [
                    "P",
                    f"Last year's number plus something. For {m} we kept a target of about {n} lakh "
                    f"for that line. We reached maybe eighty percent.",
                ],
                ["S", "What stopped the other twenty percent?"],
                [
                    "P",
                    "Late follow-ups, I think, and some big orders that slipped to the next month. "
                    "Customers delay when nobody pushes them.",
                ],
                ["S", "So the deals were there, but they were not pushed over the line."],
                ["P", "Exactly. That is the problem in one line."],
            ],
            [
                ["S", "Can I ask how you hire salespeople today?"],
                [
                    "P",
                    "References mostly. Someone's cousin, someone from a competitor. We do one "
                    "interview and that is it.",
                ],
                ["S", f"And how long before a new person on {d} sells on their own?"],
                [
                    "P",
                    f"Three or four months. Some never do. Out of the last {n2} we hired, I would say "
                    "half left within a year.",
                ],
                [
                    "S",
                    "That is expensive. Every person who leaves takes their customers' trust too.",
                ],
                ["P", "Yes. Customers ask me where the last person went. It is embarrassing."],
            ],
            [
                ["S", f"What happens after a customer buys {p}? Does anyone call them again?"],
                [
                    "P",
                    "Only if there is a complaint. We do not call for repeat orders. They come back "
                    "on their own, or they go to someone else.",
                ],
                ["S", "Roughly what share of your sales are repeat customers?"],
                [
                    "P",
                    f"Maybe {n} percent. It should be higher. Our product is good, people like it.",
                ],
                ["S", "So there is money sitting in your old customer list."],
                ["P", "I think so. Nobody has time to call them."],
            ],
        ]
        return rng.choice(kinds)

    turns: list[list[str]] = list(opening)
    total = sum(len(t[1].split()) for t in turns)
    placed = sorted(anchors, key=lambda a: a[0])
    closing_words = sum(len(t[1].split()) for t in closing)
    while total < budget - closing_words:
        if placed and total >= placed[0][0] * budget:
            for turn in placed.pop(0)[1]:
                turns.append(turn)
                total += len(turn[1].split())
            continue
        for turn in block():
            turns.append(turn)
            total += len(turn[1].split())
    for _, anchor in placed:
        turns.extend(anchor)
    turns.extend(closing)
    return turns


def library() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    add = out.append

    # S01 inbound enquiry -> demo booked.
    add(
        scenario(
            "S01",
            "Inbound enquiry from a Meta form, demo booked",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Anil Deshmukh", "phone": "+91 00000 30001", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
S: Hello, am I speaking with Anil Deshmukh? This is Priya from AC Sales Sandbox. You filled in our form about sales training for your team.
P: Yes, yes, Anil here. I filled it last night. Thanks for calling back so fast.
S: Of course. Is this a good time for five minutes?
P: Yes, go ahead. I am at the office.
S: Wonderful. Can you tell me a little about your business first?
P: We run Deshmukh Auto Spares in Nashik. Two-wheeler and car spare parts, wholesale and retail. I have eight salespeople.
S: Eight people. And what made you fill in the form now?
P: Honestly, my people are not following up. Customers ask for a quote, we send it, and then nobody calls them again. I am losing orders to the shop next door.
S: That is the most common thing we hear. How many quotes go out in a month, roughly?
P: Around two hundred. If half of them closed I would be very happy. Right now maybe one in five closes.
S: Got it. We run a programme called Closing Bootcamp. It is six weeks, live sessions with your team, and a follow-up system they actually use.
P: What does it cost?
S: It is forty-five thousand rupees per seat, but for a team of eight we have a team package. I would rather show you how it works first and then talk about the package.
P: Okay. My budget for this is around two to two and a half lakh in total. I cannot go above that this year.
S: That is helpful, thank you. When would you want your team to start?
P: Before Diwali if possible. After Diwali the market is busy and nobody will have time.
S: Makes sense. Is anyone else involved in the decision?
P: My brother Sunil is my partner. He handles the accounts. He should be there.
S: Then let us do a short online demo with both of you. Would Tuesday at four in the evening work?
P: Tuesday at four is fine. Sunil is free after three.
S: Perfect. I will send the Google Meet link on WhatsApp today, along with two case studies from auto parts dealers.
P: Good. Send it on this number.
S: Done. So Tuesday four p.m., you and Sunil, a thirty-minute demo. Thank you, Anil.
P: Thank you, Priya. Talk on Tuesday.
""",
            key={
                "person.name": ["anil"],
                "company.name": ["deshmukh auto"],
                "company.location": ["nashik"],
                "company.team_size": {"number": 8},
                "need.primary_pain": [["follow"], ["quote"]],
                "money.budget": {"amount": 250000, "low": 200000, "high": 250000},
                "money.price_quoted": {"amount": 45000},
                "decision.timeline": [["diwali"]],
                "decision.maker": [["sunil", "brother", "partner"]],
                "commitment.next_step": [["demo"]],
                "commitment.seller_promise": [["meet link", "link", "case stud"]],
                "meeting": {"weekday": "tuesday", "hour": 16},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_scheduled",
                "stage_ok": ["meeting_scheduled"],
                "follow_up": {"weekday": "tuesday", "hour": 16},
            },
            audio={"format": "m4a"},
            covers=["inbound", "meeting_booked"],
        )
    )

    # S02 cold call rejected.
    add(
        scenario(
            "S02",
            "Cold call, rejected: in-house trainer already",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Kavita Rao", "phone": "+91 00000 30002", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_F},
            script="""
S: Good afternoon, am I speaking with Kavita Rao?
P: Yes, who is this?
S: This is Priya from AC Sales Sandbox. We help small business sales teams close more of their enquiries. Do you have two minutes?
P: I have one minute. What is it about?
S: I saw that Rao Interiors has grown a lot in Hyderabad this year. Usually when a design firm grows, follow-ups with walk-in customers start slipping. Is that something you see?
P: Not really. We have a full-time sales trainer in-house. She has been with us for six years.
S: That is great. Many of our clients also have an in-house trainer, and we work alongside them with a follow-up system.
P: I understand, but we are not looking for anything like this. We just renewed our CRM contract for two years as well.
S: Fair enough. Would it be all right if I send a short note by email, in case it is useful next year?
P: No, please do not. We are really not interested. Please take my number off your list.
S: Understood, I will remove it. Thank you for your time, Kavita.
P: Thank you. Bye.
""",
            key={
                "person.name": ["kavita"],
                "company.name": ["rao interiors"],
                "company.location": ["hyderabad"],
                "friction.objection": [["in-house", "trainer", "not interested", "not looking"]],
                "market.alternative": [["trainer", "crm", "in-house"]],
                "outcome.call_outcome": "no_sale",
                "forbid": ["money.budget", "commitment.follow_up"],
            },
            expect={
                "report": True,
                "stage": "lost",
                "stage_ok": ["lost", "junk"],
                "follow_up": None,
            },
            audio={"format": "mp3"},
            covers=["cold_rejected"],
        )
    )

    # S03 heavy objections.
    add(
        scenario(
            "S03",
            "Inbound, heavy objections, follow-up agreed",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Farhan Shaikh", "phone": "+91 00000 30003", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M2},
            script="""
S: Hello Farhan, this is Priya from AC Sales Sandbox. You asked about our sales coaching on the website yesterday.
P: Yes, I did. But let me tell you upfront, I have been burnt before.
S: I am sorry to hear that. What happened?
P: Two years back we paid a trainer from Mumbai one and a half lakh. He gave three days of motivational speeches. Nothing changed after one week.
S: That is frustrating. What did you hope would change?
P: I hoped my team would close more of the leads we pay for. We spend almost sixty thousand a month on Google Ads for Shaikh Pharma Distributors. Most leads just die.
S: So the problem is not getting leads, it is converting them.
P: Exactly. But your programme is forty-five thousand per person. That is too expensive for us. I have six people.
S: I hear you. Can I ask what one extra order a month is worth to you?
P: One order from a hospital can be two to three lakh.
S: So if the programme gets each of your six people one extra order in a quarter, it pays for itself many times over.
P: That is what everyone says. The last trainer said the same thing.
S: Fair. The difference is that we do not do speeches. We sit on their real calls every week for six weeks and we track the numbers with you.
P: My people also do not have time. They are on the road all day. They cannot sit in classes.
S: The sessions are forty minutes, twice a week, at eight in the morning, on the phone. Most teams do them from home before work.
P: Hmm. And what if it does not work?
S: If your conversion has not moved by week four, you can stop and we refund the remaining weeks.
P: That sounds better. But I still need to talk to my father. He is the one who signs the cheques.
S: Of course. What would help you make the case to him?
P: Send me a case study from a distribution business, and the refund terms in writing.
S: I will send both on WhatsApp today. Can I call you on Friday at eleven to hear what your father thinks?
P: Friday at eleven is okay. But no pressure, okay?
S: No pressure at all. Talk on Friday, Farhan.
""",
            key={
                "person.name": ["farhan"],
                "company.name": ["shaikh pharma"],
                "company.team_size": {"number": 6},
                "need.primary_pain": [["convert", "leads", "close"]],
                "money.price_quoted": {"amount": 45000},
                "money.investment_discussed": {"amount": 60000},
                "friction.objection": [
                    ["expensive", "price", "cost"],
                    ["burnt", "trainer", "before", "last trainer"],
                    ["time", "road", "classes"],
                    ["father", "cheque"],
                ],
                "market.past_attempt": [["trainer", "mumbai", "motivational"]],
                "decision.maker": [["father"]],
                "commitment.seller_promise": [["case study", "refund"]],
                "commitment.follow_up": [["friday"]],
                "meeting": {"weekday": "friday", "hour": 11},
                "outcome.call_outcome": "follow_up_agreed",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"weekday": "friday", "hour": 11},
            },
            covers=["heavy_objections"],
        )
    )

    # S04 negotiation on the seller's own product price -> won.
    add(
        scenario(
            "S04",
            "Price negotiation on the team package, closed at 1.55 lakh",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Meenal Patil", "phone": "+91 00000 30004", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_F},
            script="""
S: Hi Meenal, Priya here from AC Sales Sandbox. You said you would have an answer on the team package today.
P: Hi Priya. Yes, we discussed it. We like it, but the price is the problem.
S: Let us talk about it. The package for your four people is one lakh eighty thousand for the six weeks.
P: We were thinking one lakh forty thousand. That is what we can manage this quarter.
S: I understand. One lakh forty would mean cutting the weekly call reviews, which is the part that changes behaviour. I would not want to sell you a weaker programme.
P: Then what can you do?
S: If you can confirm today, I can do one lakh sixty-five thousand, and you can pay it in two instalments.
P: One sixty-five is still high. Patil Home Appliances is a small company, Priya. Meet me in the middle. One fifty.
S: How about this: one lakh fifty-five thousand, two instalments, the first one before the batch starts and the second after week three.
P: One fifty-five in two parts. And you include the follow-up templates for WhatsApp?
S: Yes, the templates are included, and I will add one extra review session for you as the owner.
P: Okay. Deal. Send me the invoice for the first instalment.
S: Wonderful. The first instalment is seventy-seven thousand five hundred. When can you pay it?
P: I will transfer it on Monday.
S: Perfect. The batch starts on the fifteenth. I will send the invoice and the joining details today.
P: Thank you, Priya. Good doing business.
S: Thank you, Meenal. Welcome aboard.
""",
            key={
                "person.name": ["meenal"],
                "company.name": ["patil home"],
                "company.team_size": {"number": 4},
                "money.price_quoted": {"amount": 180000, "also": [165000, 155000]},
                "money.budget": {"amount": 140000, "low": 140000, "high": 150000},
                "friction.objection": [["price", "high", "expensive"]],
                "commitment.prospect_promise": [["monday", "transfer", "pay"]],
                "commitment.seller_promise": [["invoice"]],
                "outcome.call_outcome": "deal_closed",
            },
            expect={
                "report": True,
                "stage": "won",
                "stage_ok": ["won"],
                "deal_amount": 155000,
            },
            covers=["negotiation", "won"],
        )
    )

    # S05 call-back requested.
    add(
        scenario(
            "S05",
            "Busy prospect asks for a call back tomorrow at 6 pm",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Rakesh Gupta", "phone": "+91 00000 30005", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
S: Hello, Rakesh Gupta? This is Priya from AC Sales Sandbox, about the enquiry you sent for sales training.
P: Yes, Priya, I remember. But I am driving right now, I cannot talk properly.
S: No problem at all. When is a good time to call you back?
P: Tomorrow evening. Call me at six. After six I am free.
S: Tomorrow at six p.m., done. Is it still about training for your showroom team in Indore?
P: Yes, the showroom team. Twelve people. We can discuss tomorrow.
S: Perfect. I will call you tomorrow at six. Drive safe, Rakesh.
P: Thank you. Bye.
S: Bye.
""",
            key={
                "person.name": ["rakesh"],
                "company.location": ["indore"],
                "company.team_size": {"number": 12},
                "commitment.follow_up": [["tomorrow", "six", "6"]],
                "meeting": {"day_offset": 1, "hour": 18},
                "outcome.call_outcome": "callback_requested",
                "forbid": ["money.budget"],
            },
            expect={
                "report": "short_ok",
                "stage": "open_leads",
                "stage_ok": ["open_leads", "interested", "new"],
                "follow_up": {"day_offset": 1, "hour": 18},
            },
            covers=["callback"],
        )
    )

    # S06 wrong number.
    add(
        scenario(
            "S06",
            "Wrong number",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Sunil Jadhav", "phone": "+91 00000 30006", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M2},
            script="""
S: Hello, is this Sunil Jadhav?
P: No, there is no Sunil here. Wrong number.
S: Oh, sorry. Is this not Jadhav Traders?
P: No madam, this is a personal number. You have the wrong number.
S: My apologies. Sorry for the trouble.
P: It is okay. Bye.
""",
            key={
                "outcome.call_outcome": "no_conversation",
                "forbid": ["money.budget", "company.name"],
            },
            expect={
                "report": False,
                "hold": ["ai_no_conversation", "ai_short_call"],
                "stage": "junk",
                "stage_ok": ["junk", "not_connected", "new", "lost"],
            },
            audio={"format": "amr", "rate": 8000},
            covers=["wrong_number", "short_rule"],
        )
    )

    # S07 IVR / voicemail.
    add(
        scenario(
            "S07",
            "Switched-off IVR, then voicemail beep",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Pooja Iyer", "phone": "+91 00000 30007", "source": "manual"},
            voices={"S": EN_SELLER_F, "I": IVR},
            script="""
I: The number you are calling is currently switched off. Please try again later.
I: The number you are calling is currently switched off. Please try again later.
I: Please leave your message after the tone.
S: Hi Pooja, this is Priya from AC Sales Sandbox, returning your enquiry. I will try you again tomorrow. Thank you.
""",
            key={
                "outcome.call_outcome": "no_conversation",
                "forbid": ["money.budget", "person.role"],
            },
            expect={
                "report": False,
                "hold": ["ai_no_conversation", "ai_short_call"],
                "stage": "not_connected",
                "stage_ok": ["not_connected", "new"],
            },
            covers=["ivr_voicemail", "short_rule"],
        )
    )

    # S08 20-second hang-up.
    add(
        scenario(
            "S08",
            "Hang-up after about 20 seconds",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Vikram Sethi", "phone": "+91 00000 30008", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
S: Hello Vikram, this is Priya from AC Sales Sandbox, about sales training for your team.
P: I am in a meeting. Do not call me now.
S: Sorry, when can I call?
P: I said not now.
""",
            key={"outcome.call_outcome": "no_conversation", "forbid": ["money.budget"]},
            expect={
                "report": False,
                "hold": ["ai_no_conversation", "ai_short_call"],
                "stage": "not_connected",
                "stage_ok": ["not_connected", "open_leads", "new"],
                "max_seconds": 22,
            },
            covers=["hangup_20s", "short_rule"],
        )
    )

    # S09 45-minute discovery call.
    s09 = _long_call(
        9,
        45,
        seller="Rohan",
        prospect="Harish",
        company="Mahajan Kitchen Equipment",
        city="Pune",
        opening=_turns("""
S: Good morning Harish, Rohan from AC Sales Sandbox. Thanks for blocking the full hour for this.
P: Good morning Rohan. Yes, I wanted to go deep this time, not a quick call.
S: Perfect. Then let me ask a lot of questions and you stop me whenever you want.
P: Go ahead.
S: First, tell me about Mahajan Kitchen Equipment. What do you sell and to whom?
P: Commercial kitchen equipment. Ovens, burners, exhaust hoods, for hotels and restaurants in Pune and around. We have twenty-two people in sales.
"""),
        anchors=[
            (
                0.62,
                _turns("""
S: Let me ask the money question now that we have the full picture. What have you set aside for training this year?
P: For the sales team, three lakh rupees in total. My partner agreed to that number. Not more.
S: Three lakh in total. And by when do you want the first batch to finish?
P: Before the end of December, because January is when hotels plan their renovations.
"""),
            ),
            (
                0.8,
                _turns("""
S: Who else needs to agree before you go ahead?
P: My partner Nitin Mahajan. He looks after finance. He will want to see a proper proposal.
"""),
            ),
        ],
        closing=_turns("""
S: Harish, this has been very useful. I think the right next step is a proposal presentation for you and Nitin.
P: Agreed. Can we do it next Wednesday at three in the afternoon? Nitin is in the office that day.
S: Next Wednesday at three, at your office in Pune. I will bring the proposal with two options inside your three lakh.
P: Good. See you on Wednesday.
S: See you Wednesday, Harish. Thank you for your time.
"""),
    )
    add(
        scenario(
            "S09",
            "45-minute discovery call, proposal meeting booked",
            org="ac",
            seller="ac.rohan",
            path="phone",
            language="english",
            lead={"name": "Harish Mahajan", "phone": "+91 00000 30009", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_M},
            script=s09,
            key={
                "person.name": ["harish"],
                "company.name": ["mahajan kitchen"],
                "company.location": ["pune"],
                "company.team_size": {"number": 22},
                "need.primary_pain": [["follow", "discount", "training", "convert"]],
                "money.budget": {"amount": 300000},
                "decision.timeline": [["december"]],
                "decision.maker": [["nitin", "partner"]],
                "commitment.next_step": [["proposal"]],
                "meeting": {"weekday": "wednesday", "hour": 15},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_scheduled",
                "stage_ok": ["meeting_scheduled"],
                "follow_up": {"weekday": "wednesday", "hour": 15},
            },
            covers=["long_45min"],
        )
    )

    # S10 2-hour call.
    s10 = _long_call(
        10,
        112,  # about 118 minutes at phone pace: inside the pipeline's 2-hour limit
        seller="Rohan",
        prospect="Devika",
        company="Kalyani Textiles",
        city="Surat",
        opening=_turns("""
S: Hello Devika, Rohan from AC Sales Sandbox. Thank you for making time for the full workshop call.
P: Hello Rohan. Yes, I have kept two hours. My operations head may join for some time in between.
S: Perfect. Let us start with the big picture. Tell me about Kalyani Textiles.
P: We make sarees and dress material in Surat and sell to about four hundred retailers across Gujarat and Maharashtra. Our sales team is thirty-five people.
"""),
        anchors=[
            (
                0.8,
                _turns("""
S: Devika, we are deep into this now. Can I ask about the budget you have in mind?
P: For the full team, we have kept six lakh rupees for this financial year. That was approved last month.
S: Six lakh for the year. And when do you need the team trained?
P: Before the wedding season starts in mid-January. That is when retailers stock up.
"""),
            ),
        ],
        closing=_turns("""
S: Devika, thank you for two very honest hours. Shall we meet in Surat to finalise the plan?
P: Yes. Saturday at ten in the morning, at our factory office. My operations head Paresh will join.
S: Saturday at ten, at your factory office in Surat, with Paresh. I will bring the rollout plan and the contract draft.
P: Perfect. See you on Saturday.
"""),
    )
    add(
        scenario(
            "S10",
            "2-hour workshop call, visit booked",
            org="ac",
            seller="ac.rohan",
            path="phone",
            language="english",
            lead={"name": "Devika Kalyani", "phone": "+91 00000 30010", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_F},
            script=s10,
            key={
                "person.name": ["devika"],
                "company.name": ["kalyani textiles"],
                "company.location": ["surat"],
                "company.team_size": {"number": 35},
                "money.budget": {"amount": 600000},
                "decision.timeline": [["january", "wedding season"]],
                "person.other_party": [["paresh", "operations head"]],
                "commitment.next_step": [["meet", "visit", "rollout", "contract"]],
                "meeting": {"weekday": "saturday", "hour": 10},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_scheduled",
                "stage_ok": ["meeting_scheduled"],
                "follow_up": {"weekday": "saturday", "hour": 10},
            },
            audio={"format": "m4a", "rate": 16000},
            covers=["long_2h"],
        )
    )

    # S11 Hinglish inbound, meeting booked (web upload path).
    add(
        scenario(
            "S11",
            "Hinglish inbound enquiry, visit booked (web upload)",
            org="ac",
            seller="ac.rohan",
            path="web",
            language="hinglish",
            lead={"name": "Sanjay Verma", "phone": "+91 00000 30011", "source": "manual"},
            voices={"S": HI_M2, "P": HI_M},
            script="""
S: हेलो, संजय वर्मा जी? मैं रोहन बोल रहा हूँ, AC सेल्स सैंडबॉक्स से. आपने कल हमारी वेबसाइट पर सेल्स ट्रेनिंग के लिए इन्क्वायरी की थी.
P: हाँ हाँ, रोहन जी, बोलिए. मैंने ही फॉर्म भरा था.
S: थैंक यू सर. आपका बिज़नेस क्या है, थोड़ा बताइए?
P: हमारा वर्मा इलेक्ट्रिकल्स है, लखनऊ में. स्विच, वायर, फैन, सब होलसेल में. दस लोगों की सेल्स टीम है.
S: अच्छा. और अभी सबसे बड़ी प्रॉब्लम क्या है टीम में?
P: प्रॉब्लम ये है कि लड़के कोटेशन भेज देते हैं, फिर फॉलो अप नहीं करते. आधे ऑर्डर ऐसे ही चले जाते हैं.
S: समझ गया. हमारा क्लोज़िंग बूटकैंप छह हफ्ते का है, उसमें यही फॉलो अप सिस्टम सिखाते हैं.
P: फीस कितनी है?
S: पर सीट पैंतालीस हज़ार है, लेकिन दस लोगों के लिए टीम पैकेज बनता है.
P: देखिए, मेरा बजट डेढ़ लाख तक है. उससे ज़्यादा नहीं हो पाएगा.
S: ठीक है सर, डेढ़ लाख में भी ऑप्शन बन सकता है. मैं एक बार आपके ऑफिस आकर समझा दूँ?
P: हाँ, आ जाइए. गुरुवार को सुबह ग्यारह बजे ठीक रहेगा.
S: गुरुवार, सुबह ग्यारह बजे, आपके ऑफिस में. मैं लोकेशन व्हाट्सएप पर ले लूँगा.
P: ठीक है, मैं लोकेशन भेज देता हूँ.
S: थैंक यू संजय जी, गुरुवार को मिलते हैं.
P: ठीक है, नमस्ते.
""",
            key={
                "person.name": ["sanjay", "संजय"],
                "company.name": ["verma electric", "वर्मा इलेक्ट्रिकल"],
                "company.location": ["lucknow", "लखनऊ"],
                "company.team_size": {"number": 10},
                "need.primary_pain": [["follow", "फॉलो"]],
                "money.budget": {"amount": 150000},
                "money.price_quoted": {"amount": 45000},
                "commitment.next_step": [["visit", "meet", "office", "ऑफिस"]],
                "meeting": {"weekday": "thursday", "hour": 11},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_scheduled",
                "stage_ok": ["meeting_scheduled"],
                "follow_up": {"weekday": "thursday", "hour": 11},
            },
            covers=["hinglish", "web_upload"],
        )
    )

    # S12 Marathi-English follow-up.
    add(
        scenario(
            "S12",
            "Marathi-English call, follow-up next Monday",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="marathi-english",
            lead={"name": "Sachin Kale", "phone": "+91 00000 30012", "source": "manual"},
            voices={"S": {"model": MR, "speaker": 1}, "P": {"model": MR, "speaker": 6}},
            script="""
S: नमस्कार, सचिन काळे बोलत आहात का? मी प्रिया, AC सेल्स सँडबॉक्स मधून बोलते.
P: हो, मी सचिन. बोला.
S: तुम्ही आमच्या सेल्स ट्रेनिंग बद्दल विचारलं होतं. तुमचा बिझनेस काय आहे?
P: आमचं काळे फर्निचर आहे, कोल्हापूर मध्ये. शोरूम आहे आणि सहा सेल्समन आहेत.
S: छान. आणि सध्या टीम मध्ये काय अडचण आहे?
P: लोक शोरूम मध्ये येतात, बघतात, आणि परत येत नाहीत. आमचे सेल्समन त्यांना परत फोन करत नाहीत.
S: बरोबर. आमचा क्लोजिंग बूटकॅम्प हेच शिकवतो, follow up कसा करायचा.
P: फी किती आहे?
S: एका सीटला पंचेचाळीस हजार रुपये.
P: ते जरा जास्त वाटतं. मला माझ्या भावाशी बोलावं लागेल, तो पार्टनर आहे.
S: नक्कीच. मी तुम्हाला ब्रोशर व्हॉट्सॲप वर पाठवते. पुढच्या सोमवारी परत फोन करू का?
P: हो, सोमवारी संध्याकाळी पाच नंतर फोन करा.
S: ठीक आहे, सोमवारी पाच वाजता फोन करते. धन्यवाद सचिन.
P: धन्यवाद.
""",
            key={
                "person.name": ["sachin", "सचिन"],
                "company.name": ["kale furniture", "काळे फर्निचर"],
                "company.location": ["kolhapur", "कोल्हापूर"],
                "company.team_size": {"number": 6},
                "money.price_quoted": {"amount": 45000},
                "friction.objection": [["price", "expensive", "जास्त", "high", "cost"]],
                "decision.maker": [["brother", "partner", "भाऊ"]],
                "commitment.seller_promise": [["brochure", "ब्रोशर"]],
                "commitment.follow_up": [["monday", "सोमवार"]],
                "meeting": {"weekday": "monday", "hour": 17},
                "outcome.call_outcome": "follow_up_agreed",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"weekday": "monday", "hour": 17},
            },
            covers=["marathi_english"],
        )
    )

    # S13 Hindi, objections, brochure on WhatsApp (web upload).
    add(
        scenario(
            "S13",
            "Hindi call with objections, brochure on WhatsApp (web upload)",
            org="ac",
            seller="ac.rohan",
            path="web",
            language="hindi",
            lead={"name": "Ramesh Yadav", "phone": "+91 00000 30013", "source": "manual"},
            voices={"S": HI_M2, "P": HI_M},
            script="""
S: नमस्ते, रमेश यादव जी बोल रहे हैं? मैं रोहन, एसी सेल्स सैंडबॉक्स से.
P: हाँ, बोलिए. क्या काम है?
S: आपने हमारी सेल्स ट्रेनिंग के बारे में पूछा था. आपका व्यापार क्या है?
P: यादव ट्रैक्टर पार्ट्स, कानपुर में. सात लोग बेचते हैं, गाँव गाँव जाते हैं.
S: अच्छा. टीम में सबसे बड़ी मुश्किल क्या है?
P: लड़के ग्राहक से बात तो करते हैं, पर सौदा पक्का नहीं कर पाते. ग्राहक कहता है सोचेंगे, और बात वहीं खत्म.
S: समझ गया. हमारे कार्यक्रम में यही सिखाते हैं कि सौदा कैसे पक्का करें.
P: पर भाई, पैसे बहुत लगेंगे. और मेरे लड़के क्लास में नहीं बैठेंगे, वो दिन भर बाहर रहते हैं.
S: क्लास फ़ोन पर होती है, सुबह आठ बजे, चालीस मिनट. बाहर रहते हुए भी कर सकते हैं.
P: हम्म. पहले भी एक बार ट्रेनिंग करवाई थी, कोई फ़ायदा नहीं हुआ.
S: इसीलिए हम चार हफ्ते में नतीजा न दिखे तो बाकी पैसे लौटा देते हैं.
P: अच्छा. ठीक है, आप मुझे व्हाट्सएप पर पूरी जानकारी भेज दीजिए. मैं पढ़ के बताऊँगा.
S: ज़रूर. मैं आज ही भेज देता हूँ. परसों फिर फ़ोन करूँ?
P: हाँ, परसों दोपहर में कर लीजिए.
S: ठीक है रमेश जी, धन्यवाद.
P: धन्यवाद.
""",
            key={
                "person.name": ["ramesh", "रमेश"],
                "company.name": ["yadav tractor", "यादव ट्रैक्टर"],
                "company.location": ["kanpur", "कानपुर"],
                "company.team_size": {"number": 7},
                "need.primary_pain": [["close", "सौदा", "deal", "think", "सोचेंगे"]],
                "friction.objection": [
                    ["price", "money", "पैसे", "cost", "expensive"],
                    ["class", "time", "क्लास", "outside", "field"],
                    ["before", "पहले", "training", "past"],
                ],
                "commitment.seller_promise": [["whatsapp", "व्हाट्सएप", "details", "जानकारी"]],
                "commitment.follow_up": [["day after", "परसों"]],
                "meeting": {"day_offset": 2, "hour": None},
                "outcome.call_outcome": "follow_up_agreed",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"day_offset": 2},
            },
            covers=["hindi", "web_upload", "heavy_objections"],
        )
    )

    # S14 noisy line.
    add(
        scenario(
            "S14",
            "Noisy line (market noise), demo booked",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Nitin Bhosale", "phone": "+91 00000 30014", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M2},
            script="""
S: Hello Nitin, Priya from AC Sales Sandbox. Is this a good time?
P: Hello? Yes, I am at the market, there is a lot of noise. Speak loudly please.
S: Sure. You enquired about training for your sales team. What is your business?
P: Bhosale Agro Chemicals. Fertilisers and pesticides, in Ahmednagar. Fifteen people in sales.
S: Fifteen people. What is the main problem you want to fix?
P: They do not know the products properly. Farmers ask questions and my people cannot answer, so the farmer goes to another shop.
S: Product knowledge and confidence. We cover that with your own product sheets.
P: Good. What is the cost?
S: Forty-five thousand per seat, with a team package for fifteen.
P: Budget is about four lakh for the whole team.
S: That works for a package. Can we do a demo on Monday at five in the evening?
P: Monday at five, yes. Send the link on WhatsApp.
S: Done. Monday five p.m. Thank you Nitin.
P: Okay, bye.
""",
            key={
                "person.name": ["nitin"],
                "company.name": ["bhosale agro"],
                "company.location": ["ahmednagar"],
                "company.team_size": {"number": 15},
                "need.primary_pain": [["product", "knowledge", "answer"]],
                "money.budget": {"amount": 400000},
                "money.price_quoted": {"amount": 45000},
                "commitment.next_step": [["demo"]],
                "meeting": {"weekday": "monday", "hour": 17},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_scheduled",
                "stage_ok": ["meeting_scheduled"],
                "follow_up": {"weekday": "monday", "hour": 17},
            },
            audio={"noise": "market", "snr_db": 6},
            covers=["noisy_line"],
        )
    )

    # S15 one side silent.
    add(
        scenario(
            "S15",
            "One-side-silent recording (prospect not recorded)",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Leena Fernandes", "phone": "+91 00000 30015", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_F},
            script="""
S: Hello Leena, Priya here from AC Sales Sandbox. Thanks for your enquiry about sales training.
P: Hi Priya. Yes, I run Fernandes Bakery Supplies in Goa. Nine people in sales.
S: Lovely. What made you look for training now?
P: My team only takes orders. They never suggest new products to the bakeries. Our average order is stuck.
S: So upselling is the gap. That is one of the six modules in our bootcamp.
P: Interesting. What is the fee?
S: Forty-five thousand per seat. For nine people we would make a package.
P: Okay. Send me the details, I will discuss it with my husband, he is the co-owner.
S: I will send it today on WhatsApp. Can I call you on Thursday at noon?
P: Thursday at twelve is fine.
S: Thank you Leena. Talk on Thursday.
""",
            key={
                "outcome.call_outcome": "follow_up_agreed",
                "commitment.follow_up": [["thursday"]],
            },
            expect={
                "report": "either",
                "hold": ["ai_no_conversation"],
                "one_sided": True,
                "stage_ok": ALL_STAGES,
            },
            audio={"silent_side": "P"},
            covers=["one_side_silent", "failure_handling"],
        )
    )

    # S16 crosstalk.
    add(
        scenario(
            "S16",
            "Crosstalk: both speak over each other during the price talk",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Ajay Kulshrestha", "phone": "+91 00000 30016", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
S: Hi Ajay, Priya from AC Sales Sandbox again.
P: Hello Priya. Before that, my team asked me to tell you the sample session was good.
S: That is lovely to hear. What did they like?
P: Two of my older salesmen said the role play was the first useful training they have had in years.
S: And did anything not work for them?
P: The timing. Eight in the morning is early for some of them, they travel from far.
S: We can move it to nine for your batch. Now, about the proposal, did you get a chance to look at it?
P: Yes, I saw it. Two lakh ten thousand for seven people. That is too much.
S: I understand, but the proposal includes
P: No, no, listen, my last vendor charged one lakh for everything.
S: The last vendor did not include the weekly
P: I know, I know, but one lakh is my number.
S: Let me finish, please. The weekly call reviews are why it works.
P: Okay, okay, go on.
S: For seven people I can bring it to one lakh seventy-five thousand if we start this month.
P: One seventy-five is still more than I planned. Let me speak with my CA and call you back.
S: Fair. When should I expect your call?
P: I will call you on Wednesday morning.
S: Wednesday morning then. Thank you Ajay.
""",
            key={
                "person.name": ["ajay"],
                "company.team_size": {"number": 7},
                "money.price_quoted": {"amount": 210000, "also": [175000]},
                "money.budget": {"amount": 100000},
                "friction.objection": [["too much", "price", "expensive", "more than"]],
                "commitment.prospect_promise": [["call", "wednesday"]],
                "outcome.call_outcome": "follow_up_agreed",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"weekday": "wednesday"},
            },
            audio={"crosstalk": True},
            covers=["crosstalk", "negotiation"],
        )
    )

    # S17 speakerphone echo.
    add(
        scenario(
            "S17",
            "Speakerphone with echo, call-back on Saturday",
            org="ac",
            seller="ac.rohan",
            path="phone",
            language="english",
            lead={"name": "Gaurav Mehta", "phone": "+91 00000 30017", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_M2},
            script="""
S: Hello Gaurav, Rohan from AC Sales Sandbox. Am I on speaker?
P: Yes, I am on speaker, I am in my car. Go ahead.
S: You had asked about training for your insurance advisors. How many advisors do you have?
P: Mehta Insurance Point has twenty advisors in Vadodara. Most of them are part-time.
S: Part-time advisors. What is the biggest challenge?
P: They are shy to call their own contacts. They wait for walk-ins. Walk-ins are very few.
S: How many policies does a typical advisor close in a month right now?
P: Two or three. The good ones close eight or ten, but there are only four or five of them.
S: So the gap between your best and the rest is big. That is usually about how they open the first conversation.
P: Yes. The good ones just talk naturally. The new ones read from a pamphlet.
S: That is mostly a confidence thing, and scripts help a lot. We have a module for exactly that.
P: Sounds good. But I am driving. Can you call me on Saturday morning?
S: Saturday at ten in the morning?
P: Make it eleven.
S: Saturday eleven a.m. Drive safe Gaurav.
P: Thanks Rohan.
""",
            key={
                "person.name": ["gaurav"],
                "company.name": ["mehta insurance"],
                "company.location": ["vadodara"],
                "company.team_size": {"number": 20},
                "need.primary_pain": [["shy", "confidence", "call", "walk-in"]],
                "commitment.follow_up": [["saturday"]],
                "meeting": {"weekday": "saturday", "hour": 11},
                "outcome.call_outcome": "callback_requested",
            },
            expect={
                "report": True,
                "stage": "open_leads",
                "stage_ok": ["open_leads", "interested"],
                "follow_up": {"weekday": "saturday", "hour": 11},
            },
            audio={"echo": True},
            covers=["speakerphone_echo", "callback"],
        )
    )

    # S18 Fortline inbound student, counselling booked.
    add(
        scenario(
            "S18",
            "Fortline inbound: working professional, counselling session booked",
            org="cy",
            seller="cy.karan",
            path="phone",
            language="english",
            lead={"name": "Aditi Nair", "phone": "+91 00000 40001", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_F},
            script="""
S: Hello Aditi, this is Karan from Fortline Cyber Institute. You enquired about our SOC Analyst Fast Track.
P: Hi Karan, yes. I work in IT support at a bank in Kochi and I want to move into cyber security.
S: That is a common path and a good one. How many years of experience do you have?
P: Four years in desktop and network support.
S: Good base. The Fast Track is sixteen weeks, weekend batches, live labs. The fee is forty-nine thousand rupees.
P: Is there an EMI option? I cannot pay it in one go.
S: Yes, six monthly instalments of about eight thousand five hundred.
P: That works. When does the next batch start?
S: The next weekend batch starts on the seventh of December.
P: Okay. Before I decide, I want to understand the placement support.
S: Let us set up a free counselling session with our placement mentor. Is Sunday at eleven good?
P: Sunday at eleven is good.
S: Done. I will send you the invite and the syllabus by email.
P: Thank you Karan.
""",
            key={
                "person.name": ["aditi"],
                "company.location": ["kochi"],
                "person.role": [["it support", "support"]],
                "need.goal": [["cyber", "security", "career", "move"]],
                "money.price_quoted": {"amount": 49000},
                "friction.question": [["emi", "instalment", "placement"]],
                "commitment.seller_promise": [["invite", "syllabus"]],
                "commitment.next_step": [["counselling", "session", "mentor"]],
                "meeting": {"weekday": "sunday", "hour": 11},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_scheduled",
                "stage_ok": ["meeting_scheduled", "interested"],
                "follow_up": {"weekday": "sunday", "hour": 11},
            },
            covers=["inbound", "meeting_booked", "fortline"],
        )
    )

    # S19 Fortline corporate cold call -> interested.
    add(
        scenario(
            "S19",
            "Fortline cold call to a company: phishing workshop proposal",
            org="cy",
            seller="cy.karan",
            path="phone",
            language="english",
            lead={"name": "Mohit Agarwal", "phone": "+91 00000 40002", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_M2},
            script="""
S: Good morning, is this Mohit Agarwal, the IT head at Agarwal Logistics?
P: Speaking. Who is this?
S: Karan from Fortline Cyber Institute. We run phishing-safe workshops for company teams. Do you have two minutes?
P: Two minutes. Go.
S: Most logistics firms we speak to have had at least one fake invoice email in the last year. Has that happened to you?
P: Actually yes. Last month our accounts team almost paid a fake vendor invoice. Ninety thousand rupees.
S: That is exactly what the workshop prevents. It is a half-day session for up to fifty staff, with a simulated phishing test after one month.
P: What does it cost?
S: Two lakh fifty thousand for up to fifty people, including the follow-up test.
P: We have about one hundred and twenty staff in Jaipur. I would need approval from our CFO.
S: Understood. Shall I send a proposal for one hundred and twenty people that you can show the CFO?
P: Yes, send it. My email is on our website, use the IT head address.
S: I will send it today and call you next Tuesday to discuss it.
P: Fine. Tuesday afternoon.
""",
            key={
                "person.name": ["mohit"],
                "person.role": [["it head", "it"]],
                "company.name": ["agarwal logistics"],
                "company.location": ["jaipur"],
                "company.team_size": {"number": 120},
                "need.primary_pain": [["phishing", "fake invoice", "invoice"]],
                "money.price_quoted": {"amount": 250000},
                "decision.approver": [["cfo"]],
                "decision.maker": [["cfo"]],
                "commitment.seller_promise": [["proposal"]],
                "commitment.follow_up": [["tuesday"]],
                "outcome.call_outcome": "follow_up_agreed",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"weekday": "tuesday"},
            },
            audio={"format": "mp3"},
            covers=["cold_positive", "fortline"],
        )
    )

    # S20 Fortline Hinglish fee negotiation, won (web upload).
    add(
        scenario(
            "S20",
            "Fortline Hinglish fee negotiation, enrolled with EMI (web upload)",
            org="cy",
            seller="cy.karan",
            path="web",
            language="hinglish",
            lead={"name": "Rahul Chauhan", "phone": "+91 00000 40003", "source": "manual"},
            voices={"S": HI_M2, "P": HI_M},
            script="""
S: हेलो राहुल, करण बोल रहा हूँ फोर्टलाइन साइबर इंस्टीट्यूट से. आपने कल फ़ीस के बारे में सोचने को कहा था.
P: हाँ करण भाई. देखो, कोर्स अच्छा है, लेकिन पचासी हज़ार बहुत ज़्यादा है.
S: समझ सकता हूँ. पहले ये बताइए, आप अभी कहाँ काम कर रहे हैं?
P: मैं एक कॉल सेंटर में आईटी सपोर्ट में हूँ, दो साल से. सैलरी कम है और ग्रोथ नहीं है.
S: और साइबर सिक्योरिटी ही क्यों?
P: उसमें स्कोप ज़्यादा है. मेरे दो दोस्त एसओसी एनालिस्ट बन गए, अच्छा पैकेज मिला.
S: साइबर डिफ़ेंस डिप्लोमा पूरा एक साल का है, लैब्स के साथ. फिर भी बताइए, आप कितना सोच रहे थे?
P: सत्तर हज़ार तक मैं कर सकता हूँ. उससे ऊपर नहीं.
S: सत्तर तो मुश्किल है. अगर आप इस हफ्ते जॉइन करते हैं तो पचहत्तर हज़ार कर सकता हूँ, और बारह किश्तों में.
P: पचहत्तर, बारह EMI में? ठीक है, डन. कब से शुरू होगा?
S: अगला बैच पंद्रह दिसंबर से है. मैं आज पेमेंट लिंक भेज देता हूँ.
P: ठीक है, मैं आज रात को पहली EMI भर दूँगा.
S: बहुत बढ़िया राहुल. वेलकम टू फोर्टलाइन.
P: थैंक यू करण भाई.
""",
            key={
                "person.name": ["rahul", "राहुल"],
                "person.role": [
                    ["it support", "आईटी सपोर्ट", "support", "call centre", "call center"]
                ],
                "money.price_quoted": {"amount": 85000, "also": [75000]},
                "money.budget": {"amount": 70000},
                "friction.objection": [["price", "fee", "ज़्यादा", "expensive"]],
                "commitment.seller_promise": [["payment link", "लिंक", "link"]],
                "commitment.prospect_promise": [["emi", "pay", "भर"]],
                "outcome.call_outcome": "deal_closed",
            },
            expect={"report": True, "stage": "won", "stage_ok": ["won"], "deal_amount": 75000},
            covers=["hinglish", "negotiation", "won", "web_upload", "fortline"],
        )
    )

    # S21 Fortline callback next month.
    add(
        scenario(
            "S21",
            "Fortline: student asks to be called after exams",
            org="cy",
            seller="cy.karan",
            path="phone",
            language="english",
            lead={"name": "Tanvi Kulkarni", "phone": "+91 00000 40004", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_F},
            script="""
S: Hi Tanvi, Karan from Fortline Cyber Institute. You asked about the ethical hacking course.
P: Hi. Yes, but I have my final year exams right now. I cannot think about it.
S: Of course. When do your exams finish?
P: On the twentieth of December.
S: Then shall I call you after that, maybe on the twenty-second?
P: Yes, call me on the twenty-second, in the afternoon.
S: Will do. Meanwhile I will email you the course outline so you can look at it after exams.
P: Okay, thank you. All the best.
S: All the best for your exams, Tanvi.
""",
            key={
                "person.name": ["tanvi"],
                "person.role": [["student"]],
                "friction.blocker": [["exam"]],
                "commitment.follow_up": [["22", "twenty-second", "december"]],
                "commitment.seller_promise": [["outline", "email"]],
                "outcome.call_outcome": "callback_requested",
            },
            expect={
                "report": "short_ok",
                "stage": "open_leads",
                "stage_ok": ["open_leads", "interested"],
                "follow_up": {"month_day": [12, 22]},
            },
            covers=["callback", "fortline"],
        )
    )

    # S22 Fortline lost to free YouTube.
    add(
        scenario(
            "S22",
            "Fortline: lost, prefers free YouTube courses",
            org="cy",
            seller="cy.karan",
            path="phone",
            language="english",
            lead={"name": "Irfan Qureshi", "phone": "+91 00000 40005", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_M},
            script="""
S: Hello Irfan, Karan from Fortline Cyber Institute. You downloaded our course brochure last week.
P: Yes, I saw it. Honestly, eighty-five thousand is a lot. Everything is on YouTube for free.
S: A lot is on YouTube, true. What we add is the labs, a mentor, and placement support.
P: I already started a free course on YouTube and one on Coursera. I will finish those first.
S: That is a good start. Would you like me to check back in three months?
P: No, I do not think so. I will do it on my own. Thank you.
S: Understood. All the best, Irfan.
P: Thanks.
""",
            key={
                "person.name": ["irfan"],
                "money.price_quoted": {"amount": 85000},
                "friction.objection": [["youtube", "free", "expensive", "a lot"]],
                "market.alternative": [["youtube", "coursera", "free"]],
                "outcome.call_outcome": "no_sale",
                "forbid": ["commitment.follow_up"],
            },
            expect={"report": "short_ok", "stage": "lost", "stage_ok": ["lost"], "follow_up": None},
            covers=["lost", "fortline"],
        )
    )

    # S23 AC Meta lead who is a job seeker -> junk / not a fit.
    add(
        scenario(
            "S23",
            "Meta lead turns out to be a job seeker",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Deepak Solanki", "phone": "+91 00000 30018", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M2},
            script="""
S: Hello Deepak, Priya from AC Sales Sandbox. You filled our form about sales training for your team.
P: Hello madam. Actually I am looking for a sales job. I thought this form was for a job.
S: Oh I see. So you do not have a business or a team?
P: No madam. I am a fresher. I completed my BCom this year. Do you have any job openings?
S: We are not hiring right now, and this programme is for business owners. I am sorry for the confusion.
P: Okay madam, no problem. If there is any opening please tell me.
S: Sure. All the best, Deepak.
""",
            key={
                "person.name": ["deepak"],
                "person.role": [["fresher", "job", "student", "graduate"]],
                "outcome.call_outcome": "not_a_fit",
                "forbid": ["money.budget", "company.team_size"],
            },
            expect={"report": "short_ok", "stage": "junk", "stage_ok": ["junk", "lost"]},
            covers=["not_a_fit"],
        )
    )

    # S24 AC call after the meeting: meeting done, decision maker brother.
    add(
        scenario(
            "S24",
            "After the demo: meeting done, waiting on the brother",
            org="ac",
            seller="ac.rohan",
            path="phone",
            language="english",
            lead={"name": "Prakash Shetty", "phone": "+91 00000 30019", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_M},
            script="""
S: Hi Prakash, Rohan here. Thank you for the demo yesterday at your office.
P: Thank you Rohan. It was good. My team liked the role plays.
S: Which part did they like most?
P: The objection drills. Customers here always say they will think about it, and my people never knew what to say next.
S: That is the most common one. We spend a full week on it in the programme.
P: Good, because that is where we lose most of our deals.
S: Great to hear. Where do things stand on your side?
P: I am convinced. But my elder brother Mohan runs the Mangalore branch and he wants his team in it too. He is travelling until Thursday.
S: So it would be both branches, Udupi and Mangalore?
P: Yes. Eighteen people in all. Can you send a revised quote for eighteen?
S: I will send it today. With eighteen seats the package comes to about five lakh sixty thousand.
P: Hmm, that is more than I thought. Keep it under five lakh if you can. Mohan will look at the number first.
S: I will see what I can do and send two options. Can we all speak on Friday at five?
P: Friday at five with Mohan, yes.
S: Perfect. Thank you Prakash.
""",
            key={
                "person.name": ["prakash"],
                "company.location": ["udupi", "mangalore"],
                "company.team_size": {"number": 18},
                "decision.maker": [["mohan", "brother"]],
                "money.price_quoted": {"amount": 560000},
                "money.budget": {"amount": 500000},
                "commitment.seller_promise": [["quote", "option"]],
                "meeting": {"weekday": "friday", "hour": 17},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_done",
                "stage_ok": ["meeting_done", "meeting_scheduled", "interested"],
                "follow_up": {"weekday": "friday", "hour": 17},
            },
            covers=["meeting_done"],
        )
    )

    # S25 level changes: the prospect is very quiet (web upload).
    add(
        scenario(
            "S25",
            "Very quiet prospect, level jumps (web upload)",
            org="ac",
            seller="ac.rohan",
            path="web",
            language="english",
            lead={"name": "Shweta Joshi", "phone": "+91 00000 30020", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_F},
            script="""
S: Hello Shweta, Rohan from AC Sales Sandbox, about the training enquiry for your clinic.
P: Hello. Yes. Joshi Dental Clinic, in Thane. I have four front desk people.
S: Front desk people. What do you want them to get better at?
P: When patients call for a price, they just say the price. They do not book an appointment.
S: How many calls does the front desk get in a day?
P: About forty on weekdays. More on Mondays.
S: And roughly how many of those turn into an appointment today?
P: Maybe ten. The rest ask the price and hang up.
S: So converting phone enquiries into appointments.
P: Yes. That is it.
S: We have a short programme for front desk teams. Three weeks, twenty thousand per person.
P: That is fine. Can you start in January?
S: Yes, the January batch starts on the sixth. Shall I block four seats?
P: Block them. I will confirm the names next week.
S: Done. I will send the invoice for eighty thousand.
P: Okay. Thank you.
""",
            key={
                "person.name": ["shweta"],
                "company.name": ["joshi dental"],
                "company.location": ["thane"],
                "company.team_size": {"number": 4},
                "need.primary_pain": [["appointment", "book", "price"]],
                "money.price_quoted": {"amount": 20000, "also": [80000]},
                "decision.timeline": [["january"]],
                "commitment.prospect_promise": [["names", "confirm"]],
                "outcome.call_outcome": "deal_closed",
            },
            expect={"report": True, "stage": "won", "stage_ok": ["won"], "deal_amount": 80000},
            audio={"format": "wav", "levels": {"P": -18, "S": 0, "jumps": True}},
            covers=["level_changes", "web_upload", "won"],
        )
    )

    # S26 Xiaomi AMR narrowband.
    add(
        scenario(
            "S26",
            "Xiaomi recorder AMR (8 kHz narrowband)",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="english",
            lead={"name": "Kiran Pawar", "phone": "+91 00000 30021", "source": "manual"},
            voices={"S": EN_SELLER_F, "P": EN_P_M},
            script="""
S: Hello Kiran, this is Priya from AC Sales Sandbox. You enquired about training for your real estate team.
P: Yes Priya. Pawar Realty, in Pune. We sell flats in new projects. Eleven people in sales.
S: What is the main challenge with the team?
P: Site visits. We get many enquiries but very few come for a site visit. Maybe one in ten.
S: That is a booking problem on the first call. We fix that in the first two weeks of the bootcamp.
P: What is the fee for eleven people?
S: The package for eleven comes to about four lakh ninety-five thousand.
P: Too high. My limit is three and a half lakh.
S: Let me prepare a smaller version, with the first call module and the site visit module only. I will send it tomorrow.
P: Okay. Send it and call me on Wednesday evening.
S: Wednesday evening it is. Thank you Kiran.
""",
            key={
                "person.name": ["kiran"],
                "company.name": ["pawar realty"],
                "company.location": ["pune"],
                "company.team_size": {"number": 11},
                "need.primary_pain": [["site visit", "visit"]],
                "money.price_quoted": {"amount": 495000},
                "money.budget": {"amount": 350000},
                "friction.objection": [["high", "price", "limit"]],
                "commitment.seller_promise": [["smaller", "version", "send"]],
                "commitment.follow_up": [["wednesday"]],
                "outcome.call_outcome": "follow_up_agreed",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"weekday": "wednesday"},
            },
            audio={"format": "amr", "rate": 8000},
            covers=["xiaomi_amr"],
        )
    )

    # S27 stereo variant.
    add(
        scenario(
            "S27",
            "Stereo recording (seller left, prospect right)",
            org="cy",
            seller="cy.karan",
            path="phone",
            language="english",
            lead={"name": "Neeraj Bansal", "phone": "+91 00000 40006", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_M2},
            script="""
S: Hello Neeraj, Karan from Fortline Cyber Institute, about the cloud security course.
P: Hi Karan. Yes. I am a system admin at a hospital in Chandigarh and my manager wants me certified.
S: What does your work involve today, Neeraj?
P: I manage the servers and the patient records system. We moved part of it to the cloud last year.
S: Then the cloud course fits well. It covers access control, logging and incident response.
P: Good. Logging is exactly what our auditors asked about last time.
S: Is the company paying for it?
P: Yes, the hospital will pay, up to sixty thousand. Anything above that I pay myself.
S: The Cloud Security Practitioner course is fifty-five thousand, so it is fully covered.
P: Good. I need the certificate before March, for our audit.
S: The February batch ends on the twenty-eighth, with the exam in the last week.
P: Perfect. Please send the quotation in the hospital's name so I can raise a purchase order.
S: I will send it today. Shall I call you on Monday to check the purchase order?
P: Yes, Monday morning.
""",
            key={
                "person.name": ["neeraj"],
                "person.role": [["system admin", "admin"]],
                "company.location": ["chandigarh"],
                "money.budget": {"amount": 60000},
                "money.price_quoted": {"amount": 55000},
                "decision.timeline": [["march", "audit", "february"]],
                "decision.approver": [["manager", "hospital", "purchase order"]],
                "commitment.seller_promise": [["quotation", "quote"]],
                "commitment.follow_up": [["monday"]],
                "outcome.call_outcome": "follow_up_agreed",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"weekday": "monday"},
            },
            audio={"format": "m4a", "channels": 2},
            covers=["stereo", "fortline"],
        )
    )

    # S28 Marathi-English cold call to a clinic, meeting booked.
    add(
        scenario(
            "S28",
            "Marathi-English cold call, meeting booked",
            org="ac",
            seller="ac.priya",
            path="phone",
            language="marathi-english",
            lead={"name": "Dr Swati Gokhale", "phone": "+91 00000 30022", "source": "manual"},
            voices={"S": {"model": MR, "speaker": 1}, "P": {"model": MR, "speaker": 3}},
            script="""
S: नमस्कार, डॉक्टर स्वाती गोखले बोलत आहात का? मी प्रिया, AC सेल्स सँडबॉक्स मधून.
P: हो, बोला. पण पटकन, माझे पेशंट थांबले आहेत.
S: दोन मिनिटं. तुमच्या क्लिनिक मध्ये रिसेप्शन वर फोन येतात, पण अपॉइंटमेंट कमी बुक होतात का?
P: हो, खरं आहे. पुण्यात आमचं गोखले आय क्लिनिक आहे, तीन रिसेप्शनिस्ट आहेत, पण बुकिंग कमी आहे.
S: दिवसाला किती फोन येतात रिसेप्शन वर?
P: साधारण पन्नास. पण त्यातले फक्त दहा-बारा अपॉइंटमेंट बुक होतात.
S: म्हणजे बरेच पेशंट फक्त माहिती विचारून फोन ठेवतात.
P: हो, नेमकं तेच होतं. आणि रिसेप्शनिस्ट त्यांना परत फोन करत नाहीत.
S: आम्ही रिसेप्शन टीम साठी तीन आठवड्यांचं ट्रेनिंग देतो.
P: ठीक आहे. मला सविस्तर समजून घ्यायचं आहे. शनिवारी दुपारी तीन वाजता क्लिनिक वर या.
S: शनिवारी तीन वाजता, नक्की येते. धन्यवाद डॉक्टर.
P: धन्यवाद.
""",
            key={
                "person.name": ["swati", "स्वाती"],
                "person.role": [["doctor", "डॉक्टर", "dr"]],
                "company.name": ["gokhale eye", "गोखले आय"],
                "company.location": ["pune", "पुण"],
                "company.team_size": {"number": 3},
                "need.primary_pain": [["appointment", "booking", "बुकिंग", "अपॉइंटमेंट"]],
                "meeting": {"weekday": "saturday", "hour": 15},
                "outcome.call_outcome": "meeting_scheduled",
            },
            expect={
                "report": True,
                "stage": "meeting_scheduled",
                "stage_ok": ["meeting_scheduled"],
                "follow_up": {"weekday": "saturday", "hour": 15},
            },
            audio={"format": "amr", "rate": 8000},
            covers=["marathi_english", "cold_positive", "meeting_booked"],
        )
    )

    # S29 Hindi Fortline student, counselling.
    add(
        scenario(
            "S29",
            "Hindi call: parent asks about the course for his son",
            org="cy",
            seller="cy.karan",
            path="phone",
            language="hindi",
            lead={"name": "Suresh Mishra", "phone": "+91 00000 40007", "source": "manual"},
            voices={"S": HI_M2, "P": HI_M},
            script="""
S: नमस्ते, सुरेश मिश्रा जी? मैं करण, फोर्टलाइन साइबर इंस्टीट्यूट से.
P: हाँ जी नमस्ते. मैंने अपने बेटे के लिए पूछा था. वो बीएससी कर चुका है.
S: बहुत अच्छा. बेटे का नाम क्या है, और कहाँ रहते हैं आप?
P: बेटे का नाम अमन है. हम भोपाल में रहते हैं.
S: अमन ने पहले कंप्यूटर में कोई कोर्स किया है?
P: हाँ, कॉलेज में नेटवर्किंग का एक छोटा कोर्स किया था. उसे यही काम पसंद है.
S: तब तो उसके लिए अच्छा रहेगा. हर हफ्ते लैब में प्रैक्टिकल होता है.
P: अच्छा, ये अच्छी बात है.
S: अमन के लिए एथिकल हैकिंग कोर्स अच्छा रहेगा. छह महीने का है, फ़ीस साठ हज़ार.
P: साठ हज़ार ठीक है, पर नौकरी की गारंटी है क्या?
S: गारंटी नहीं, पर हम प्लेसमेंट में पूरी मदद करते हैं. पिछले बैच में सत्तर प्रतिशत को नौकरी मिली.
P: ठीक है. अमन से एक बार बात कर लीजिए. रविवार को शाम छह बजे फ़ोन कीजिए, वो घर पर होगा.
S: रविवार शाम छह बजे, अमन से बात करूँगा. धन्यवाद मिश्रा जी.
P: धन्यवाद.
""",
            key={
                "person.name": ["suresh", "सुरेश"],
                "person.other_party": [["aman", "अमन", "son", "बेटे"]],
                "company.location": ["bhopal", "भोपाल"],
                "money.price_quoted": {"amount": 60000},
                "friction.question": [["guarantee", "गारंटी", "job", "नौकरी", "placement"]],
                "commitment.follow_up": [["sunday", "रविवार"]],
                "meeting": {"weekday": "sunday", "hour": 18},
                "outcome.call_outcome": "callback_requested",
            },
            expect={
                "report": True,
                "stage": "interested",
                "stage_ok": ["interested", "open_leads"],
                "follow_up": {"weekday": "sunday", "hour": 18},
            },
            covers=["hindi", "fortline", "callback"],
        )
    )

    # S30 lost to a competitor.
    add(
        scenario(
            "S30",
            "Lost: already signed with another training firm",
            org="ac",
            seller="ac.rohan",
            path="phone",
            language="english",
            lead={"name": "Arvind Menon", "phone": "+91 00000 30023", "source": "manual"},
            voices={"S": EN_SELLER_M, "P": EN_P_M2},
            script="""
S: Hello Arvind, Rohan from AC Sales Sandbox. Following up on the proposal we sent last week.
P: Hi Rohan. I should have called you. We went with another firm, Peak Performance Trainers.
S: Thank you for telling me. May I ask what made the difference?
P: Price, mainly. They quoted one lakh twenty for the team, yours was one lakh ninety. And they could start next week.
S: That is fair feedback. Would it be all right if I check in after their programme ends, to see how it went?
P: Sure, you can call me in March. No promises though.
S: No promises needed. Thank you Arvind, and all the best.
P: Thanks Rohan.
""",
            key={
                "person.name": ["arvind"],
                "market.competitor": [["peak performance"]],
                "friction.objection": [["price", "cheaper", "start"]],
                "money.price_quoted": {"amount": 190000, "also": [120000]},
                "commitment.follow_up": [["march"]],
                "outcome.call_outcome": "no_sale",
            },
            expect={
                "report": "short_ok",
                "stage": "lost",
                "stage_ok": ["lost"],
                "lost_reason": ["competitor", "price", "peak"],
            },
            covers=["lost_competitor"],
        )
    )
    assert len(out) == 30 and len({s["id"] for s in out}) == 30
    phones = [s["lead"]["phone"] for s in out]
    assert len(set(phones)) == len(phones)
    assert all(p.startswith("+91 00000 ") for p in phones)
    return out


def words(s: dict[str, Any]) -> int:
    return sum(len(t[1].split()) for t in s["turns"])


def build(out_dir: str) -> None:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    for s in library():
        (root / f"{s['id']}.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(s["id"], s["language"], s["path"], words(s), "words", s["title"])


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "build":
        raise SystemExit("usage: scenarios.py build <out-dir>")
    build(sys.argv[2])
