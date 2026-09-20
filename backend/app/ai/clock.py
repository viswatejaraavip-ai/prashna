"""One source of "now" for every model call in the pipeline.

A consultation is anchored in time: "the coming months", "this year", "the
dasha running now" only mean something relative to a date. Without being
told, a model answers from whenever its training data ends — which for a
launched app is silently, confidently wrong. So every stage that can reason
about time is handed the same stamp, produced here:

    planner   `today` in the JSON payload
    executor  the brief's "Now:" line, and the year prune() windows periods around
    reasoner  the "Now:" line Opus anchors every date on
    memory    so the rolling summary records absolute, not relative, times

The app's users and the engine's dasha/transit windows are all in India, so
the canonical zone is IST. IST has never observed DST, so a fixed +05:30
offset is exact and needs no tzdata on the container.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30), "IST")

# Tests freeze time by setting this to an ISO-8601 instant.
_FROZEN_ENV = "AI_CLOCK_FROZEN"
_frozen: Optional[datetime] = None


def freeze(when: Optional[datetime]) -> None:
    """Pin `now()` (tests only). Pass None to resume the real clock."""
    global _frozen
    _frozen = when


def now() -> datetime:
    """Current instant in IST."""
    if _frozen is not None:
        return _frozen.astimezone(IST)
    env = os.environ.get(_FROZEN_ENV, "")
    if env:
        try:
            return datetime.fromisoformat(env).astimezone(IST)
        except ValueError:
            pass
    return datetime.now(timezone.utc).astimezone(IST)


def today_iso() -> str:
    """YYYY-MM-DD in IST."""
    return now().strftime("%Y-%m-%d")


def year() -> int:
    return now().year


def stamp(with_time: bool = True) -> str:
    """Human, unambiguous, and the same string in every stage.

    e.g. "Saturday, 20 September 2026, 14:35 IST (2026-09-20)". The ISO date
    is repeated so the model can copy it into date arithmetic without
    re-parsing the prose."""
    n = now()
    # %-d is not portable; build the day number by hand.
    pretty = "%s, %d %s %d" % (n.strftime("%A"), n.day, n.strftime("%B"), n.year)
    if with_time:
        pretty += ", %s IST" % n.strftime("%H:%M")
    return "%s (%s)" % (pretty, n.strftime("%Y-%m-%d"))
