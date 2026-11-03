"""A lead's city as people type it ("Poona", "pune city", "PCMC", "पुणे") read as one place,
for the owner's "top cities" (owner, 2 Nov 2026). The typed city stays on the lead as it is;
this only reads it. A value that names no known place, or two different towns, is not
placed and is counted as such, never guessed. Pure: no database, no network."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Final

MH: Final = "Maharashtra"

# Canonical city -> its spellings (lower case, letters and spaces). A wide place (a metro or
# a district) gives way to a town named beside it: "Baramati, Pune" is Baramati.
CITIES: Final[dict[str, tuple[str, ...]]] = {
    "Pune": (
        "pune",
        "puna",
        "poona",
        "pun",
        "punr",
        "punech",
        "puneee",
        "pune city",
        "pcmc",
        "pimpri chinchwad",
        "pimpri",
        "chinchwad",
        "hadapsar",
        "wagholi",
        "kothrud",
        "baner",
        "kharadi",
        "hinjewadi",
        "wakad",
        "viman nagar",
        "kondhwa",
        "katraj",
        "bhosari",
        "nigdi",
    ),
    "Mumbai": (
        "mumbai",
        "bombay",
        "mum",
        "mumbai city",
        "mumbai suburban",
        "mumbai suburbs",
        "andheri",
        "borivali",
        "mulund",
        "ghatkopar",
        "dadar",
        "bandra",
        "malad",
        "goregaon",
    ),
    "Navi Mumbai": (
        "navi mumbai",
        "navimumbai",
        "new mumbai",
        "vashi",
        "nerul",
        "airoli",
        "belapur",
        "cbd belapur",
        "kharghar",
        "ghansoli",
        "kopar khairane",
        "sanpada",
        "seawoods",
        "ulwe",
    ),
    "Thane": ("thane",),
    "Ahilyanagar": (
        "ahmednagar",
        "ahmadnagar",
        "ahemadnagar",
        "ahemdnagar",
        "ahmed nagar",
        "ahilyanagar",
        "ahilya nagar",
    ),
    "Kolhapur": ("kolhapur", "kohalpur"),
    "Latur": ("latur", "latoor"),
    "Nashik": ("nashik", "nasik"),
    "Solapur": ("solapur", "sholapur"),
    "Satara": ("satara",),
    "Sangli": ("sangli",),
    "Jalgaon": ("jalgaon", "jalgav"),
    "Chhatrapati Sambhajinagar": (
        "chhatrapati sambhajinagar",
        "chatrapati sambhajinagar",
        "sambhaji nagar",
        "sambhajinagar",
        "aurangabad",
    ),
    "Nagpur": ("nagpur",),
    "Nanded": ("nanded",),
    "Amravati": ("amravati",),
    "Akola": ("akola",),
    "Dharashiv": ("dharashiv", "osmanabad"),
    "Beed": ("beed",),
    "Ratnagiri": ("ratnagiri",),
    "Sindhudurg": ("sindhudurg",),
    "Ichalkaranji": ("ichalkaranji", "ichalkarnji", "ichalakaranji"),
    "Baramati": ("baramati",),
    "Lonavala": ("lonavala", "lonavla", "lonawala"),
    "Chakan": ("chakan",),
    "Shirur": ("shirur",),
    "Daund": ("daund",),
    "Talegaon Dabhade": ("talegaon dabhade",),
    "Karad": ("karad",),
    "Miraj": ("miraj",),
    "Panvel": ("panvel",),
    "Kalyan": ("kalyan",),
    "Dombivli": ("dombivli", "dombivili"),
    "Vasai-Virar": ("vasai", "virar", "nalasopara"),
    "Bhiwandi": ("bhiwandi",),
    "Malegaon": ("malegaon",),
    "Pandharpur": ("pandharpur",),
    "Shirdi": ("shirdi",),
    "Sangamner": ("sangamner",),
    "Alibag": ("alibag", "alibaug"),
    "Panaji": ("panaji", "panjim"),
    "Margao": ("margao", "madgaon"),
    "Mapusa": ("mapusa",),
    "Delhi": ("delhi", "new delhi"),
    "Gurugram": ("gurugram", "gurgaon"),
    "Noida": ("noida", "greater noida"),
    "Ghaziabad": ("ghaziabad",),
    "Faridabad": ("faridabad",),
    "Bengaluru": ("bengaluru", "bangalore", "banglore"),
    "Belagavi": ("belagavi", "belgaum"),
    "Hubballi": ("hubballi", "hubli", "dharwad"),
    "Mysuru": ("mysuru", "mysore"),
    "Mangaluru": ("mangaluru", "mangalore"),
    "Chennai": ("chennai", "madras"),
    "Coimbatore": ("coimbatore",),
    "Madurai": ("madurai",),
    "Hyderabad": ("hyderabad", "secunderabad"),
    "Visakhapatnam": ("visakhapatnam", "vizag"),
    "Vijayawada": ("vijayawada",),
    "Kolkata": ("kolkata", "calcutta"),
    "Ahmedabad": ("ahmedabad",),
    "Surat": ("surat",),
    "Vadodara": ("vadodara", "baroda"),
    "Rajkot": ("rajkot",),
    "Jaipur": ("jaipur",),
    "Udaipur": ("udaipur",),
    "Lucknow": ("lucknow",),
    "Kanpur": ("kanpur",),
    "Varanasi": ("varanasi", "banaras"),
    "Prayagraj": ("prayagraj", "allahabad"),
    "Agra": ("agra",),
    "Indore": ("indore",),
    "Bhopal": ("bhopal",),
    "Raipur": ("raipur",),
    "Patna": ("patna",),
    "Ranchi": ("ranchi",),
    "Bhubaneswar": ("bhubaneswar",),
    "Guwahati": ("guwahati",),
    "Chandigarh": ("chandigarh", "mohali", "panchkula"),
    "Ludhiana": ("ludhiana",),
    "Amritsar": ("amritsar",),
    "Dehradun": ("dehradun",),
    "Kochi": ("kochi", "cochin", "ernakulam"),
    "Thiruvananthapuram": ("thiruvananthapuram", "trivandrum"),
}
WIDE: Final[frozenset[str]] = frozenset(
    {
        "Pune",
        "Mumbai",
        "Navi Mumbai",
        "Thane",
        "Ahilyanagar",
        "Kolhapur",
        "Latur",
        "Nashik",
        "Solapur",
        "Satara",
        "Sangli",
        "Jalgaon",
        "Sindhudurg",
        "Delhi",
        "Bengaluru",
        "Hyderabad",
        "Chennai",
        "Kolkata",
    }
)
DEVANAGARI: Final[dict[str, str]] = {
    "पुणे": "pune",
    "पूणे": "pune",
    "मुंबई": "mumbai",
    "ठाणे": "thane",
    "नाशिक": "nashik",
    "कोल्हापूर": "kolhapur",
    "कोल्हापुर": "kolhapur",
    "सातारा": "satara",
    "सोलापूर": "solapur",
    "नागपूर": "nagpur",
    "अमरावती": "amravati",
    "सांगली": "sangli",
    "लातूर": "latur",
}
# Words that say nothing about the place ("Pune, Maharashtra, India", "Tal. Daund").
NOISE: Final[frozenset[str]] = frozenset(
    {
        "maharashtra",
        "india",
        "ms",
        "mh",
        "dist",
        "district",
        "di",
        "ta",
        "tal",
        "taluka",
        "at",
        "post",
        "city",
        "west",
        "east",
        "north",
        "south",
    }
)

_ALIAS: Final[dict[str, str]] = {
    alias: city for city, aliases in CITIES.items() for alias in aliases
}
_PATTERN: Final = re.compile(
    r"\b(" + "|".join(sorted((re.escape(a) for a in _ALIAS), key=len, reverse=True)) + r")\b"
)


def _key(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw or "")
    for word, latin in DEVANAGARI.items():
        text = text.replace(word, f" {latin} ")
    text = re.sub(r"[^a-z]+", " ", text.lower())
    return " ".join(word for word in text.split() if word not in NOISE)


def place(raw: str | None) -> str | None:
    """The one city a typed value names, or None when it names none or two towns."""
    key = _key(raw or "")
    if not key:
        return None
    hits = {_ALIAS[match.group(1)] for match in _PATTERN.finditer(key)}
    if not hits:
        return None
    towns = {city for city in hits if city not in WIDE}
    if len(towns) == 1:
        return next(iter(towns))
    if towns:
        return None
    if len(hits) == 1:
        return next(iter(hits))
    # "Pimpri Chinchwad, Pune" reads Pune; Pune and Mumbai together name no one place.
    return None


def top_cities(cities: Iterable[str | None], limit: int = 5) -> tuple[list[tuple[str, int]], int]:
    """The most common places, most first, and how many cities could not be placed (an
    empty city is neither)."""
    placed: Counter[str] = Counter()
    unplaced = 0
    for raw in cities:
        if not raw or not raw.strip():
            continue
        city = place(raw)
        if city is None:
            unplaced += 1
        else:
            placed[city] += 1
    return sorted(placed.items(), key=lambda item: (-item[1], item[0]))[:limit], unplaced
