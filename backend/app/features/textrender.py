"""Correctly shaped Indic text on Pillow images, without libraqm.

Pillow only shapes Indic scripts (conjuncts, vowel-sign reordering, reph)
when it was built with libraqm + FriBiDi, which the slim Cloud Run image and
most macOS wheels lack. So we shape with HarfBuzz (``uharfbuzz`` wheel), pull
the glyph outlines from HarfBuzz itself and rasterise them with Pillow at 4x,
then downsample for anti-aliasing. Output is identical on every platform.

Fonts are the Noto Sans families shipped in ``features/fonts`` (SIL OFL 1.1,
see fonts/OFL.txt). Each character is assigned the first font in
[language font, Noto Sans (Latin), other Indic fonts] whose cmap has it;
combining marks, ZWJ/ZWNJ and viramas stay in the run of the preceding base.
"""

import os
import unicodedata
from functools import lru_cache
from typing import Dict, List, Tuple

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

_FAMILY = {
    "hi": "NotoSansDevanagari", "te": "NotoSansTelugu", "ta": "NotoSansTamil",
    "kn": "NotoSansKannada", "ml": "NotoSansMalayalam", "en": "NotoSans",
}


def font_path(lang: str, bold: bool = False) -> str:
    fam = _FAMILY.get(lang, "NotoSans")
    return os.path.join(FONT_DIR, "%s-%s.ttf" % (fam, "Bold" if bold else "Regular"))


class _Face:
    def __init__(self, path: str):
        import uharfbuzz as hb
        from fontTools.ttLib import TTFont
        with open(path, "rb") as fh:
            blob = hb.Blob(fh.read())
        self.path = path
        self.face = hb.Face(blob)
        self.font = hb.Font(self.face)
        self.upem = self.face.upem
        tt = TTFont(path, lazy=True)
        self.cmap = set(tt.getBestCmap().keys())
        hhea = tt["hhea"]
        self.ascender, self.descender = hhea.ascent, hhea.descent
        tt.close()
        self._outline_cache: Dict[int, List[List[Tuple[float, float]]]] = {}

    def has(self, ch: str) -> bool:
        return ord(ch) in self.cmap

    def outline(self, gid: int) -> List[List[Tuple[float, float]]]:
        """Glyph contours in font units, curves flattened to polylines."""
        if gid in self._outline_cache:
            return self._outline_cache[gid]
        pen = _FlattenPen()
        self.font.draw_glyph_with_pen(gid, pen)
        pen.closePath()
        self._outline_cache[gid] = pen.contours
        return pen.contours


class _FlattenPen:
    """Minimal pen protocol (moveTo/lineTo/qCurveTo/curveTo/closePath)."""
    STEPS = 8

    def __init__(self):
        self.contours: List[List[Tuple[float, float]]] = []
        self.cur: List[Tuple[float, float]] = []

    def moveTo(self, p):
        self.closePath()
        self.cur = [tuple(p)]

    def lineTo(self, p):
        self.cur.append(tuple(p))

    def qCurveTo(self, *pts):
        # TrueType-style implied on-curve points between consecutive controls.
        p0 = self.cur[-1]
        pts = [tuple(p) for p in pts]
        ctrls, end = pts[:-1], pts[-1]
        if not ctrls:
            self.cur.append(end)
            return
        for i, c in enumerate(ctrls):
            nxt = end if i == len(ctrls) - 1 else (
                ((c[0] + ctrls[i + 1][0]) / 2.0, (c[1] + ctrls[i + 1][1]) / 2.0))
            for s in range(1, self.STEPS + 1):
                t = s / float(self.STEPS)
                a = (1 - t) ** 2
                b = 2 * (1 - t) * t
                d = t * t
                self.cur.append((a * p0[0] + b * c[0] + d * nxt[0],
                                 a * p0[1] + b * c[1] + d * nxt[1]))
            p0 = nxt

    def curveTo(self, *pts):
        p0 = self.cur[-1]
        pts = [tuple(p) for p in pts]
        # Split poly-cubics into cubic segments of 3 points.
        while len(pts) >= 3:
            c1, c2, end = pts[0], pts[1], pts[2]
            for s in range(1, self.STEPS + 1):
                t = s / float(self.STEPS)
                mt = 1 - t
                self.cur.append((
                    mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * end[0],
                    mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * end[1]))
            p0 = end
            pts = pts[3:]
        for p in pts:
            self.cur.append(p)

    def closePath(self):
        if len(self.cur) >= 3:
            self.contours.append(self.cur)
        self.cur = []

    endPath = closePath


@lru_cache(maxsize=32)
def _face(path: str) -> _Face:
    return _Face(path)


def _fallback_chain(lang: str, bold: bool) -> List[_Face]:
    order = [lang, "en"] + [l for l in ("hi", "te", "ta", "kn", "ml") if l != lang]
    return [_face(font_path(l, bold)) for l in order]


def _is_joiner(ch: str) -> bool:
    return (unicodedata.category(ch) in ("Mn", "Mc", "Me")
            or ch in ("\u200c", "\u200d"))


def _runs(text: str, lang: str, bold: bool) -> List[Tuple[_Face, str]]:
    chain = _fallback_chain(lang, bold)
    runs: List[Tuple[_Face, str]] = []
    for ch in text:
        if runs and _is_joiner(ch):
            face = runs[-1][0]
        elif ch == " " and runs:
            face = runs[-1][0]
        else:
            face = next((f for f in chain if f.has(ch)), chain[0])
        if runs and runs[-1][0] is face:
            runs[-1] = (face, runs[-1][1] + ch)
        else:
            runs.append((face, ch))
    return runs


def _shape(face: _Face, text: str):
    import uharfbuzz as hb
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(face.font, buf, {"kern": True, "liga": True})
    return buf.glyph_infos, buf.glyph_positions


def shape_line(text: str, lang: str, bold: bool = False):
    """[(face, gid, x_units_scaled_to_1px_per_upem...)] -> list of glyph
    placements in *em* units: (face, gid, x_em, y_em). Plus total advance."""
    out = []
    x = 0.0
    for face, chunk in _runs(text, lang, bold):
        infos, positions = _shape(face, chunk)
        for info, pos in zip(infos, positions):
            out.append((face, info.codepoint, x + pos.x_offset / face.upem,
                        pos.y_offset / face.upem))
            x += pos.x_advance / face.upem
    return out, x


def missing_glyphs(text: str, lang: str, bold: bool = False) -> int:
    """How many shaped glyphs are .notdef (tofu). 0 means fully covered."""
    glyphs, _ = shape_line(text, lang, bold)
    return sum(1 for g in glyphs if g[1] == 0)


def text_width(text: str, size: float, lang: str, bold: bool = False) -> float:
    return shape_line(text, lang, bold)[1] * size


def wrap(text: str, size: float, max_width: float, lang: str,
         bold: bool = False) -> List[str]:
    lines: List[str] = []
    for para in (text or "").split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            trial = (cur + " " + w) if cur else w
            if cur and text_width(trial, size, lang, bold) > max_width:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        lines.append(cur)
    return lines


def draw_text(img, xy: Tuple[float, float], text: str, size: float,
              fill=(0, 0, 0), lang: str = "en", bold: bool = False,
              anchor: str = "la") -> float:
    """Draw one line with its top-left at xy (anchor 'la'), or centred
    horizontally ('ma') / right-aligned ('ra'). Returns the width drawn."""
    from PIL import Image, ImageChops, ImageDraw

    glyphs, advance = shape_line(text, lang, bold)
    width = advance * size
    if not glyphs:
        return 0.0
    x0, y0 = xy
    if anchor[0] == "m":
        x0 -= width / 2.0
    elif anchor[0] == "r":
        x0 -= width
    ss = 4  # supersampling
    asc = 1.25  # top of line box to baseline, in em (room for Indic top marks)
    line_h = 1.9  # line box height in em (room for deep below-base forms)
    w_px = int(width * ss) + 8 * ss
    h_px = int(size * line_h * ss) + 4 * ss
    mask = Image.new("1", (w_px, h_px), 0)
    baseline = asc * size * ss + 2 * ss
    for face, gid, gx, gy in glyphs:
        contours = face.outline(gid)
        if not contours:
            continue
        scale = size * ss / face.upem
        polys = [[(4 * ss + gx * size * ss + px * scale,
                   baseline - gy * size * ss - py * scale) for px, py in contour]
                 for contour in contours]
        bx0 = int(min(p[0] for poly in polys for p in poly)) - 1
        by0 = int(min(p[1] for poly in polys for p in poly)) - 1
        bx1 = int(max(p[0] for poly in polys for p in poly)) + 2
        by1 = int(max(p[1] for poly in polys for p in poly)) + 2
        gw, gh = bx1 - bx0, by1 - by0
        if gw <= 0 or gh <= 0:
            continue
        # Even-odd fill per glyph (XOR of contours keeps counters open),
        # then OR the glyph into the line mask.
        gmask = Image.new("1", (gw, gh), 0)
        for poly in polys:
            layer = Image.new("1", (gw, gh), 0)
            ImageDraw.Draw(layer).polygon([(x - bx0, y - by0) for x, y in poly], fill=1)
            gmask = ImageChops.logical_xor(gmask, layer)
        if bx0 < 0 or by0 < 0 or bx1 > w_px or by1 > h_px:
            # Clip the glyph to the line box (only extreme marks get here).
            gmask = gmask.crop((max(0, -bx0), max(0, -by0),
                                gw - max(0, bx1 - w_px), gh - max(0, by1 - h_px)))
            bx0, by0 = max(bx0, 0), max(by0, 0)
        mask.paste(1, (bx0, by0), gmask)
    alpha = mask.convert("L").resize((w_px // ss, h_px // ss), Image.BOX)
    colour = Image.new("RGBA", alpha.size, tuple(fill[:3]) + (255,))
    colour.putalpha(alpha)
    base = img if img.mode == "RGBA" else None
    target = (int(round(x0)) - 4, int(round(y0)) - 2)
    if base is not None:
        base.alpha_composite(colour, dest=(max(target[0], 0), max(target[1], 0)))
    else:
        img.paste(colour, target, colour)
    return width
