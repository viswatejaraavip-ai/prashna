"""Divisional (varga) chart calculations per Parashara.

Every function takes an absolute sidereal longitude (0-360) and returns
the varga sign index (0 = Aries .. 11 = Pisces).

Sign conventions used below (0-indexed):
  odd sign      -> sign number 1,3,5.. -> index % 2 == 0  (Aries, Gemini, ...)
  movable       -> index % 3 == 0 (Aries, Cancer, Libra, Capricorn)
  fixed         -> index % 3 == 1
  dual          -> index % 3 == 2
  element: fire -> index % 4 == 0, earth -> 1, air -> 2, water -> 3
"""

import math
from typing import Callable, Dict

ARIES, TAURUS, GEMINI, CANCER, LEO, VIRGO = 0, 1, 2, 3, 4, 5
LIBRA, SCORPIO, SAGITTARIUS, CAPRICORN, AQUARIUS, PISCES = 6, 7, 8, 9, 10, 11


def _split(lon: float):
    lon = lon % 360.0
    sign = int(lon // 30)
    deg = lon - sign * 30
    return sign, deg


def _part(deg: float, size: float, count: int) -> int:
    # guard against floating point putting 30.0 into part `count`
    return min(int(deg / size), count - 1)


def d1(lon: float) -> int:
    return _split(lon)[0]


def d2(lon: float) -> int:
    """Hora: odd signs 0-15 Leo / 15-30 Cancer; even signs reversed."""
    sign, deg = _split(lon)
    first_half = deg < 15.0
    if sign % 2 == 0:  # odd sign
        return LEO if first_half else CANCER
    return CANCER if first_half else LEO


def d3(lon: float) -> int:
    """Drekkana: 10-degree parts go to 1st, 5th, 9th sign from itself."""
    sign, deg = _split(lon)
    return (sign + 4 * _part(deg, 10.0, 3)) % 12


def d4(lon: float) -> int:
    """Chaturthamsa: 7.5-degree parts go to 1st, 4th, 7th, 10th from itself."""
    sign, deg = _split(lon)
    return (sign + 3 * _part(deg, 7.5, 4)) % 12


def d7(lon: float) -> int:
    """Saptamsa: odd signs count from itself, even signs from the 7th."""
    sign, deg = _split(lon)
    n = _part(deg, 30.0 / 7.0, 7)
    start = sign if sign % 2 == 0 else (sign + 6) % 12
    return (start + n) % 12


def d9(lon: float) -> int:
    """Navamsa: 3d20' parts; equivalent to (sign*9 + part) mod 12."""
    sign, deg = _split(lon)
    n = _part(deg, 30.0 / 9.0, 9)
    return (sign * 9 + n) % 12


def d10(lon: float) -> int:
    """Dasamsa: 3-degree parts; odd from itself, even from the 9th."""
    sign, deg = _split(lon)
    n = _part(deg, 3.0, 10)
    start = sign if sign % 2 == 0 else (sign + 8) % 12
    return (start + n) % 12


def d12(lon: float) -> int:
    """Dwadasamsa: 2.5-degree parts counted from the sign itself."""
    sign, deg = _split(lon)
    return (sign + _part(deg, 2.5, 12)) % 12


def d16(lon: float) -> int:
    """Shodasamsa: movable from Aries, fixed from Leo, dual from Sagittarius."""
    sign, deg = _split(lon)
    n = _part(deg, 30.0 / 16.0, 16)
    start = [ARIES, LEO, SAGITTARIUS][sign % 3]
    return (start + n) % 12


def d20(lon: float) -> int:
    """Vimsamsa: movable from Aries, fixed from Sagittarius, dual from Leo."""
    sign, deg = _split(lon)
    n = _part(deg, 1.5, 20)
    start = [ARIES, SAGITTARIUS, LEO][sign % 3]
    return (start + n) % 12


def d24(lon: float) -> int:
    """Chaturvimsamsa: odd signs from Leo, even signs from Cancer."""
    sign, deg = _split(lon)
    n = _part(deg, 1.25, 24)
    start = LEO if sign % 2 == 0 else CANCER
    return (start + n) % 12


def d27(lon: float) -> int:
    """Bhamsa: by element - fire from Aries, earth from Cancer, air from Libra, water from Capricorn."""
    sign, deg = _split(lon)
    n = _part(deg, 30.0 / 27.0, 27)
    start = [ARIES, CANCER, LIBRA, CAPRICORN][sign % 4]
    return (start + n) % 12


def d30(lon: float) -> int:
    """Trimsamsa: unequal parts ruled by Mars/Saturn/Jupiter/Mercury/Venus.

    Odd signs:  5 Aries, 5 Aquarius, 8 Sagittarius, 7 Gemini, 5 Libra.
    Even signs: 5 Taurus, 7 Virgo, 8 Pisces, 5 Capricorn, 5 Scorpio.
    """
    sign, deg = _split(lon)
    if sign % 2 == 0:  # odd sign
        bounds = [(5, ARIES), (10, AQUARIUS), (18, SAGITTARIUS), (25, GEMINI), (30, LIBRA)]
    else:
        bounds = [(5, TAURUS), (12, VIRGO), (20, PISCES), (25, CAPRICORN), (30, SCORPIO)]
    for limit, target in bounds:
        if deg < limit:
            return target
    return bounds[-1][1]


def d40(lon: float) -> int:
    """Khavedamsa: odd signs from Aries, even signs from Libra."""
    sign, deg = _split(lon)
    n = _part(deg, 0.75, 40)
    start = ARIES if sign % 2 == 0 else LIBRA
    return (start + n) % 12


def d45(lon: float) -> int:
    """Akshavedamsa: movable from Aries, fixed from Leo, dual from Sagittarius."""
    sign, deg = _split(lon)
    n = _part(deg, 30.0 / 45.0, 45)
    start = [ARIES, LEO, SAGITTARIUS][sign % 3]
    return (start + n) % 12


def d60(lon: float) -> int:
    """Shashtiamsa: 0.5-degree parts counted from the sign itself."""
    sign, deg = _split(lon)
    n = _part(deg, 0.5, 60)
    return (sign + n) % 12


VARGA_FUNCTIONS: Dict[str, Callable[[float], int]] = {
    "D1": d1, "D2": d2, "D3": d3, "D4": d4, "D7": d7, "D9": d9,
    "D10": d10, "D12": d12, "D16": d16, "D20": d20, "D24": d24,
    "D27": d27, "D30": d30, "D40": d40, "D45": d45, "D60": d60,
}


def varga_sign(lon: float, varga: str) -> int:
    key = varga.upper()
    if key not in VARGA_FUNCTIONS:
        raise ValueError("Unknown varga '%s'. Supported: %s" % (varga, ", ".join(VARGA_FUNCTIONS)))
    return VARGA_FUNCTIONS[key](lon)
