"""Every template key exists in every language file with the same
placeholders, and every string shapes without missing glyphs (no tofu)."""

import json
import os
import string

import pytest

from app.features import common, textrender

LANGS = ("hi", "te", "ta", "kn", "ml", "en")


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        if k == "_meta":
            continue
        key = prefix + k
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _fields(s):
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


MASTER = _flatten(common.templates("en"))


def test_master_covers_engine_terms():
    from jyotish.constants import NAKSHATRAS, SIGNS
    for s in SIGNS:
        assert "lagna." + s in MASTER and "moon_sign." + s in MASTER
    for n in NAKSHATRAS:
        assert "nakshatra." + n in MASTER
    for p in ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"):
        assert "maha." + p in MASTER and "antar." + p in MASTER
        assert "planet_abbr." + p in MASTER
    for i in range(1, 10):
        assert "tara.%d" % i in MASTER
    for i in range(1, 13):
        assert "chandra.%d" % i in MASTER and "ordinal.%d" % i in MASTER


@pytest.mark.parametrize("lang", LANGS)
def test_language_file_complete(lang):
    with open(os.path.join(common.I18N_DIR, lang + ".json"), encoding="utf-8") as fh:
        data = json.load(fh)
    flat = _flatten(data)
    assert set(flat) == set(MASTER), (set(MASTER) ^ set(flat))
    for key, val in flat.items():
        assert isinstance(val, str) and val.strip(), key
        assert _fields(val) == _fields(MASTER[key]), key
    assert "Udhyath" in flat["labels.brand_tagline"]


@pytest.mark.parametrize("lang", LANGS)
def test_language_is_in_its_script(lang):
    """Long texts must be mostly in the language's own script."""
    ranges = {"hi": (0x0900, 0x097F), "te": (0x0C00, 0x0C7F), "ta": (0x0B80, 0x0BFF),
              "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F), "en": (0x0041, 0x007A)}
    lo, hi = ranges[lang]
    flat = _flatten(common.templates(lang))
    for key in [k for k in flat if k.split(".")[0] in ("lagna", "moon_sign", "nakshatra", "maha", "tara")]:
        letters = [c for c in flat[key] if c.isalpha()]
        native = [c for c in letters if lo <= ord(c) <= hi]
        assert len(native) / max(1, len(letters)) > 0.8, key


@pytest.mark.parametrize("lang", LANGS)
def test_no_tofu(lang):
    flat = _flatten(common.templates(lang))
    for key, val in flat.items():
        assert textrender.missing_glyphs(val, lang) == 0, key


@pytest.mark.parametrize("lang", LANGS)
def test_panchanga_names(lang):
    from jyotish.constants import KARANA_FIXED_END, KARANA_MOVABLE, YOGAS, TITHIS
    names = common.names(lang)
    for y in YOGAS:
        assert y in names["yogas"]
    for k in KARANA_MOVABLE + KARANA_FIXED_END + ["Kimstughna"]:
        assert k in names["karanas"]
    for tname in TITHIS[:14] + ["Purnima", "Amavasya"]:
        assert tname in names["tithis"]
