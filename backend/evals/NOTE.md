**What is in this report, and what is not.** The published evaluation runs
against public figures only — people whose birth data is already a matter of
record — so that no private individual's birth details or readings are
published along with it. That has one consequence worth stating plainly
before you read the numbers.

**Every chart here has an unverified birth time.** Public birth times are
almost never reliable, and an uncertain birth time moves the lagna, the
houses and every dasha boundary. The hit rate below is therefore a *floor*,
not a fair measurement of the method: it is what the agent manages when it
does not really know the chart. The birth-time-known row reads n=0 for
exactly this reason, not because the agent scored zero.

To measure the number that matters, supply charts whose birth time and
outcomes you actually know, in `evals/golden_set.local.json` (gitignored,
same shape as `golden_set.json`). On a private run of two birth-time-known
charts the hit rate within one year was 6 of 7, against 3 of 22 here. Seven
questions is far too small to quote as a result — but the gap between the
two is the size of the birth-time problem, and it is the single biggest
factor in whether this agent is any good.

**The answers were collected across several builds** during a day of fixes,
because re-asking all of them costs about Rs 160 each time. The defect list
at the end says which are fixed and which are open; anything marked fixed
was verified against the deployed service.
