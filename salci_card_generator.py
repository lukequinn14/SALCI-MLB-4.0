#!/usr/bin/env python3
"""
salci_card_generator.py
=======================
Generates shareable PNG cards for SALCI pitcher projections.

Row layout per pitcher (left → right):
  [Team Logo] | [Pitcher Name / Matchup] | [Grade Badge] | [Exp Ks] | [K% Pills]

Logo source: ESPN CDN PNGs fetched server-side with browser headers.
Name resolution logic mirrors pitching_dashboard_tab.py exactly.
"""

from PIL import Image, ImageDraw, ImageFont
import requests
import io
from datetime import datetime
import pytz

# ─────────────────────────────────────────────────────────────────────────────
# CARD DIMENSIONS & LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

CARD_W   = 1200
HEADER_H = 100
ROW_H    = 80
SECTION_H= 48
FOOTER_H = 70
PAD      = 28

# Column x-positions inside each row
COL_LOGO   = PAD                  # logo left edge
COL_NAME   = PAD + 56 + 14        # pitcher name
COL_GRADE  = 490                  # grade badge centre-x
COL_EXP    = 590                  # expected Ks
COL_PILLS  = 730                  # first K pill

LOGO_SIZE  = (52, 52)

BRAND    = "SALCI"
HANDLE   = "@SALCI"
HASHTAGS = "#SALCI  #MLB  #Strikeouts"

# ─────────────────────────────────────────────────────────────────────────────
# THEMES
# ─────────────────────────────────────────────────────────────────────────────

DARK_THEME = {
    "bg":             (10, 17, 30),
    "row_even":       (18, 28, 46),
    "row_odd":        (10, 17, 30),
    "section_bg":     (22, 35, 58),
    "accent":         (16, 185, 129),
    "text_primary":   (241, 245, 249),
    "text_secondary": (148, 163, 184),
    "text_muted":     (71, 85, 105),
    "grade_s":        (167, 139, 250),
    "grade_a":        (251, 191, 36),
    "grade_b":        (59, 130, 246),
    "grade_c":        (148, 163, 184),
    "divider":        (30, 41, 59),
    "dark_bg":        True,
}

LIGHT_THEME = {
    "bg":             (248, 250, 252),
    "row_even":       (255, 255, 255),
    "row_odd":        (241, 245, 249),
    "section_bg":     (226, 232, 240),
    "accent":         (15, 118, 110),
    "text_primary":   (15, 23, 42),
    "text_secondary": (71, 85, 105),
    "text_muted":     (148, 163, 184),
    "grade_s":        (124, 58, 237),
    "grade_a":        (180, 100, 0),
    "grade_b":        (37, 99, 235),
    "grade_c":        (100, 116, 139),
    "divider":        (203, 213, 225),
    "dark_bg":        False,
}

GRADE_TEXT = {
    "S": "S+", "A+": "A+", "A": "A", "A-": "A-",
    "B+": "B+", "B": "B", "B-": "B-",
    "C": "C", "D": "D", "F": "F",
}

# ─────────────────────────────────────────────────────────────────────────────
# ESPN LOGO RESOLUTION  (mirrors pitching_dashboard_tab.py)
# ─────────────────────────────────────────────────────────────────────────────

_ABBREV_TO_ESPN = {
    "ARI": "ari", "ATL": "atl", "BAL": "bal", "BOS": "bos",
    "CHC": "chc", "CWS": "chw", "CIN": "cin",
    "CLE": "cle", "COL": "col", "DET": "det", "HOU": "hou",
    "KC":  "kc",  "LAA": "laa", "LAD": "lad", "MIA": "mia",
    "MIL": "mil", "MIN": "min", "NYM": "nym", "NYY": "nyy",
    "OAK": "oak", "PHI": "phi", "PIT": "pit", "SD":  "sd",
    "SF":  "sf",  "SEA": "sea", "STL": "stl",
    "TB":  "tb",  "TEX": "tex", "TOR": "tor", "WSH": "wsh",
}

_FULL_TO_ABBREV = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",         "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",      "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",     "Detroit Tigers": "DET",
    "Houston Astros": "HOU",       "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",   "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",        "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",      "New York Mets": "NYM",
    "New York Yankees": "NYY",     "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI","Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",      "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",     "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",        "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",    "Washington Nationals": "WSH",
    "Athletics": "OAK", "A's": "OAK", "Guardians": "CLE",
    "Nationals": "WSH", "Cardinals": "STL", "Brewers": "MIL",
    "Padres": "SD", "Giants": "SF", "Mariners": "SEA",
    "Rockies": "COL", "Marlins": "MIA", "Twins": "MIN",
    "Rays": "TB", "Yankees": "NYY", "Mets": "NYM",
    "Cubs": "CHC", "White Sox": "CWS", "Red Sox": "BOS",
    "Blue Jays": "TOR", "Royals": "KC", "Angels": "LAA",
    "Dodgers": "LAD", "Phillies": "PHI", "Pirates": "PIT",
    "Rangers": "TEX", "Orioles": "BAL", "Braves": "ATL",
    "Reds": "CIN", "Tigers": "DET", "Astros": "HOU",
    "Diamondbacks": "ARI", "D-backs": "ARI",
}

_DARK_BG_TEAMS = {"COL", "SD", "NYY", "MIN", "KC", "PIT", "MIL", "CWS", "SF"}

_ESPN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer":  "https://www.espn.com/mlb/",
    "Accept":   "image/webp,image/apng,image/*,*/*;q=0.8",
}

_LOGO_CACHE: dict = {}


def _resolve_abbrev(team: str) -> str:
    """Convert any team name/alias/abbrev to canonical 2-3 letter abbrev."""
    t = team.strip()
    if t in _FULL_TO_ABBREV:
        return _FULL_TO_ABBREV[t]
    upper = t.upper()
    if upper in _ABBREV_TO_ESPN:
        return upper
    lower = t.lower()
    for alias, abbrev in _FULL_TO_ABBREV.items():
        if alias.lower() == lower:
            return abbrev
    best, best_len = None, 0
    for full, abbrev in _FULL_TO_ABBREV.items():
        fl = full.lower()
        if fl in lower or lower in fl:
            if len(full) > best_len:
                best, best_len = abbrev, len(full)
    return best if best else upper


def _espn_url(abbrev: str, dark_bg: bool) -> str:
    slug = _ABBREV_TO_ESPN.get(abbrev, abbrev.lower())
    if dark_bg and abbrev in _DARK_BG_TEAMS:
        return f"https://a.espncdn.com/i/teamlogos/mlb/500-dark/{slug}.png"
    return f"https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{slug}.png"


def _fetch_logo(team: str, size: tuple, dark_bg: bool) -> Image.Image:
    """
    Fetch ESPN team logo PNG and return as RGBA PIL Image.
    Results are cached. Falls back to a colored-initial circle on error.
    """
    abbrev    = _resolve_abbrev(team)
    cache_key = (abbrev, size, dark_bg)
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key]

    url = _espn_url(abbrev, dark_bg)
    try:
        r = requests.get(url, headers=_ESPN_HEADERS, timeout=8)
        if r.status_code == 200:
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            img = img.resize(size, Image.LANCZOS)
            _LOGO_CACHE[cache_key] = img
            return img
    except Exception:
        pass

    # Fallback: colored circle with abbreviation
    img  = _circle_placeholder(abbrev, size)
    _LOGO_CACHE[cache_key] = img
    return img


_CIRCLE_COLORS = {
    "A": (14,99,62),   "B": (12,35,64),   "C": (204,52,51),
    "D": (12,35,64),   "H": (0,45,98),    "K": (0,70,135),
    "L": (0,90,156),   "M": (19,41,75),   "N": (0,45,98),
    "O": (239,56,26),  "P": (253,184,39), "S": (45,130,69),
    "T": (0,56,120),   "W": (171,0,3),
}

def _circle_placeholder(abbrev: str, size: tuple) -> Image.Image:
    img  = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    color = _CIRCLE_COLORS.get((abbrev or "?")[0].upper(), (60, 80, 140))
    draw.ellipse([2, 2, w-3, h-3], fill=color + (255,))
    label = abbrev[:3].upper()
    font  = _font(max(9, w // 4))
    bb    = draw.textbbox((0, 0), label, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    draw.text(((w-tw)//2, (h-th)//2), label, fill=(255,255,255,255), font=font)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# FONT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load best available system TrueType font at given size."""
    mac_regular = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SF-Pro-Display-Regular.otf",
        "/System/Library/Fonts/SFNSText.ttf",
    ]
    mac_bold = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    linux_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    linux_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]

    candidates = (mac_bold if bold else mac_regular) + (linux_bold if bold else linux_regular)

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# Keep _font() as a thin alias used by _circle_placeholder
def _font(size: int = 16) -> ImageFont.FreeTypeFont:
    return _load_font(size, bold=False)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _tw(draw, text, font):
    """Text width."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]

def _th(draw, text, font):
    """Text height."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]

def _blend(fg, bg, a):
    return tuple(int(fg[i]*a + bg[i]*(1-a)) for i in range(3))

def _grade_color(grade: str, theme: dict) -> tuple:
    g = (grade or "C").upper()
    if g == "S":             return theme["grade_s"]
    if g in ("A","A+","A-"): return theme["grade_a"]
    if g in ("B","B+","B-"): return theme["grade_b"]
    return theme["grade_c"]


# ─────────────────────────────────────────────────────────────────────────────
# SPLIT BY GAME TIME
# ─────────────────────────────────────────────────────────────────────────────

def split_by_gametime(pitchers: list) -> tuple:
    ET = pytz.timezone("America/New_York")
    early, late = [], []
    for p in pitchers:
        dt_str = p.get("game_datetime")
        if dt_str:
            try:
                dt_utc = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                (early if dt_utc.astimezone(ET).hour < 17 else late).append(p)
                continue
            except Exception:
                pass
        late.append(p)
    early.sort(key=lambda x: x.get("salci", 0), reverse=True)
    late.sort(key=lambda x: x.get("salci", 0), reverse=True)
    return early, late


# ─────────────────────────────────────────────────────────────────────────────
# DRAW FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _draw_header(draw, img, theme, date_str, card_type):
    """Brand left · title centre · date+handle right · divider."""
    # Left — brand
    bf = _load_font(42, bold=True)
    draw.text((PAD, 20), BRAND, fill=theme["accent"], font=bf)

    # Centre — card type
    tf = _load_font(28, bold=False)
    w  = _tw(draw, card_type, tf)
    draw.text(((CARD_W - w) // 2, 28), card_type,
              fill=theme["text_primary"], font=tf)

    # Right — date + handle
    mf   = _load_font(22, bold=False)
    meta = f"{date_str}  {HANDLE}"
    mw   = _tw(draw, meta, mf)
    draw.text((CARD_W - mw - PAD, 34), meta,
              fill=theme["text_muted"], font=mf)

    # Divider
    draw.line([(PAD, HEADER_H - 2), (CARD_W - PAD, HEADER_H - 2)],
              fill=theme["divider"], width=2)


def _draw_section(draw, theme, label, y):
    """Thin section-header strip. Returns SECTION_H."""
    draw.rectangle([0, y, CARD_W, y + SECTION_H], fill=theme["section_bg"])
    f = _load_font(18, bold=True)
    draw.text((PAD, y + (SECTION_H - _th(draw, label, f)) // 2),
              label, fill=theme["text_secondary"], font=f)
    return SECTION_H


def _draw_row(draw, img, theme, pitcher, y, idx):
    """
    Draw one pitcher row.

    Left → right:
      [Logo 52×52] | [Last Name  Hand · Team vs Opp] | [Grade] | [Exp Ks] | [K% pills]
    """
    row_bg = theme["row_even"] if idx % 2 == 0 else theme["row_odd"]
    draw.rectangle([0, y, CARD_W, y + ROW_H], fill=row_bg)

    # ── Logo ──────────────────────────────────────────────────────────────
    team      = pitcher.get("team", "")
    dark_bg   = theme["dark_bg"]
    logo      = _fetch_logo(team, LOGO_SIZE, dark_bg)
    logo_y    = y + (ROW_H - LOGO_SIZE[1]) // 2
    img.paste(logo, (COL_LOGO, logo_y), logo)

    # ── Pitcher name + matchup ────────────────────────────────────────────
    last_name = pitcher.get("pitcher", "Unknown").split()[-1]
    hand      = pitcher.get("pitcher_hand", "R")
    opponent  = pitcher.get("opponent", "")
    abbrev    = _resolve_abbrev(team) if team else ""

    name_f = _load_font(28, bold=True)
    sub_f  = _load_font(20, bold=False)
    name_label = f"{last_name}  ({hand}HP)"
    sub_label  = f"{abbrev}  vs  {_resolve_abbrev(opponent) if opponent else opponent}"

    name_y = y + (ROW_H // 2) - _th(draw, name_label, name_f) - 2
    sub_y  = y + (ROW_H // 2) + 4

    draw.text((COL_NAME, name_y), name_label,
              fill=theme["text_primary"], font=name_f)
    draw.text((COL_NAME, sub_y), sub_label,
              fill=theme["text_secondary"], font=sub_f)

    # ── Grade badge ───────────────────────────────────────────────────────
    grade      = pitcher.get("salci_grade", "C")
    grade_lbl  = GRADE_TEXT.get(grade.upper(), grade)
    grade_col  = _grade_color(grade, theme)
    gf         = _load_font(22, bold=True)
    gw         = _tw(draw, grade_lbl, gf)
    gh         = _th(draw, grade_lbl, gf)
    bw, bh     = gw + 24, gh + 12
    bx         = COL_GRADE
    by         = y + (ROW_H - bh) // 2
    badge_bg   = _blend(grade_col, row_bg, 0.20)
    draw.rounded_rectangle([bx, by, bx + bw, by + bh],
                            radius=6, fill=badge_bg, outline=grade_col, width=2)
    draw.text((bx + 12, by + 6), grade_lbl, fill=grade_col, font=gf)

    # ── Expected Ks ───────────────────────────────────────────────────────
    exp     = pitcher.get("expected", "--")
    exp_f   = _load_font(38, bold=True)
    lbl_f   = _load_font(20, bold=False)
    exp_str = str(exp)
    ey      = y + (ROW_H - _th(draw, exp_str, exp_f)) // 2
    draw.text((COL_EXP, ey), exp_str, fill=theme["accent"], font=exp_f)
    draw.text((COL_EXP + _tw(draw, exp_str, exp_f) + 5,
               ey + _th(draw, exp_str, exp_f) - _th(draw, "K", lbl_f) - 2),
              "K", fill=theme["text_secondary"], font=lbl_f)

    # ── K% pills — sorted by K threshold ascending ────────────────────────
    k_lines = pitcher.get("k_lines", {}) or pitcher.get("lines", {}) or {}
    if k_lines:
        items   = sorted(k_lines.items())[:4]
        pill_x  = COL_PILLS
        pill_f  = _load_font(16, bold=True)
        for k_val, prob in items:
            if prob >= 70:
                pc = (34, 197, 94)
            elif prob >= 50:
                pc = (234, 179, 8)
            else:
                pc = (239, 68, 68)
            pill_text = f"{k_val}+  {prob}%"
            pw = _tw(draw, pill_text, pill_f) + 24   # +8px each side (Change 4)
            ph = _th(draw, pill_text, pill_f) + 12
            py = y + (ROW_H - ph) // 2
            draw.rounded_rectangle([pill_x, py, pill_x + pw, py + ph],
                                    radius=5,
                                    fill=_blend(pc, row_bg, 0.18),
                                    outline=pc, width=1)
            draw.text((pill_x + 12, py + 6), pill_text, fill=pc, font=pill_f)
            pill_x += pw + 10

    return ROW_H


def _draw_footer(draw, theme, total_h):
    fy = total_h - FOOTER_H
    draw.line([(PAD, fy + 2), (CARD_W - PAD, fy + 2)],
              fill=theme["divider"], width=1)
    hf = _load_font(18, bold=False)
    hw = _tw(draw, HASHTAGS, hf)
    draw.text(((CARD_W - hw) // 2, fy + 16), HASHTAGS,
              fill=theme["text_secondary"], font=hf)
    wf = _load_font(16, bold=False)
    ww = _tw(draw, BRAND, wf)
    draw.text((CARD_W - ww - PAD, fy + 44), BRAND,
              fill=theme["text_muted"], font=wf)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — GENERATE CARD
# ─────────────────────────────────────────────────────────────────────────────

def generate_card(pitchers: list, theme: dict,
                  card_type: str = "Today's Top Pitchers",
                  date_str: str = "") -> Image.Image:
    """
    Assemble and return the full shareable card as a PIL Image (RGB).

    Layout
    ------
    Header (90px)
    [Section header (36px) + rows (72px each)] × up to 2 groups
    Footer (56px)
    """
    if not date_str:
        date_str = datetime.now(
            pytz.timezone("America/New_York")
        ).strftime("%b %d, %Y")

    early, late = split_by_gametime(pitchers)
    has_groups  = bool(early or late)

    n_sections = sum([bool(early), bool(late)]) if has_groups else 0
    n_pitchers = (len(early) + len(late)) if has_groups else len(pitchers)
    total_h    = HEADER_H + n_sections * SECTION_H + n_pitchers * ROW_H + FOOTER_H + 8

    img  = Image.new("RGB", (CARD_W, total_h), theme["bg"])
    draw = ImageDraw.Draw(img)

    _draw_header(draw, img, theme, date_str, card_type)
    y = HEADER_H + 8

    def _render_group(group, label):
        nonlocal y
        if not group:
            return
        y += _draw_section(draw, theme, label, y)
        for idx, p in enumerate(group):
            _draw_row(draw, img, theme, p, y, idx)
            y += ROW_H

    if has_groups:
        _render_group(early, "EARLY GAMES")
        _render_group(late,  "LATE GAMES")
    else:
        for idx, p in enumerate(pitchers):
            _draw_row(draw, img, theme, p, y, idx)
            y += ROW_H

    _draw_footer(draw, theme, total_h)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def card_to_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes for a Streamlit download button."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
