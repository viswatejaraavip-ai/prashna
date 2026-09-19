"""WhatsApp share cards (1080x1350 PNG): birth chart or today's forecast,
branded "Udhyath". Indic text is shaped by textrender (HarfBuzz)."""

import io
from datetime import date
from typing import Dict, List

from .common import fmt_date, jc, sign, t, templates
from .textrender import draw_text, wrap

W, H = 1080, 1350
BG = (253, 247, 236)
MAROON = (122, 28, 28)
GOLD = (201, 146, 42)
INK = (45, 32, 30)
MUTED = (120, 105, 95)
RATING_COLOURS = {"good": (46, 125, 50), "mixed": (201, 146, 42), "careful": (183, 28, 28)}

# South Indian chart: fixed sign cells (col, row) on a 4x4 grid.
_SOUTH = {11: (0, 0), 0: (1, 0), 1: (2, 0), 2: (3, 0), 3: (3, 1), 4: (3, 2),
          5: (3, 3), 6: (2, 3), 7: (1, 3), 8: (0, 3), 9: (0, 2), 10: (0, 1)}
# North Indian chart: house label centres in unit-square coordinates.
_NORTH = {1: (0.5, 0.27), 2: (0.25, 0.11), 3: (0.11, 0.25), 4: (0.27, 0.5),
          5: (0.11, 0.75), 6: (0.25, 0.89), 7: (0.5, 0.73), 8: (0.75, 0.89),
          9: (0.89, 0.75), 10: (0.73, 0.5), 11: (0.89, 0.25), 12: (0.75, 0.11)}


def _canvas():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 150], fill=MAROON)
    d.rectangle([0, 150, W, 156], fill=GOLD)
    d.rectangle([0, H - 110, W, H], fill=MAROON)
    d.rectangle([0, H - 116, W, H - 110], fill=GOLD)
    draw_text(img, (W / 2, 28), "Udhyath", 64, (255, 255, 255), "en", bold=True, anchor="ma")
    return img, d


def _footer(img, lang: str):
    draw_text(img, (W / 2, H - 88), t(lang, "labels.brand_tagline"), 30, (255, 240, 220),
              lang, anchor="ma")


def _lines(img, x: float, y: float, text: str, size: int, colour, lang: str,
           max_w: float, bold: bool = False, gap: float = 1.55,
           max_y: float = H - 130) -> float:
    for line in wrap(text, size, max_w, lang, bold):
        if y + size * 1.4 > max_y:  # never run into the footer band
            break
        draw_text(img, (x, y), line, size, colour, lang, bold)
        y += size * gap
    return y


def _south_chart(img, d, x0, y0, size, placements: Dict[int, List[str]], lagna: int,
                 lang: str, centre: List[str]):
    cell = size / 4.0
    for s, (c, r) in _SOUTH.items():
        box = [x0 + c * cell, y0 + r * cell, x0 + (c + 1) * cell, y0 + (r + 1) * cell]
        d.rectangle(box, outline=MAROON, width=3,
                    fill=(250, 236, 214) if s == lagna else None)
        draw_text(img, (box[0] + 8, box[1] + 4), sign(lang, jc.SIGNS[s]), 20, MUTED, lang)
        items = placements.get(s, [])
        for i, txt in enumerate(items[:6]):
            col, row = i % 2, i // 2
            draw_text(img, (box[0] + 12 + col * (cell / 2 - 4), box[1] + 36 + row * 36),
                      txt, 28, INK, lang, bold=(txt == templates(lang)["planet_abbr"]["Lagna"]))
    d.rectangle([x0 + cell, y0 + cell, x0 + 3 * cell, y0 + 3 * cell], outline=MAROON, width=3)
    centre = [c for c in centre if c]
    yy = y0 + size / 2 - len(centre) * 24
    for i, line in enumerate(centre):
        draw_text(img, (x0 + size / 2, yy), line, 32 if i == 0 else 26,
                  MAROON if i == 0 else MUTED, lang, bold=(i == 0), anchor="ma")
        yy += 50 if i == 0 else 42


def _north_chart(img, d, x0, y0, size, houses: Dict[int, List[str]], lagna: int, lang: str):
    s = size
    d.rectangle([x0, y0, x0 + s, y0 + s], outline=MAROON, width=3)
    d.line([x0, y0, x0 + s, y0 + s], fill=MAROON, width=3)
    d.line([x0 + s, y0, x0, y0 + s], fill=MAROON, width=3)
    d.polygon([(x0 + s / 2, y0), (x0 + s, y0 + s / 2), (x0 + s / 2, y0 + s), (x0, y0 + s / 2)],
              outline=MAROON, width=3)
    for h, (ux, uy) in _NORTH.items():
        cx, cy = x0 + ux * s, y0 + uy * s
        sign_no = (lagna + h - 1) % 12 + 1
        items = houses.get(h, [])
        draw_text(img, (cx, cy - 58), str(sign_no), 22, MUTED, "en", anchor="ma")
        line1 = " ".join(items[:3])
        line2 = " ".join(items[3:6])
        draw_text(img, (cx, cy - 26), line1, 30, INK, lang, anchor="ma")
        if line2:
            draw_text(img, (cx, cy + 12), line2, 30, INK, lang, anchor="ma")


def chart_card(profile: Dict, chart: Dict, snap: Dict, lang: str) -> bytes:
    img, d = _canvas()
    abbr = templates(lang)["planet_abbr"]
    lagna = chart["ascendant"]["sign_index"]
    by_sign: Dict[int, List[str]] = {lagna: [abbr["Lagna"]]}
    by_house: Dict[int, List[str]] = {1: [abbr["Lagna"]]}
    for p in jc.PLANETS:
        info = chart["planets"][p]
        by_sign.setdefault(info["sign_index"], []).append(abbr[p])
        by_house.setdefault(info["house_whole_sign"], []).append(abbr[p])
    draw_text(img, (W / 2, 180), profile.get("name", ""), 48, MAROON, lang, bold=True, anchor="ma")
    draw_text(img, (W / 2, 250), t(lang, "labels.birth_chart"), 30, MUTED, lang, anchor="ma")
    size, x0, y0 = 680, (W - 680) / 2, 300
    if lang == "hi":
        _north_chart(img, d, x0, y0, size, by_house, lagna, lang)
    else:
        _south_chart(img, d, x0, y0, size, by_sign, lagna, lang,
                     [fmt_date(profile["birth"]["date"]),
                      profile["birth"]["time"] if profile.get("time_known", True) else "",
                      profile["birth"].get("place", "").split(",")[0]])
    y = y0 + size + 36
    facts = [snap["lagna"]["title"], snap["moon_sign"]["title"], snap["nakshatra"]["title"]]
    for f in facts:
        if y > H - 190:
            break
        y = _lines(img, 90, y, f, 30, INK, lang, W - 180, gap=1.45)
    _footer(img, lang)
    return _png(img)


def daily_card(name: str, day: date, forecast: Dict, pan: Dict, lang: str) -> bytes:
    img, d = _canvas()
    draw_text(img, (W / 2, 190), forecast["title"], 44, MAROON, lang, bold=True, anchor="ma")
    colour = RATING_COLOURS.get(forecast["rating"], GOLD)
    d.rounded_rectangle([140, 280, W - 140, 370], radius=44, fill=colour)
    draw_text(img, (W / 2, 294), forecast["rating_text"], 40, (255, 255, 255), lang,
              bold=True, anchor="ma")
    y = 420
    for line in forecast["lines"]:
        if y > H - 330:
            break
        y = _lines(img, 90, y, line, 34, INK, lang, W - 180) + 18
    y += 10
    d.line([90, y, W - 90, y], fill=GOLD, width=3)
    y += 24
    rows = []
    if pan.get("tithi"):
        rows.append("%s: %s (%s)" % (t(lang, "labels.tithi"), pan["tithi"]["local"],
                                     pan["tithi"]["paksha_local"]))
        rows.append("%s: %s" % (t(lang, "labels.nakshatra_short"), pan["nakshatra"]["local"]))
    tm = pan.get("timings") or {}
    if tm.get("rahu_kalam"):
        rows.append("%s: %s - %s" % (t(lang, "labels.rahu_kalam"), tm["rahu_kalam"]["start"],
                                     tm["rahu_kalam"]["end"]))
    for r in rows:
        if y > H - 190:
            break
        y = _lines(img, 90, y, r, 30, MUTED, lang, W - 180, gap=1.45)
    _footer(img, lang)
    return _png(img)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
