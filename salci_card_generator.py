#!/usr/bin/env python3
"""
salci_card_generator.py
=======================
Generates shareable PNG cards for SALCI pitcher projections.
Uses Pillow (PIL) only — no external font files or system libraries required.
SVG logos require cairosvg + system cairo; falls back to team-initial circles.
"""

from PIL import Image, ImageDraw, ImageFont
import requests
import io
from datetime import datetime
import pytz

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

CARD_WIDTH = 1200
BRAND      = "SALCI"
HANDLE     = "@SALCI"
HASHTAGS   = "#SALCI  #MLB  #Strikeouts"

DARK_THEME = {
    "bg":             (10, 17, 30),
    "card_row":       (20, 30, 50),
    "accent":         (16, 185, 129),
    "text_primary":   (255, 255, 255),
    "text_secondary": (148, 163, 184),
    "text_muted":     (71, 85, 105),
    "grade_s":        (167, 139, 250),
    "grade_a":        (251, 191, 36),
    "grade_b":        (59, 130, 246),
    "grade_c":        (148, 163, 184),
    "divider":        (30, 41, 59),
    "logo_variant":   "dark",
}

LIGHT_THEME = {
    "bg":             (248, 250, 252),
    "card_row":       (255, 255, 255),
    "accent":         (15, 118, 110),
    "text_primary":   (15, 23, 42),
    "text_secondary": (71, 85, 105),
    "text_muted":     (148, 163, 184),
    "grade_s":        (124, 58, 237),
    "grade_a":        (217, 119, 6),
    "grade_b":        (37, 99, 235),
    "grade_c":        (100, 116, 139),
    "divider":        (226, 232, 240),
    "logo_variant":   "light",
}

# Text-safe grade labels (no emoji — PIL default font may not support them)
GRADE_LABEL = {
    "S": "S+", "A": "A", "A+": "A+", "A-": "A-",
    "B+": "B+", "B": "B", "B-": "B-",
    "C": "C", "D": "D", "F": "F",
}

MLB_LOGO_DARK_URL  = "https://www.mlbstatic.com/team-logos/team-cap-on-dark/{team_id}.svg"
MLB_LOGO_COLOR_URL = "https://www.mlbstatic.com/team-logos/{team_id}.svg"

_LOGO_CACHE: dict = {}

# Layout
HEADER_H  = 80
ROW_H     = 60
SECTION_H = 40
FOOTER_H  = 60
PAD       = 24


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _font(size: int = 16) -> ImageFont.FreeTypeFont:
    """Return a scaled PIL default font. Pillow 10+ supports the size param."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _blend(fg: tuple, bg: tuple, alpha: float) -> tuple:
    """Blend fg RGB over bg RGB with alpha 0–1. Returns RGB tuple."""
    return tuple(int(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def _text_size(draw: ImageDraw.ImageDraw, text: str,
               font: ImageFont.FreeTypeFont) -> tuple:
    """Return (width, height) of text string."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


# ─────────────────────────────────────────────────────────────────────────────
# 1. TEAM LOGO FETCHER
# ─────────────────────────────────────────────────────────────────────────────

# Consistent placeholder colors keyed by first letter of team abbrev
_PLACEHOLDER_COLORS = {
    "A": (14, 99, 62),  "B": (12, 35, 64),  "C": (204, 52, 51),
    "D": (12, 35, 64),  "H": (0, 45, 98),   "K": (0, 70, 135),
    "L": (0, 90, 156),  "M": (19, 41, 75),  "N": (0, 45, 98),
    "O": (239, 56, 26), "P": (253, 184, 39), "S": (45, 130, 69),
    "T": (0, 56, 120),  "W": (171, 0, 3),
}

def _placeholder_logo(team_abbrev: str, size: tuple, bg: tuple) -> Image.Image:
    """Colored circle with the first two letters of the team abbreviation."""
    img  = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    first = (team_abbrev or "?")[0].upper()
    color = _PLACEHOLDER_COLORS.get(first, (60, 80, 140))
    draw.ellipse([2, 2, w - 3, h - 3], fill=color + (255,))
    label = (team_abbrev or "?")[:3].upper()
    font  = _font(max(9, w // 4))
    tw, th = _text_size(draw, label, font)
    draw.text(((w - tw) // 2, (h - th) // 2), label,
              fill=(255, 255, 255, 255), font=font)
    return img


def get_team_logo(team_id: int, variant: str, size: tuple,
                  team_abbrev: str = "") -> Image.Image:
    """
    Fetch MLB team logo SVG from CDN and convert to RGBA PIL Image.
    Requires cairosvg + system cairo library; falls back to colored circle.
    """
    cache_key = (team_id, variant, size)
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key]

    url = (MLB_LOGO_DARK_URL if variant == "dark"
           else MLB_LOGO_COLOR_URL).format(team_id=team_id)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; SALCI/1.0)",
            "Accept": "image/svg+xml,*/*",
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            try:
                import cairosvg
                png_bytes = cairosvg.svg2png(
                    bytestring=resp.content,
                    output_width=size[0],
                    output_height=size[1],
                )
                img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                _LOGO_CACHE[cache_key] = img
                return img
            except Exception:
                pass
    except Exception:
        pass

    img = _placeholder_logo(team_abbrev, size, (30, 60, 120))
    _LOGO_CACHE[cache_key] = img
    return img


# ─────────────────────────────────────────────────────────────────────────────
# 2. GAME-TIME SPLITTER
# ─────────────────────────────────────────────────────────────────────────────

def split_by_gametime(pitchers: list) -> tuple:
    """
    Split pitchers into early (before 17:00 ET) and late (17:00+ ET) buckets.
    Returns (early_pitchers, late_pitchers), each sorted by salci desc.
    If game_datetime is None the pitcher goes to the late bucket.
    """
    ET = pytz.timezone("America/New_York")
    early, late = [], []

    for p in pitchers:
        dt_str = p.get("game_datetime")
        if dt_str:
            try:
                dt_utc = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                dt_et  = dt_utc.astimezone(ET)
                bucket = early if dt_et.hour < 17 else late
                bucket.append(p)
                continue
            except Exception:
                pass
        late.append(p)

    early.sort(key=lambda x: x.get("salci", 0), reverse=True)
    late.sort(key=lambda x: x.get("salci", 0), reverse=True)
    return early, late


# ─────────────────────────────────────────────────────────────────────────────
# 3. GRADE COLOR
# ─────────────────────────────────────────────────────────────────────────────

def get_grade_color(grade: str, theme: dict) -> tuple:
    """Return RGB color tuple for a SALCI grade from the active theme."""
    g = (grade or "C").upper()
    if g == "S":
        return theme["grade_s"]
    if g in ("A", "A+", "A-"):
        return theme["grade_a"]
    if g in ("B", "B+", "B-"):
        return theme["grade_b"]
    return theme["grade_c"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. DRAW HEADER
# ─────────────────────────────────────────────────────────────────────────────

def draw_header(draw: ImageDraw.ImageDraw, img: Image.Image,
                theme: dict, date_str: str, card_type: str) -> None:
    """Draw brand (left), card title (centre), date+handle (right), divider."""
    # Brand — left
    brand_font = _font(30)
    draw.text((PAD, 18), BRAND, fill=theme["accent"], font=brand_font)

    # Card type — centre
    title_font = _font(22)
    tw, _ = _text_size(draw, card_type, title_font)
    draw.text(((CARD_WIDTH - tw) // 2, 26), card_type,
              fill=theme["text_primary"], font=title_font)

    # Date + handle — right
    meta_font = _font(15)
    meta_text = f"{date_str}  {HANDLE}"
    mw, _ = _text_size(draw, meta_text, meta_font)
    draw.text((CARD_WIDTH - mw - PAD, 30), meta_text,
              fill=theme["text_muted"], font=meta_font)

    # Divider
    draw.line([(PAD, HEADER_H - 2), (CARD_WIDTH - PAD, HEADER_H - 2)],
              fill=theme["divider"], width=2)


# ─────────────────────────────────────────────────────────────────────────────
# 5. DRAW PITCHER ROW
# ─────────────────────────────────────────────────────────────────────────────

def draw_pitcher_row(draw: ImageDraw.ImageDraw, img: Image.Image,
                     theme: dict, pitcher: dict, y_pos: int,
                     row_width: int, row_index: int = 0) -> int:
    """Draw one pitcher row. Returns ROW_H (60px)."""
    # Alternating row background
    row_bg = theme["card_row"] if row_index % 2 == 0 else theme["bg"]
    draw.rectangle([0, y_pos, row_width, y_pos + ROW_H], fill=row_bg)

    # ── Team logo (40×40) ─────────────────────────────────────────────────
    logo_size = (40, 40)
    logo_x    = PAD
    logo_y    = y_pos + (ROW_H - logo_size[1]) // 2
    team_id   = pitcher.get("team_id")
    team_abbr = pitcher.get("team", "?")

    logo = get_team_logo(
        team_id or 0, theme["logo_variant"], logo_size, team_abbr
    )
    img.paste(logo, (logo_x, logo_y), logo)   # RGBA logo → uses alpha as mask

    # ── Pitcher name + team label ─────────────────────────────────────────
    name_font  = _font(18)
    small_font = _font(13)
    last_name  = pitcher.get("pitcher", "Unknown").split()[-1]
    hand       = pitcher.get("pitcher_hand", "R")
    draw.text((PAD + 50, y_pos + 10), f"{last_name} ({hand})",
              fill=theme["text_primary"], font=name_font)
    draw.text((PAD + 50, y_pos + 34), team_abbr,
              fill=theme["text_secondary"], font=small_font)

    # ── SALCI grade badge ─────────────────────────────────────────────────
    grade       = pitcher.get("salci_grade", "C")
    grade_color = get_grade_color(grade, theme)
    badge_text  = GRADE_LABEL.get(grade.upper(), grade)
    badge_font  = _font(16)
    bw, bh      = _text_size(draw, badge_text, badge_font)
    bw += 20; bh += 10
    bx = 320
    by = y_pos + (ROW_H - bh) // 2
    badge_bg = _blend(grade_color, row_bg, 0.18)
    draw.rounded_rectangle([bx, by, bx + bw, by + bh],
                            radius=6, fill=badge_bg, outline=grade_color, width=2)
    draw.text((bx + 10, by + 5), badge_text, fill=grade_color, font=badge_font)

    # ── Expected Ks ───────────────────────────────────────────────────────
    exp      = pitcher.get("expected", 0)
    exp_font = _font(26)
    exp_str  = str(exp)
    draw.text((440, y_pos + 12), exp_str, fill=theme["accent"], font=exp_font)
    draw.text((440 + _text_size(draw, exp_str, exp_font)[0] + 6, y_pos + 22),
              "K exp", fill=theme["text_secondary"], font=small_font)

    # ── K-line pills (top 2 by probability) ──────────────────────────────
    k_lines = pitcher.get("k_lines", {}) or pitcher.get("lines", {}) or {}
    if k_lines:
        top2 = sorted(k_lines.items(), key=lambda x: x[1], reverse=True)[:2]
        pill_x = 620
        pill_font = _font(14)
        for k_val, prob in top2:
            if prob >= 70:
                pill_color = (34, 197, 94)
            elif prob >= 50:
                pill_color = (234, 179, 8)
            else:
                pill_color = (239, 68, 68)
            pill_text = f"{k_val}+  {prob}%"
            pw, ph    = _text_size(draw, pill_text, pill_font)
            pw += 16; ph += 8
            py = y_pos + (ROW_H - ph) // 2
            pill_bg = _blend(pill_color, row_bg, 0.18)
            draw.rounded_rectangle(
                [pill_x, py, pill_x + pw, py + ph],
                radius=4, fill=pill_bg, outline=pill_color, width=1,
            )
            draw.text((pill_x + 8, py + 4), pill_text,
                      fill=pill_color, font=pill_font)
            pill_x += pw + 10

    return ROW_H


# ─────────────────────────────────────────────────────────────────────────────
# 6. DRAW SECTION HEADER
# ─────────────────────────────────────────────────────────────────────────────

def draw_section_header(draw: ImageDraw.ImageDraw, theme: dict,
                        label: str, y_pos: int, width: int) -> int:
    """Draw a section divider row. Returns SECTION_H (40px)."""
    draw.rectangle([0, y_pos, width, y_pos + SECTION_H], fill=theme["divider"])
    font = _font(15)
    draw.text((PAD, y_pos + 12), label,
              fill=theme["text_secondary"], font=font)
    return SECTION_H


# ─────────────────────────────────────────────────────────────────────────────
# 7. DRAW FOOTER
# ─────────────────────────────────────────────────────────────────────────────

def draw_footer(draw: ImageDraw.ImageDraw, theme: dict,
                width: int, total_height: int) -> None:
    """Draw hashtags (centred) and SALCI watermark (bottom-right)."""
    footer_y = total_height - FOOTER_H
    draw.line([(PAD, footer_y + 2), (width - PAD, footer_y + 2)],
              fill=theme["divider"], width=1)

    # Hashtags — centred
    ht_font = _font(16)
    hw, _   = _text_size(draw, HASHTAGS, ht_font)
    draw.text(((width - hw) // 2, footer_y + 16), HASHTAGS,
              fill=theme["text_secondary"], font=ht_font)

    # Watermark — bottom right
    wm_font = _font(13)
    ww, _   = _text_size(draw, BRAND, wm_font)
    draw.text((width - ww - PAD, footer_y + 38), BRAND,
              fill=theme["text_muted"], font=wm_font)


# ─────────────────────────────────────────────────────────────────────────────
# 8. GENERATE CARD
# ─────────────────────────────────────────────────────────────────────────────

def generate_card(pitchers: list, theme: dict,
                  card_type: str = "Today's Top Pitchers",
                  date_str: str = "") -> Image.Image:
    """
    Assemble the full shareable card image.

    Layout:
        header (80px)
        [section header (40px) + pitcher rows (60px each)] × 2 groups
        footer (60px)
        10px bottom padding

    Returns a PIL Image (RGB).
    """
    if not date_str:
        date_str = datetime.now(
            pytz.timezone("America/New_York")
        ).strftime("%b %d, %Y")

    early, late = split_by_gametime(pitchers)
    has_groups  = bool(early or late)

    # Calculate total height
    n_sections  = sum([bool(early), bool(late)]) if has_groups else 0
    n_pitchers  = len(early) + len(late) if has_groups else len(pitchers)
    total_h     = (HEADER_H + n_sections * SECTION_H +
                   n_pitchers * ROW_H + FOOTER_H + 10)

    img  = Image.new("RGB", (CARD_WIDTH, total_h), theme["bg"])
    draw = ImageDraw.Draw(img)

    draw_header(draw, img, theme, date_str, card_type)
    y = HEADER_H + 10

    def _render_group(group: list, label: str) -> None:
        nonlocal y
        if not group:
            return
        y += draw_section_header(draw, theme, label, y, CARD_WIDTH)
        for idx, pitcher in enumerate(group):
            draw_pitcher_row(draw, img, theme, pitcher, y, CARD_WIDTH, idx)
            y += ROW_H

    if has_groups:
        _render_group(early, "EARLY GAMES")
        _render_group(late,  "LATE GAMES")
    else:
        for idx, pitcher in enumerate(pitchers):
            draw_pitcher_row(draw, img, theme, pitcher, y, CARD_WIDTH, idx)
            y += ROW_H

    draw_footer(draw, theme, CARD_WIDTH, total_h)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# 9. CARD TO BYTES
# ─────────────────────────────────────────────────────────────────────────────

def card_to_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes suitable for a Streamlit download button."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
