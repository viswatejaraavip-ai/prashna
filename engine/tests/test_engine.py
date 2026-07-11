"""Smoke tests for the Jyotish engine.

Validation reference: India independence chart (Aug 15, 1947, 00:00 IST,
New Delhi 28.6139N 77.2090E, Lahiri). Widely published values:
  Lagna ~ 7-8 Taurus, Moon in Cancer (Pushya), Sun in Cancer ~28,
  Rahu in Taurus, Saturn in Cancer, first mahadasha lord Saturn
  (Moon in Pushya -> Saturn).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jyotish import api  # noqa: E402

INDIA = {
    "year": 1947, "month": 8, "day": 15, "hour": 0, "minute": 0,
    "latitude": 28.6139, "longitude": 77.2090, "tz_name": "Asia/Kolkata",
}


def test_birth_chart():
    chart = api.birth_chart(INDIA)
    asc = chart["ascendant"]
    assert asc["sign"] == "Taurus", "expected Taurus lagna, got %s" % asc["sign"]
    assert 5 < asc["degrees_in_sign"] < 10, asc["degrees_in_sign"]
    assert chart["planets"]["Moon"]["sign"] == "Cancer"
    assert chart["planets"]["Moon"]["nakshatra"]["name"] == "Pushya"
    assert chart["planets"]["Sun"]["sign"] == "Cancer"
    assert chart["planets"]["Saturn"]["sign"] == "Cancer"
    assert chart["planets"]["Rahu"]["sign"] == "Taurus"
    print("birth_chart OK  (Lagna %s %s, Moon %s/%s)" % (
        asc["dms"], asc["sign"],
        chart["planets"]["Moon"]["sign"],
        chart["planets"]["Moon"]["nakshatra"]["name"]))


def test_vargas():
    out = api.all_vargas(INDIA)
    assert set(out["charts"].keys()) == {
        "D1", "D2", "D3", "D4", "D7", "D9", "D10", "D12",
        "D16", "D20", "D24", "D27", "D30", "D40", "D45", "D60"}
    d9 = api.varga_chart(INDIA, "D9")
    assert d9["varga"] == "D9"
    assert all("sign" in v for v in d9["placements"].values())
    print("vargas OK  (D9 lagna: %s)" % d9["ascendant_sign"])


def test_dasha():
    tree = api.dasha_periods(INDIA, levels=2)
    assert tree["birth_lord"] == "Saturn", tree["birth_lord"]
    assert len(tree["mahadashas"]) == 9
    assert len(tree["mahadashas"][0]["antardashas"]) == 9
    now = api.current_dasha(INDIA)
    assert "mahadasha" in now
    print("dasha OK  (birth lord %s, balance %.2fy; now: %s/%s)" % (
        tree["birth_lord"], tree["balance_years_at_birth"],
        now["mahadasha"]["lord"], now["antardasha"]["lord"]))


def test_bhava_and_panchanga():
    bhava = api.bhava_chart(INDIA)
    assert len(bhava["bhava_madhya"]) == 12
    assert set(bhava["placements"].keys()) >= {"Sun", "Moon", "Saturn"}
    p = api.panchanga_for(INDIA)
    assert p["tithi"]["paksha"] in ("Shukla", "Krishna")
    t = api.transits()
    assert len(t["planets"]) == 9
    print("bhava+panchanga OK  (tithi %s %s, vara %s)" % (
        p["tithi"]["paksha"], p["tithi"]["name"], p["vara"]))


def test_kp():
    out = api.kp_chart(INDIA)
    assert len(out["cusps"]) == 12
    assert set(out["planets"].keys()) == {
        "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"}
    for row in out["cusps"]:
        for key in ("sign_lord", "star_lord", "sub_lord", "sub_sub_lord"):
            assert row[key] in ("Sun", "Moon", "Mars", "Mercury", "Jupiter",
                                "Venus", "Saturn", "Rahu", "Ketu"), row
    # Sub-lord boundary sanity: start of Ashwini (0 deg) is Ketu's own sub.
    from jyotish import kp as kp_mod
    assert kp_mod.sub_lord(0.0) == "Ketu"
    # First sub of Ashwini spans 7/120 * 13d20' = 0d46'40"; just past it -> Venus.
    assert kp_mod.sub_lord(0.7778) == "Venus"
    assert kp_mod.star_lord(0.0) == "Ketu"
    m = out["planets"]["Moon"]
    print("kp OK  (Moon: %s star %s/%s sub %s)" % (
        m["sign"], m["star"], m["star_lord"], m["sub_lord"]))


def test_ashtakavarga():
    from jyotish.ashtakavarga import AV_PLANETS, BAV_TOTALS, BENEFIC_PLACES
    # Classical checksums hold for the tables themselves.
    for planet in AV_PLANETS:
        total = sum(len(h) for h in BENEFIC_PLACES[planet].values())
        assert total == BAV_TOTALS[planet], (planet, total)
    assert sum(BAV_TOTALS.values()) == 337

    out = api.ashtakavarga_chart(INDIA)
    for planet in AV_PLANETS:
        assert out["bav_totals"][planet] == BAV_TOTALS[planet]
    assert out["sav_total"] == 337
    assert all(0 <= v <= 8 for v in out["bav"]["Sun"].values())
    print("ashtakavarga OK  (SAV total %d; SAV Aries %d)" % (
        out["sav_total"], out["sav"]["Aries"]))


def test_panchanga_now():
    out = api.panchanga_now(28.6139, 77.2090, "Asia/Kolkata")
    assert out["tithi"]["paksha"] in ("Shukla", "Krishna")
    assert len(out["transits"]) == 9
    print("panchanga_now OK  (%s %s, %s)" % (
        out["tithi"]["paksha"], out["tithi"]["name"], out["nakshatra"]["name"]))


def test_dasha_systems():
    from jyotish.dasha_systems import KC_APASAVYA, KC_SAVYA, KC_YEARS

    # Kalachakra chain checksums (classical paramayus).
    savya_totals = [sum(KC_YEARS[r] for r in chain) for chain in KC_SAVYA]
    apas_totals = [sum(KC_YEARS[r] for r in chain) for chain in KC_APASAVYA]
    assert savya_totals == [100, 85, 83, 86], savya_totals
    assert apas_totals == [86, 83, 85, 100], apas_totals

    # Yogini: Moon in Pushya (nakshatra 8) -> (8+3) mod 8 = 3 -> Dhanya.
    yog = api.dasha_periods(INDIA, system="yogini")
    assert yog["birth_lord"].startswith("Dhanya"), yog["birth_lord"]
    assert len(yog["mahadashas"]) == 24  # 3 cycles x 8
    assert len(yog["mahadashas"][0]["antardashas"]) == 8

    # Chara: Taurus lagna (savya) -> direct sequence starting Taurus.
    ch = api.dasha_periods(INDIA, system="chara")
    assert ch["lagna_sign"] == "Taurus" and ch["direction"] == "direct"
    assert [m["lord"] for m in ch["mahadashas"][:3]] == ["Taurus", "Gemini", "Cancer"]
    assert all(1 <= m["years"] <= 12 for m in ch["mahadashas"])
    assert len(ch["mahadashas"]) == 12

    # Kalachakra: Moon in Pushya = nakshatra 8 (index 7) -> group index
    # 7//3=2 -> even -> savya. Verify structure.
    kc = api.dasha_periods(INDIA, system="kalachakra")
    assert kc["group"] == "savya", kc["group"]
    assert kc["paramayu_years"] in (100, 85, 83, 86)
    assert len(kc["mahadashas"]) == 9
    assert len(kc["mahadashas"][0]["antardashas"]) == 9

    # Unknown system rejected.
    try:
        api.dasha_periods(INDIA, system="nope")
        raise AssertionError("should have raised")
    except ValueError:
        pass
    print("dasha systems OK  (yogini %s; chara %s %s; kalachakra %s pada %d, %dy)" % (
        yog["birth_lord"], ch["lagna_sign"], ch["direction"],
        kc["group"], kc["pada"], kc["paramayu_years"]))


if __name__ == "__main__":
    test_birth_chart()
    test_vargas()
    test_dasha()
    test_bhava_and_panchanga()
    test_kp()
    test_ashtakavarga()
    test_panchanga_now()
    test_dasha_systems()
    print("\nAll engine tests passed.")
