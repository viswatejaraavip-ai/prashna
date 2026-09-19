"""Matching PDF for sending to the other family (fpdf2 + HarfBuzz shaping,
so Telugu/Tamil/Kannada/Malayalam/Hindi conjuncts render correctly)."""

import io
import urllib.request
from typing import Dict, Optional

from .common import fmt_date, t
from .textrender import font_path

BRAND_NAME = "Udhyath"
_MAROON = (122, 28, 28)
_GOLD = (201, 146, 42)
_INK = (40, 30, 30)
_MUTED = (110, 100, 95)


def _pdf(lang: str):
    from fpdf import FPDF
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_font("main", "", font_path(lang, False))
    pdf.add_font("main", "B", font_path(lang, True))
    pdf.add_font("latin", "", font_path("en", False))
    pdf.add_font("latin", "B", font_path("en", True))
    pdf.set_text_shaping(True)
    pdf.set_fallback_fonts(["latin"], exact_match=False)
    return pdf


def _setf(pdf, style: str, size: float) -> None:
    """Select the language font. Switching via the Latin font first forces a
    real font change: fpdf2 2.8 skips a set_font() with unchanged arguments,
    and after a cell rendered entirely in the fallback font that leaves the
    fallback font active, so following Indic text comes out blank."""
    pdf.set_font("latin", style, size)
    pdf.set_font("main", style, size)


def _font_for(pdf, text: str, style: str, size: float) -> None:
    """Latin-only strings use the Latin font directly (never the fallback),
    everything else the language font, re-selected for every cell."""
    if all(ord(c) < 0x0900 for c in text):
        pdf.set_font("latin", style, size)
    else:
        _setf(pdf, style, size)


def _fetch_logo(url: str) -> Optional[bytes]:
    if not url or not url.startswith("https://"):
        return None
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = resp.read(1_000_001)
        return data if len(data) <= 1_000_000 else None
    except Exception:
        return None


def matching_pdf(result: Dict, lang: str, brand: Optional[Dict] = None,
                 births: Optional[Dict[str, Dict]] = None) -> bytes:
    pdf = _pdf(lang)
    pdf.add_page()
    brand = brand or {}
    title_brand = brand.get("display_name") or BRAND_NAME

    # Header band
    pdf.set_fill_color(*_MAROON)
    pdf.rect(0, 0, 210, 26, "F")
    x_text = 12
    logo = _fetch_logo(brand.get("logo_url", "")) if brand else None
    if logo:
        try:
            pdf.image(io.BytesIO(logo), x=10, y=4, h=18)
            x_text = 32
        except Exception:
            pass
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(x_text, 6)
    _font_for(pdf, title_brand, "B", 16)
    pdf.cell(0, 8, title_brand)
    pdf.set_xy(x_text, 15)
    sub = brand.get("phone") or t(lang, "labels.brand_tagline")
    _font_for(pdf, sub, "", 9)
    pdf.cell(0, 6, sub)
    pdf.set_text_color(*_INK)

    pdf.set_xy(12, 32)
    _setf(pdf, "B", 15)
    pdf.set_text_color(*_MAROON)
    pdf.multi_cell(186, 9, t(lang, "labels.matching_report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_INK)

    # People
    pdf.ln(2)
    col_w = 91
    y0 = pdf.get_y()
    y_end = y0
    for i, (key, label_key) in enumerate((("groom", "labels.groom"), ("bride", "labels.bride"))):
        p = result[key]
        x = 12 + i * (col_w + 4)
        pdf.set_draw_color(*_GOLD)
        pdf.set_xy(x, y0)
        _setf(pdf, "B", 11)
        pdf.set_fill_color(250, 243, 230)
        pdf.cell(col_w, 8, "%s: %s" % (t(lang, label_key), p.get("name") or ""), border=1, fill=True)
        _setf(pdf, "", 9.5)
        rows = []
        b = (births or {}).get(key)
        if b:
            place = b.get("place") or ""
            tm = b.get("time") if p.get("time_known", True) else "~"
            rows.append("%s: %s %s" % (t(lang, "labels.birth_details"), fmt_date(b["date"]), tm))
            if place:
                rows.append(place)
        rows.append("%s: %s" % (t(lang, "labels.moon_sign"), p["moon_sign_local"]))
        rows.append("%s: %s, %s %s" % (t(lang, "labels.nakshatra"), p["nakshatra_local"],
                                        t(lang, "labels.pada"), p["pada"]))
        if p.get("manglik") is not None:
            rows.append("%s: %s" % (t(lang, "labels.manglik"),
                                    t(lang, "labels.yes" if p["manglik"] else "labels.no")))
        yy = y0 + 8
        for r in rows:
            _font_for(pdf, r, "", 9.5)
            pdf.set_xy(x, yy)
            pdf.multi_cell(col_w, 6, r, border="LR", new_x="RIGHT", new_y="TOP")
            yy += 6 * max(1, len(pdf.multi_cell(col_w, 6, r, dry_run=True, output="LINES")))
        pdf.line(x, yy, x + col_w, yy)
        y_end = max(y_end, yy)
    pdf.set_xy(12, y_end + 6)

    # Guna milan table
    _setf(pdf, "B", 12)
    pdf.set_text_color(*_MAROON)
    gm = result["guna_milan"]
    pdf.cell(0, 8, "%s: %s" % (t(lang, "labels.guna_milan"),
                               t(lang, "labels.score_of", score="%g" % gm["total"], max=36)),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_INK)
    _setf(pdf, "B", 10)
    pdf.set_fill_color(250, 243, 230)
    pdf.cell(120, 7, t(lang, "labels.koota"), border=1, fill=True)
    pdf.cell(66, 7, t(lang, "labels.points"), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    _setf(pdf, "", 10)
    for k in gm["kootas"]:
        pdf.cell(120, 7, k["name"], border=1)
        pdf.cell(66, 7, "%g / %g" % (k["points"], k["max"]), border=1, new_x="LMARGIN", new_y="NEXT")

    # Dashakoot
    pdf.ln(3)
    dk = result["dashakoot"]
    _setf(pdf, "B", 12)
    pdf.set_text_color(*_MAROON)
    pdf.cell(0, 8, "%s: %d / 10" % (t(lang, "labels.dashakoot"), dk["passed"]),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_INK)
    _setf(pdf, "", 9.5)
    for i, p in enumerate(dk["poruthams"]):
        x = 12 + (i % 2) * 93
        if i % 2 == 0 and i:
            pdf.ln(6.5)
        pdf.set_x(x)
        pdf.cell(93, 6.5, "%s: %s" % (p["name"], t(lang, "labels.passed" if p["ok"]
                                                   else "labels.not_passed")), border=1)
    pdf.ln(10)

    # Verdict
    _setf(pdf, "B", 12)
    pdf.set_text_color(*_MAROON)
    pdf.cell(0, 8, t(lang, "labels.verdict"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_INK)
    _setf(pdf, "", 10.5)
    for line in [result["verdict"]["text"]] + result["cautions"] + \
            ([result["manglik"]["text"]] if result["manglik"].get("text") else []):
        pdf.multi_cell(186, 6.5, line, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
    if result.get("approximate"):
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(186, 6, t(lang, "matching.time_unknown"), align="L", new_x="LMARGIN", new_y="NEXT")

    # Footer
    pdf.ln(4)
    pdf.set_draw_color(*_GOLD)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(*_MUTED)
    footer_lines = [brand.get("footer") or "", t(lang, "labels.disclaimer")]
    if brand.get("display_name"):
        footer_lines.append("%s %s · %s" % (t(lang, "labels.prepared_by"),
                                            brand["display_name"], BRAND_NAME))
    else:
        footer_lines.append(BRAND_NAME)
    for line in footer_lines:
        if line:
            _font_for(pdf, line, "", 8.5)
            pdf.multi_cell(186, 5, line, align="L", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
