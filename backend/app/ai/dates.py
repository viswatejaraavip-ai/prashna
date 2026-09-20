"""Birth date and age: the arithmetic that keeps a dated answer honest.

The live evaluation (backend/evals/RESULTS.md) found that the agent timed
past events from *today* instead of from the chart: of 23 past events it
dated, 12 landed within five years of today although only one truly did. It
told a client born in 1993 that his career started in 2004 (age 11), and a
1917 chart that she married in 2021 (age 104). The reasoner was given the
present moment but never the client's birth date, so an absurd age was
literally not computable from what it had.

Two things live here, one for each end of the query:

* `born_line()` — the fact the models were missing, in the same shape for
  the facts brief and for the reasoner: date of birth and age today.
* `implausible_dates()` — a free post-check on the finished reply. It is a
  detector, not a filter: it says "this answer dates something before the
  client was born, or at an age no one reaches", which is always a bug in
  the reading. It is recorded in the trace and logged; nothing is rewritten,
  because rewriting would cost another Opus call and could only make the
  answer later, not righter.
"""

import re
from datetime import date
from typing import Dict, List, Optional

from . import clock

# Above this, a year in a reading is not a life event of a living client: it
# is the model having lost track of who it is reading for.
MAX_PLAUSIBLE_AGE = 100
# Years outside this range are not dates in an astrology reading.
MIN_YEAR, MAX_YEAR = 1800, 2199

_YEAR = re.compile(r"(?<![\d.,])(1[89]\d\d|2[01]\d\d)(?![\d])")
# "1985-2006", "2004 – 2022": a dasha period, not a dated event. Vimshottari
# starts at the balance of the birth nakshatra and Kalachakra earlier still,
# so a period that opens before the client was born is the engine's own fact
# and must not be reported as a defect.
_RANGE = re.compile(r"(?<![\d.,])(1[89]\d\d|2[01]\d\d)\s*[-–—]{1,2}\s*"
                    r"(1[89]\d\d|2[01]\d\d)(?![\d])")

# Every script the app speaks writes digits its own way; the model sometimes
# uses them. Fold them to ASCII before looking for years.
_DIGIT_BASES = (0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66,
                0x0CE6, 0x0D66, 0x0E50, 0x06F0, 0x0660)
_FOLD = {base + d: ord("0") + d for base in _DIGIT_BASES for d in range(10)}


def fold_digits(text: str) -> str:
    """Devanagari/Telugu/Tamil/... digits -> ASCII, so years are findable."""
    return (text or "").translate(_FOLD)


def years_in(text: str) -> List[int]:
    """Every four-digit year the reply names, in order, without duplicates."""
    out: List[int] = []
    for m in _YEAR.finditer(fold_digits(text)):
        y = int(m.group(1))
        if MIN_YEAR <= y <= MAX_YEAR and y not in out:
            out.append(y)
    return out


def birth_date(profile: Optional[Dict]) -> Optional[date]:
    """The profile's date of birth, or None if it is missing or unreadable."""
    raw = str(((profile or {}).get("birth") or {}).get("date") or "")[:10]
    try:
        y, m, d = (int(x) for x in raw.split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def age_on(born: date, when: date) -> int:
    """Completed years, the way a person states their own age."""
    return when.year - born.year - ((when.month, when.day) < (born.month, born.day))


def age_today(profile: Optional[Dict], now: Optional[date] = None) -> Optional[int]:
    born = birth_date(profile)
    if born is None:
        return None
    return age_on(born, now or clock.now().date())


def born_line(profile: Optional[Dict], now: Optional[date] = None) -> str:
    """One line naming the date of birth and the age today, or "" if unknown.

    Both models get this string verbatim: the brief so it can tag periods
    with an age, the reasoner so every window it proposes can be checked
    against one."""
    born = birth_date(profile)
    if born is None:
        return ""
    today = now or clock.now().date()
    return ("Client born: %d %s %d (%s); age today %d."
            % (born.day, born.strftime("%B"), born.year, born.isoformat(),
               age_on(born, today)))


def implausible_dates(reply: str, profile: Optional[Dict],
                      now: Optional[date] = None) -> List[Dict]:
    """Years in `reply` that cannot belong to this client's life.

    Deliberately narrow, so that what it reports is always a real defect:
    a year before the client was born, or one that would make them older
    than `MAX_PLAUSIBLE_AGE`. A reading that merely picked the wrong decade
    is not caught here — only one that is impossible. Two known limits: the
    opening year of a dated period ("Kalachakra 1985-2006") is exempt,
    because the engine's own periods legitimately start before birth; and an
    event dated at, say, 82 is implausible for most lives but not impossible,
    so it passes. This detects the worst of the defect, not all of it."""
    born = birth_date(profile)
    if born is None:
        return []
    text = fold_digits(reply)
    periods = {int(m.group(1)) for m in _RANGE.finditer(text)
               if int(m.group(2)) >= born.year}
    out: List[Dict] = []
    for y in years_in(reply):
        age = y - born.year
        if y < born.year and y not in periods:
            out.append({"year": y, "age": age, "why": "before_birth"})
        elif age > MAX_PLAUSIBLE_AGE:
            out.append({"year": y, "age": age, "why": "implausible_age"})
    return out


def check(reply: str, profile: Optional[Dict],
          now: Optional[date] = None) -> Optional[Dict]:
    """Trace-shaped summary of `implausible_dates`, or None when clean."""
    bad = implausible_dates(reply, profile, now)
    if not bad:
        return None
    return {"born": birth_date(profile).isoformat(), "bad": bad[:6],
            "count": len(bad)}
