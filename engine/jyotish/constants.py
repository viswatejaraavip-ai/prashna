"""Constants for Vedic (Jyotish) astrology calculations."""

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

SIGN_LORDS = [
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
]

# Planet names in traditional order (Sun..Saturn, then the nodes)
PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

NAKSHATRA_SPAN = 360.0 / 27.0  # 13°20'

# Vimshottari dasha: lord of each nakshatra follows this 9-lord cycle
# starting from Ashwini (Ketu).
DASHA_SEQUENCE = [
    ("Ketu", 7), ("Venus", 20), ("Sun", 6), ("Moon", 10), ("Mars", 7),
    ("Rahu", 18), ("Jupiter", 16), ("Saturn", 19), ("Mercury", 17),
]
DASHA_TOTAL_YEARS = 120
YEAR_DAYS = 365.25

TITHIS = [
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Purnima/Amavasya",
]

YOGAS = [
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda",
    "Sukarma", "Dhriti", "Shula", "Ganda", "Vriddhi", "Dhruva",
    "Vyaghata", "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyan",
    "Parigha", "Shiva", "Siddha", "Sadhya", "Shubha", "Shukla",
    "Brahma", "Indra", "Vaidhriti",
]

KARANA_MOVABLE = ["Bava", "Balava", "Kaulava", "Taitila", "Gara", "Vanija", "Vishti"]
KARANA_FIXED_END = ["Shakuni", "Chatushpada", "Naga"]  # karanas 58, 59, 60
KARANA_FIXED_START = "Kimstughna"  # karana 1

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# The 16 classical (Shodasavarga) divisional charts and what they signify.
VARGA_SIGNIFICATIONS = {
    "D1": "Rasi - body, physical self, overall life",
    "D2": "Hora - wealth and sustenance",
    "D3": "Drekkana - siblings, courage",
    "D4": "Chaturthamsa - fortune, property, home",
    "D7": "Saptamsa - children, progeny",
    "D9": "Navamsa - spouse, marriage, dharma, inner strength",
    "D10": "Dasamsa - career, profession, status",
    "D12": "Dwadasamsa - parents, lineage",
    "D16": "Shodasamsa - vehicles, comforts, happiness",
    "D20": "Vimsamsa - spiritual life, worship",
    "D24": "Chaturvimsamsa - education, learning",
    "D27": "Bhamsa - strengths and weaknesses, vitality",
    "D30": "Trimsamsa - misfortunes, character flaws",
    "D40": "Khavedamsa - auspicious/inauspicious effects (maternal)",
    "D45": "Akshavedamsa - general conduct (paternal)",
    "D60": "Shashtiamsa - past-life karma, overall (most granular)",
}

VARGA_LIST = list(VARGA_SIGNIFICATIONS.keys())
