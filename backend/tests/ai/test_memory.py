"""Durable memory may only hold what the CLIENT said.

The live evaluation (backend/evals/RESULTS.md) found the agent storing its
own predictions as the client's biography and then reading them back as
history. The Indira Gandhi profile held "Marriage occurred between February
and October 2021" -- its own wrong answer from an earlier session -- and the
next answer opened "Based on the chart data and your session memory noting
marriage occurred between late 2021 and mid-2022", to a client who had never
said anything of the kind. A private profile picked up two more of the
agent's own wrong date windows the same way, plus two chart placements --
each of them then a permanent "fact" about a real person.

memory.SYSTEM had forbidden exactly this from the start ("Never store
predictions, chart placements or anything the astrologer said"). Flash
ignored it. So the rule is enforced in Python instead: a new fact is kept
only if the quote it carries is really in what the client typed this turn.
"""

import pytest

from app.ai import memory

Q_TE = "నేను మొదటిసారి విదేశాలకు ఎప్పుడు వెళ్ళాను? నేను సాఫ్ట్‌వేర్ ఇంజనీర్‌ని."
ANSWER = "మీరు 2016-2017లో విదేశాలకు వెళ్ళారు."


def fact(f, said):
    return {"fact": f, "said": said}


# ---------------- what the client actually said is kept ----------------

def test_a_fact_the_client_stated_is_kept():
    kept, dropped = memory.grounded(
        [fact("Works as a software engineer", "నేను సాఫ్ట్‌వేర్ ఇంజనీర్‌ని")],
        [], Q_TE)
    assert kept == ["Works as a software engineer"] and dropped == 0


def test_the_quote_is_matched_across_whitespace_and_case():
    kept, _ = memory.grounded(
        [fact("Lives in Kochi", "i live  in\nKOCHI")], [], "I live in Kochi now")
    assert kept == ["Lives in Kochi"]


def test_facts_already_stored_survive_a_turn_that_does_not_repeat_them():
    """The client says "I am a teacher" once, not in every question."""
    stored = ["Works as a teacher in Madurai"]
    kept, dropped = memory.grounded(
        [fact("Works as a teacher in Madurai", "")], stored, "When will I marry?")
    assert kept == stored and dropped == 0


# ---------------- the astrologer's own words are not ----------------

def test_a_prediction_mined_out_of_the_answer_is_dropped():
    """The exact defect: the reply's date window offered as a client fact."""
    kept, dropped = memory.grounded(
        [fact("First foreign travel occurred around 2016-2017",
              "మీరు 2016-2017లో విదేశాలకు వెళ్ళారు")],   # quoted from the ANSWER
        [], Q_TE)
    assert kept == [] and dropped == 1


def test_a_chart_placement_is_dropped():
    kept, dropped = memory.grounded(
        [fact("Ascendant is Virgo (Kanya)", "Ascendant is Virgo")], [], Q_TE)
    assert kept == [] and dropped == 1


def test_a_fact_with_no_quote_at_all_is_dropped():
    kept, dropped = memory.grounded([fact("Native is married", "")], [], Q_TE)
    assert kept == [] and dropped == 1


def test_a_bare_string_is_never_trusted():
    """The pre-grounding shape. Unless it is already stored, it has no
    provenance and cannot be told from an invented one."""
    kept, dropped = memory.grounded(["Native is married"], [], Q_TE)
    assert kept == [] and dropped == 1
    kept, dropped = memory.grounded(["Native is married"], ["Native is married"], Q_TE)
    assert kept == ["Native is married"] and dropped == 0


def test_the_indira_memory_could_not_be_written_today():
    """Verbatim from the profile the evaluation found."""
    poisoned = ["Native is married",
                "Marriage occurred between February and October 2021",
                "First child born in 2023",
                "Reached peak of public career around 2017-2018",
                "Experienced greatest public crisis and reputation loss in 2020"]
    asked = "In which year and which month did this native marry?"
    kept, dropped = memory.grounded(
        [fact(f, "the chart shows " + f) for f in poisoned], [], asked)
    assert kept == [] and dropped == len(poisoned)


# ---------------- housekeeping ----------------

def test_duplicates_and_overflow_are_trimmed():
    said = "I am a nurse in Salem and I have two children"
    raw = [fact("Works as a nurse", said), fact("works   as a NURSE", said)]
    raw += [fact("Detail %d" % i, said) for i in range(12)]
    kept, _ = memory.grounded(raw, [], said)
    assert len(kept) == memory.MAX_FACTS
    assert kept[0] == "Works as a nurse" and "works   as a NURSE" not in kept


def test_a_fact_is_cut_to_the_stored_length():
    said = "x" * 400
    kept, _ = memory.grounded([fact("y" * 400, said)], [], said)
    assert len(kept[0]) == 160


def test_update_keeps_only_grounded_facts_and_records_the_drop(monkeypatch):
    """End to end through the Flash call, with the model misbehaving."""
    from app.ai import llm
    out = {"summary": "Asked about travel.",
           "facts": [fact("Works as a software engineer", "సాఫ్ట్‌వేర్ ఇంజనీర్‌ని"),
                     fact("First foreign travel around 2016-2017",
                          "మీరు 2016-2017లో విదేశాలకు వెళ్ళారు")]}
    monkeypatch.setattr(llm, "flash",
                        lambda *a, **k: (out, llm.Stage(name="memory")))
    summary, facts, stage = memory.update(
        summary="", facts=[], question=Q_TE, answer=ANSWER, lang="te")
    assert facts == ["Works as a software engineer"]
    assert stage.detail["facts_dropped"] == 1 and stage.detail["facts_kept"] == 1
    assert summary == "Asked about travel."


def test_a_failed_memory_call_keeps_the_old_facts(monkeypatch):
    from app.ai import llm

    def boom(*a, **k):
        raise RuntimeError("flash down")

    monkeypatch.setattr(llm, "flash", boom)
    _, facts, stage = memory.update(summary="s", facts=["Works as a teacher"],
                                    question=Q_TE, answer=ANSWER, lang="te")
    assert facts == ["Works as a teacher"] and stage.detail["error"]
