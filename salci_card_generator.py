#!/usr/bin/env python3
"""
salci_card_generator.py
=======================
Generates shareable 1200px PNG cards for SALCI pitcher projections.

Rendering pipeline
------------------
All drawing is done at 2× resolution (2400×N), then downsampled with
Image.LANCZOS to 1200×N. This gives browser-quality anti-aliased text
without any external dependencies.

Row layout (left → right, two-line)
--------------------------------------
LINE 1: [Logo 56px] [Name bold 30px]                [7.3 large 48px accent] K
LINE 2:             [STL vs MIA  20px muted]  [Grade pill]  [pill1 pill2]
                                                             [pill3 pill4]

Logo source: ESPN CDN PNGs with browser-spoofed headers (same approach as
pitching_dashboard_tab.py). Name resolution identical to that module.
"""

from PIL import Image, ImageDraw, ImageFont
import requests
import io
from datetime import datetime
import pytz

# ─────────────────────────────────────────────────────────────────────────────
# BASE LAYOUT CONSTANTS  (1× pixel values — all multiplied by SCALE at render)
# ─────────────────────────────────────────────────────────────────────────────

CARD_W    = 1200
HEADER_H  = 110
ROW_H     = 90
SECTION_H = 44
FOOTER_H  = 56
PAD       = 28

LOGO_SZ      = 60        # logo square side length

# Horizontal column starts (1×)
COL_LOGO     = 20                          # logo left edge
COL_NAME     = COL_LOGO + LOGO_SZ + 16    # 96 — name / matchup
COL_GRADE    = 430                         # grade badge
COL_EXP      = 510                         # big Ks number (right of grade)
COL_PILLS    = 660                         # first K pill
PILL_SPACING = 133                         # gap between pill left edges

BRAND    = "SALCI"
HANDLE   = "@SALCI"
HASHTAGS = "#SALCI  #MLB  #Strikeouts  #BaseballBetting"

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
# ESPN LOGO RESOLUTION  (mirrors pitching_dashboard_tab.py exactly)
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
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.espn.com/mlb/",
    "Accept":  "image/webp,image/apng,image/*,*/*;q=0.8",
}

_LOGO_CACHE: dict = {}


def _resolve_abbrev(team: str) -> str:
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


def _fetch_logo(team: str, px: int, dark_bg: bool) -> Image.Image:
    """Fetch ESPN logo at px×px. Cached. Falls back to coloured-initial circle."""
    abbrev    = _resolve_abbrev(team)
    size      = (px, px)
    cache_key = (abbrev, px, dark_bg)
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key]
    url = _espn_url(abbrev, dark_bg)
    try:
        r = requests.get(url, headers=_ESPN_HEADERS, timeout=8)
        if r.status_code == 200:
            logo = Image.open(io.BytesIO(r.content)).convert("RGBA")
            logo = logo.resize(size, Image.LANCZOS)
            _LOGO_CACHE[cache_key] = logo
            return logo
    except Exception:
        pass
    logo = _circle_placeholder(abbrev, size)
    _LOGO_CACHE[cache_key] = logo
    return logo


_CIRCLE_COLORS = {
    "A": (14,99,62),  "B": (12,35,64),  "C": (204,52,51),
    "D": (12,35,64),  "H": (0,45,98),   "K": (0,70,135),
    "L": (0,90,156),  "M": (19,41,75),  "N": (0,45,98),
    "O": (239,56,26), "P": (253,184,39),"S": (45,130,69),
    "T": (0,56,120),  "W": (171,0,3),
}

def _circle_placeholder(abbrev: str, size: tuple) -> Image.Image:
    img  = Image.new("RGBA", size, (0,0,0,0))
    draw = ImageDraw.Draw(img)
    w, h = size
    c    = _CIRCLE_COLORS.get((abbrev or "?")[0].upper(), (60,80,140))
    draw.ellipse([2, 2, w-3, h-3], fill=c+(255,))
    lbl  = abbrev[:3].upper()
    font = _load_font(max(9, w//4), bold=True)
    bb   = draw.textbbox((0,0), lbl, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    draw.text(((w-tw)//2, (h-th)//2), lbl, fill=(255,255,255,255), font=font)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# FONT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load best available system TrueType font. Tried on Mac then Linux."""
    mac_reg  = ["/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
                "/System/Library/Fonts/SFNSText.ttf"]
    mac_bold = ["/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf"]
    lnx_reg  = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf"]
    lnx_bold = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]
    for path in (mac_bold if bold else mac_reg) + (lnx_bold if bold else lnx_reg):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────────────────
# DRAW HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _tw(draw, text, font):
    bb = draw.textbbox((0,0), text, font=font)
    return bb[2] - bb[0]

def _th(draw, text, font):
    bb = draw.textbbox((0,0), text, font=font)
    return bb[3] - bb[1]

def _blend(fg, bg, a):
    return tuple(int(fg[i]*a + bg[i]*(1-a)) for i in range(3))

def _grade_color(grade: str, theme: dict) -> tuple:
    g = (grade or "C").upper()
    if g == "S":              return theme["grade_s"]
    if g in ("A","A+","A-"):  return theme["grade_a"]
    if g in ("B","B+","B-"):  return theme["grade_b"]
    return theme["grade_c"]


# ─────────────────────────────────────────────────────────────────────────────
# GAME-TIME SPLITTER
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
# DRAW FUNCTIONS  (all coordinates/sizes in 1× units; caller multiplies by S)
# ─────────────────────────────────────────────────────────────────────────────

def _draw_header(draw, img, theme, date_str, card_type, S):
    """
    Header layout (110px base):
      Left   — "SALCI ⚾" 48px bold accent
      Centre — card_type  32px white
      Right  — date (line1) + "@SALCI  #SALCI" (line2)  20px muted
      Bottom — 3px divider
    """
    # Brand
    bf = _load_font(48*S, bold=True)
    draw.text((PAD*S, 18*S), "SALCI", fill=theme["accent"], font=bf)

    # Centre title
    tf = _load_font(32*S, bold=False)
    w  = _tw(draw, card_type, tf)
    draw.text(((CARD_W*S - w) // 2, 26*S), card_type,
              fill=theme["text_primary"], font=tf)

    # Right — two-line date / handle
    mf = _load_font(20*S, bold=False)
    line2 = f"{HANDLE}  #SALCI"
    d_w   = _tw(draw, date_str, mf)
    l2_w  = _tw(draw, line2, mf)
    rx    = CARD_W*S - max(d_w, l2_w) - PAD*S
    draw.text((rx, 16*S), date_str, fill=theme["text_muted"], font=mf)
    draw.text((rx, 44*S), line2,    fill=theme["text_muted"], font=mf)

    # Divider
    dy = (HEADER_H - 4) * S
    draw.line([(PAD*S, dy), (CARD_W*S - PAD*S, dy)],
              fill=theme["divider"], width=3*S)


def _draw_section(draw, theme, label, y, S):
    """
    Section header strip with 4px left accent bar.
    Returns SECTION_H (unscaled).
    """
    y0, y1 = y*S, (y + SECTION_H)*S
    draw.rectangle([0, y0, CARD_W*S, y1], fill=theme["section_bg"])

    # 4px accent bar on the left
    draw.rectangle([0, y0, 4*S, y1], fill=theme["accent"])

    f   = _load_font(22*S, bold=True)
    ty  = y0 + (SECTION_H*S - _th(draw, label, f)) // 2
    draw.text((20*S, ty), label, fill=theme["text_secondary"], font=f)
    return SECTION_H


def _draw_row(draw, img, theme, pitcher, y, idx, S):
    """
    Single-height pitcher row. All elements vertically centred in ROW_H.

    [Logo] | [Name bold / Matchup muted] | [Grade badge] [Exp Ks K] | [p1] [p2] [p3] [p4]
    """
    row_bg = theme["row_even"] if idx % 2 == 0 else theme["row_odd"]
    draw.rectangle([0, y*S, CARD_W*S, (y+ROW_H)*S], fill=row_bg)

    team     = pitcher.get("team", "")
    opponent = pitcher.get("opponent", "")
    dark_bg  = theme["dark_bg"]

    # ── Logo — vertically centred ────────────────────────────────────────
    logo_px = LOGO_SZ * S
    logo    = _fetch_logo(team, logo_px, dark_bg)
    logo_y  = y*S + (ROW_H*S - logo_px) // 2
    img.paste(logo, (COL_LOGO*S, logo_y), logo)

    # ── Name (top) + Matchup (bottom) — stacked in left column ──────────
    last_name  = pitcher.get("pitcher", "Unknown").split()[-1]
    hand       = pitcher.get("pitcher_hand", "R")
    name_f     = _load_font(28*S, bold=True)
    sub_f      = _load_font(18*S, bold=False)
    name_label = f"{last_name}  ({hand}HP)"
    abbrev     = _resolve_abbrev(team) if team else ""
    opp_abbrev = _resolve_abbrev(opponent) if opponent else ""
    sub_label  = f"{abbrev}  vs  {opp_abbrev}"

    # Centre the two-line block vertically in the row
    block_h = _th(draw, name_label, name_f) + 6*S + _th(draw, sub_label, sub_f)
    text_top = y*S + (ROW_H*S - block_h) // 2
    draw.text((COL_NAME*S, text_top), name_label,
              fill=theme["text_primary"], font=name_f)
    draw.text((COL_NAME*S, text_top + _th(draw, name_label, name_f) + 6*S),
              sub_label, fill=theme["text_secondary"], font=sub_f)

    # ── Grade badge — vertically centred ────────────────────────────────
    grade     = pitcher.get("salci_grade", "C")
    grade_lbl = GRADE_TEXT.get(grade.upper(), grade)
    grade_col = _grade_color(grade, theme)
    gf        = _load_font(22*S, bold=True)
    gw        = _tw(draw, grade_lbl, gf)
    gh        = _th(draw, grade_lbl, gf)
    bw, bh    = gw + 20*S, gh + 12*S
    bx        = COL_GRADE * S
    by        = y*S + (ROW_H*S - bh) // 2
    draw.rounded_rectangle([bx, by, bx+bw, by+bh],
                            radius=6*S,
                            fill=_blend(grade_col, row_bg, 0.22),
                            outline=grade_col, width=2*S)
    draw.text((bx + 10*S, by + 6*S), grade_lbl, fill=grade_col, font=gf)

    # ── Expected Ks — big number + "K" label, vertically centred ────────
    exp     = pitcher.get("expected", "--")
    exp_str = str(exp)
    exp_f   = _load_font(42*S, bold=True)
    k_lbl_f = _load_font(20*S, bold=False)
    exp_h   = _th(draw, exp_str, exp_f)
    exp_x   = COL_EXP * S
    exp_y   = y*S + (ROW_H*S - exp_h) // 2
    draw.text((exp_x, exp_y), exp_str, fill=theme["accent"], font=exp_f)
    # "K" sits at the top-right of the number
    draw.text((exp_x + _tw(draw, exp_str, exp_f) + 3*S, exp_y + 4*S),
              "K", fill=theme["text_secondary"], font=k_lbl_f)

    # ── K-line pills — ALL 4 in a single horizontal row, sorted by K value
    k_lines = pitcher.get("k_lines", {}) or pitcher.get("lines", {}) or {}
    if k_lines:
        # Sort numerically by the K threshold (keys may be int or str)
        items  = sorted(k_lines.items(), key=lambda x: int(x[0]))[:4]
        pill_f = _load_font(17*S, bold=True)

        for i, (k_val, prob) in enumerate(items):
            pc = (34, 197, 94) if prob >= 65 else (234, 179, 8) if prob >= 45 else (239, 68, 68)
            pill_text = f"{k_val}+  {prob}%"
            pw = _tw(draw, pill_text, pill_f) + 22*S
            ph = _th(draw, pill_text, pill_f) + 12*S
            px = (COL_PILLS + i * PILL_SPACING) * S
            py = y*S + (ROW_H*S - ph) // 2
            draw.rounded_rectangle([px, py, px+pw, py+ph],
                                    radius=5*S,
                                    fill=_blend(pc, row_bg, 0.18),
                                    outline=pc, width=max(1, S))
            draw.text((px + 11*S, py + 6*S), pill_text, fill=pc, font=pill_f)


def _draw_footer(draw, theme, total_h, S):
    """Hashtags centred + SALCI watermark right."""
    fy = (total_h - FOOTER_H) * S
    draw.line([(PAD*S, fy+2*S), (CARD_W*S - PAD*S, fy+2*S)],
              fill=theme["divider"], width=S)

    hf = _load_font(18*S, bold=False)
    hw = _tw(draw, HASHTAGS, hf)
    draw.text(((CARD_W*S - hw) // 2, fy + 14*S), HASHTAGS,
              fill=theme["text_secondary"], font=hf)

    wf = _load_font(16*S, bold=False)
    ww = _tw(draw, "SALCI", wf)
    draw.text((CARD_W*S - ww - PAD*S, fy + 32*S), "SALCI",
              fill=theme["text_muted"], font=wf)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — GENERATE CARD
# ─────────────────────────────────────────────────────────────────────────────

def generate_card(pitchers: list, theme: dict,
                  card_type: str = "Today's Top Pitchers",
                  date_str: str = "") -> Image.Image:
    """
    Assemble the full shareable card.

    Renders at 2× (SCALE=2) and downsamples to CARD_W × total_h with
    Image.LANCZOS for sharp, anti-aliased output.

    Returns a PIL Image (RGB) at 1× dimensions.
    """
    if not date_str:
        date_str = datetime.now(
            pytz.timezone("America/New_York")
        ).strftime("%b %d, %Y")

    early, late = split_by_gametime(pitchers)
    has_groups  = bool(early or late)

    n_sections = sum([bool(early), bool(late)]) if has_groups else 0
    n_pitchers = (len(early) + len(late)) if has_groups else len(pitchers)
    total_h    = HEADER_H + n_sections * SECTION_H + n_pitchers * ROW_H + FOOTER_H

    # ── Render at 2× ─────────────────────────────────────────────────────
    S   = 2
    img  = Image.new("RGB", (CARD_W * S, total_h * S), theme["bg"])
    draw = ImageDraw.Draw(img)

    _draw_header(draw, img, theme, date_str, card_type, S)
    y = HEADER_H

    def _render_group(group, label):
        nonlocal y
        if not group:
            return
        y += _draw_section(draw, theme, label, y, S)
        for idx, p in enumerate(group):
            _draw_row(draw, img, theme, p, y, idx, S)
            y += ROW_H

    if has_groups:
        _render_group(early, "EARLY GAMES")
        _render_group(late,  "LATE GAMES")
    else:
        for idx, p in enumerate(pitchers):
            _draw_row(draw, img, theme, p, y, idx, S)
            y += ROW_H

    _draw_footer(draw, theme, total_h, S)

    # ── Downsample to 1× — LANCZOS gives sharp anti-aliased edges ────────
    img = img.resize((CARD_W, total_h), Image.LANCZOS)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def card_to_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes for a Streamlit download button."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
