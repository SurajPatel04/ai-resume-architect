"""The finished resume, as a one-column serif PDF built with Typst."""

import logging
import os
import re
import subprocess
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.graphs.state import ResumeState
from app.utils.pdf_style import icons_from, photo_from

logger = logging.getLogger(__name__)

FONTS = '("New Computer Modern", "Libertinus Serif", "Linux Libertine", "Georgia")'

SANS_FONTS = '("Inter", "Helvetica Neue", "Helvetica", "Liberation Sans", "Arial")'

SUBTITLE_MAX = 60

ICON_FONT = "FontAwesome"

# FontAwesome's private-use codepoints for the six things a contact line carries.
CONTACT_ICONS = (("location", "f041"), ("phone", "f095"), ("email", "f0e0"))
LINK_ICONS = (("website", "f0ac"), ("github", "f09b"), ("linkedin", "f08c"))

CONTACT_FIELDS = tuple(field for field, _ in CONTACT_ICONS + LINK_ICONS)

# How tall a cut-out icon is set beside its line.
ICON_HEIGHT = "1.5em"

# Typefaces the app carries itself, so a matched layout renders the same on a bare
# server as on a laptop with a full font library. Filled by scripts/fetch_fonts.py.
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static", "fonts")

def font_args() -> List[str]:
    """The flag that puts our own font directory on Typst's search path."""
    return ["--font-path", FONT_DIR] if os.path.isdir(FONT_DIR) else []

@lru_cache(maxsize=1)
def installed_fonts() -> frozenset:
    """Every font family Typst can see here, lowercased. Asked once."""
    try:
        listed = subprocess.run(["typst", "fonts", *font_args()],
                                capture_output=True, timeout=20, check=True)
        return frozenset(
            line.strip().casefold()
            for line in listed.stdout.decode(errors="replace").splitlines() if line.strip()
        )
    except Exception as e:
        logger.info("Could not list fonts (%r); falling back to the built-in stacks.", e)
        return frozenset()

def font_stack(wanted: str, fallback: str) -> str:
    """Their typeface first when this machine has it, then ours behind it.

    Named rather than substituted: Typst falls through a list, so an uninstalled family
    costs a warning and the next entry. Checking first is what keeps that warning out of
    the logs on every render and makes "why doesn't it match" answerable.
    """
    family = (wanted or "").strip()
    if family and family.casefold() in installed_fonts():
        return f'("{family}", ' + fallback.lstrip("(")
    if family:
        logger.info("Their resume is set in %r, which is not installed here.", family)
    return fallback

@lru_cache(maxsize=1)
def has_icon_font() -> bool:
    """Whether this machine can actually draw the icons.

    Asked once, and only when a matched layout wants them. Without the font Typst sets
    every icon as a blank box, which is a worse resume than one with no icons at all —
    so a server that lacks it silently gets the plain contact line.
    """
    try:
        listed = subprocess.run(["typst", "fonts", *font_args()],
                                capture_output=True, timeout=20, check=True)
        return ICON_FONT.casefold() in listed.stdout.decode(errors="replace").casefold()
    except Exception as e:
        logger.info("No icon font available (%r); contact lines stay plain.", e)
        return False

SECTION_KEYS = ("summary", "skills", "experience", "projects", "education", "certifications")

# What every type size below is judged against, before their own paper is taken in.
A4_WIDTH_IN = 8.27

# The only markers allowed through: an arbitrary string is unescaped markup.
MARKERS = {"•", "-", "–", "‣", "▪", "◦"}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

class Style(BaseModel):
    """The layout choices a resume makes, in the few dimensions worth reproducing."""

    font_family: Literal["serif", "sans"] = "serif"
    name_align: Literal["center", "left"] = "center"
    name_size_pt: float = 21.0
    name_color: str = ""
    heading_case: Literal["title", "upper"] = "title"
    heading_rule: bool = True
    accent_color: str = ""
    # Two columns often set their headings two different ways — the accent in the white
    # panel, plain white in the coloured band.
    heading_color: str = ""
    sidebar_heading_color: str = ""
    text_color: str = ""
    contact_icons: bool = False
    # Set from the file, never by the model: either a photo came out of their PDF or it
    # did not, and that is not a judgement call.
    photo: str = ""
    photo_shape: Literal["rect", "circle"] = "rect"
    # Not always the column the name is in: these designs put the portrait at the top of
    # the coloured band and the name across the panel beside it.
    photo_side: str = ""
    photo_width_in: float = 0.0
    # Their contact block, when their page gives it a heading of its own rather than
    # running the details under the name. Icons cut straight off the page, by field.
    contact_side: str = ""
    contact_title: str = ""
    icon_images: Dict[str, str] = Field(default_factory=dict)
    # One flowing list of skills, or labelled groups. Ours are stored in categories
    # because that is how they were collected, not because their resume showed them.
    skills_layout: Literal["", "flat", "grouped"] = ""
    margin_x_in: float = 0.0
    margin_y_in: float = 0.0

    # Measured off the document, never described by the model: the page is a rectangle
    # in points and the sidebar is a filled path with coordinates.
    page_width_in: float = 0.0
    page_height_in: float = 0.0
    background_color: str = ""
    sidebar_side: str = ""
    sidebar_width: float = 0.0
    sidebar_color: str = ""
    # How far in from the edge the band starts, and the framed card it sits on. Some
    # templates leave a strip of the card showing beside the band rather than running
    # it flush to the paper's edge.
    sidebar_offset: float = 0.0
    card_inset_in: float = 0.0
    card_color: str = ""
    main_color: str = ""
    body_font: str = ""
    heading_font: str = ""
    # Which side of a two-column page the name and contact block sit on, and which
    # sections share the coloured band with them. Both are read off the page: putting
    # skills in the sidebar was a rule of mine applied to every design alike.
    header_side: str = ""
    sidebar_sections: List[str] = Field(default_factory=list)
    heading_tracking_em: float = 0.0
    # Their point sizes. Applied as a ratio against the loosest density, so the ladder
    # can still tighten a document that runs long instead of being pinned by them.
    body_size_pt: float = 0.0
    heading_size_pt: float = 0.0
    bullet_marker: str = "•"
    section_order: List[str] = Field(default_factory=list)
    # What they call each section. "PROFILE" is not "Profile Summary".
    section_titles: Dict[str, str] = Field(default_factory=dict)

def clean_style(style: Any) -> Optional["Style"]:
    """A Style with anything unusable replaced by the default it stands in for."""
    if style is None:
        return None
    if isinstance(style, dict):
        try:
            style = Style.model_validate(style)
        except Exception as e:
            logger.warning("Unusable style spec, falling back to the site layout: %r", e)
            return None

    out = style.model_copy()

    if not _HEX.match(out.accent_color or ""):
        out.accent_color = ""
    if not _HEX.match(out.text_color or ""):
        out.text_color = ""
    if not _HEX.match(out.background_color or ""):
        out.background_color = ""
    if not _HEX.match(out.sidebar_color or ""):
        out.sidebar_color = ""
    if not _HEX.match(out.main_color or ""):
        out.main_color = ""
    if not _HEX.match(out.card_color or ""):
        out.card_color = ""
    # A band pushed more than a third of the way in is a misread of the geometry.
    out.sidebar_offset = float(min(max(out.sidebar_offset or 0.0, 0.0), 0.33))
    # A frame wider than this is a border nobody would print.
    out.card_inset_in = float(out.card_inset_in) if 0.02 <= (out.card_inset_in or 0) <= 1.0 \
        else 0.0
    if not _HEX.match(out.name_color or ""):
        out.name_color = ""
    if not _HEX.match(out.heading_color or ""):
        out.heading_color = ""
    if not _HEX.match(out.sidebar_heading_color or ""):
        out.sidebar_heading_color = ""
    if out.sidebar_side not in ("left", "right") or not out.sidebar_color:
        out.sidebar_side, out.sidebar_width, out.sidebar_color = "", 0.0, ""
    out.sidebar_width = float(min(max(out.sidebar_width or 0, 0.15), 0.48))
    # A page smaller than a postcard or bigger than a poster is a misread, not a design.
    for side in ("page_width_in", "page_height_in"):
        size = float(getattr(out, side) or 0)
        setattr(out, side, size if 4 <= size <= 20 else 0.0)
    if out.bullet_marker not in MARKERS:
        out.bullet_marker = "•"
    if out.header_side not in ("sidebar", "main"):
        out.header_side = ""
    if out.photo_side not in ("sidebar", "main"):
        out.photo_side = ""
    if out.contact_side not in ("sidebar", "main"):
        out.contact_side = ""
    for edge in ("margin_x_in", "margin_y_in"):
        size = float(getattr(out, edge) or 0)
        setattr(out, edge, size if 0.15 <= size <= 1.5 else 0.0)
    out.contact_title = re.sub(r"\s+", " ", str(out.contact_title or "").strip())[:42]
    out.icon_images = {
        field: str(name).strip()
        for field, name in (out.icon_images or {}).items()
        if field in CONTACT_FIELDS and str(name or "").strip()
    }
    # Wider than half the page is not a portrait, it is the page.
    widest = (out.page_width_in or A4_WIDTH_IN) / 2
    out.photo_width_in = float(out.photo_width_in) \
        if 0.4 <= (out.photo_width_in or 0) <= widest else 0.0
    # Wider than this stops being a design and starts being one word per line.
    out.heading_tracking_em = float(min(max(out.heading_tracking_em or 0.0, 0.0), 0.25))

    # Type is judged against the paper it is set on. A Canva sheet is landscape A3 —
    # twice the width of A4 — and everything on it is sized to match: 17pt body, 38pt
    # headings, a 51pt name. Held to a portrait page's limits those all read as misreads
    # and were thrown away, which left correct measurements rendering as 10pt text
    # marooned on a 16-inch page.
    paper = (out.page_width_in or A4_WIDTH_IN) / A4_WIDTH_IN

    def in_range(size: float, low: float, high: float) -> float:
        return float(size) if low <= (size or 0) <= high * paper else 0.0

    out.body_size_pt = in_range(out.body_size_pt, 7, 14)
    out.heading_size_pt = in_range(out.heading_size_pt, 8, 22)
    out.name_size_pt = float(min(max(out.name_size_pt or 21, 14), 30 * paper))

    out.section_titles = {
        key: re.sub(r"\s+", " ", str(title).strip())
        for key, title in (out.section_titles or {}).items()
        if key in SECTION_KEYS and str(title or "").strip()
        and len(str(title).strip()) <= 42
    }

    aside, seen_aside = [], set()
    for key in out.sidebar_sections or []:
        if key in SECTION_KEYS and key not in seen_aside:
            seen_aside.add(key)
            aside.append(key)
    out.sidebar_sections = aside

    seen, order = set(), []
    for key in out.section_order or []:
        if key in SECTION_KEYS and key not in seen:
            seen.add(key)
            order.append(key)
    # Anything they had no heading for keeps its usual place rather than vanishing off
    # the page. The summary leads: a resume that gives it no heading is one that runs it
    # as a paragraph under the name, not one that buries it under the last section.
    missing = [k for k in SECTION_KEYS if k not in seen]
    lead = ["summary"] if "summary" in missing else []
    out.section_order = lead + order + [k for k in missing if k not in lead]

    return out

PAGE_LIMIT = 1

class Density:
    """How tightly the page is set. Three steps, and the last one is the floor."""

    def __init__(self, text, heading, leading, par_spacing, margin_x, margin_y,
                 list_spacing, above, below):
        self.text, self.heading, self.leading = text, heading, leading
        self.par_spacing = par_spacing
        self.margin_x, self.margin_y = margin_x, margin_y
        self.list_spacing, self.above, self.below = list_spacing, above, below

DENSITIES = [
    Density(10.0, 12.5, 0.78, 0.78, 0.60, 0.55, 0.65, 1.15, 0.70),
    Density(9.75, 12.0, 0.72, 0.70, 0.55, 0.50, 0.58, 1.00, 0.62),
    Density(9.5, 11.5, 0.65, 0.62, 0.50, 0.45, 0.50, 0.85, 0.55),
]

# Tried in order until the document fits. Typography only: every step here is the same
# words set closer together, so nothing runs without the user's knowledge. Taking lines
# off the page is a decision, and decisions are asked about rather than made.
FIT_LADDER = [0, 1, 2]

# What a bullet trim leaves per entry, when the user chooses one.
TRIMMED_BULLETS = 2

FIT_SECTION = "fit_page"

KEEP_CHIP = "Keep it on two pages"

TRIM_CHIP = f"Show only my strongest {TRIMMED_BULLETS} bullets"

ALL_CHIP = "Leave out the whole section"

# Sections held as a list of entries, where "drop projects" is worth narrowing to
# "drop which project". summary and skills are one block each; there is nothing to pick.
ENTRY_SECTIONS = ("experience", "projects", "education", "certifications")

# What a user may take off the page. Basics and experience are never offered.
SECTION_LABELS = {
    "summary": "Profile summary",
    "certifications": "Certifications",
    "projects": "Projects",
    "skills": "Technical skills",
    "education": "Education",
    "experience": "Professional experience",
}

DROPPABLE = {
    "summary": "Profile summary",
    "certifications": "Certifications",
    "projects": "Projects",
    "skills": "Technical skills",
    "education": "Education",
}

# What an extractor writes when it found nothing. A resume that says "Not Specified"
# where the company should be is worse than one that says nothing there: the reader is
# told, twice a line, exactly what the candidate failed to provide. Absent is absent.
PLACEHOLDERS = {
    "not specified", "notspecified", "unspecified", "not available", "not provided",
    "not mentioned", "not applicable", "unknown", "none", "n/a", "na", "nil", "tbd",
    "to be determined", "-", "--", "?", "null", "undefined", "present unknown", "",
}

def real(value: Any) -> str:
    """The value, or "" when it is a stand-in for not having one."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold().strip(".") in PLACEHOLDERS else text

def escape_typst(text: Any) -> str:
    """Neutralise Typst markup in user text, and drop stand-ins for missing data."""
    out = real(text)
    if not out:
        return ""
    for char in ("\\", "*", "_", "$", "<", ">", "@", "[", "]", "#", "`"):
        out = out.replace(char, "\\" + char)
    return out

def joined(*parts: Any, sep: str = "  |  ") -> str:
    """Escaped parts with separators only between the ones that exist."""
    return sep.join(escape_typst(p) for p in parts if p and str(p).strip())

def date_range(start: Any, end: Any) -> str:
    """'Jul 2024 – Jun 2026', or whichever half exists."""
    return " – ".join(text for text in (real(start), real(end)) if text)

def dated(left: str, right: str) -> str:
    """A title row: markup on the left, dates pushed to the right margin."""
    right = escape_typst(right)
    return f"{left} #h(1fr) {right}" if right else left

def rows(*lines: str) -> str:
    """Stack lines inside one entry, tight, using Typst's linebreak."""
    return " \\\n".join(line for line in lines if line)

def bullets(items: Any, cap: Any = None) -> List[str]:
    """The entry's highlights, strongest first, optionally only the strongest `cap`."""
    kept = [item for item in (items or []) if str(item).strip()]
    if cap is not None:
        kept = kept[:cap]
    return [f"- {escape_typst(item)}" for item in kept]

PHOTO_WIDTH = "1.05in"

# What goes in the sidebar of a two-column resume. Contact and the short, listy
# sections; the narrative ones need the width. Matches how these designs are built —
# a 32%-wide column cannot hold a bullet about a rendering pipeline.
SIDEBAR_SECTIONS = ("skills", "education", "certifications")

SIDEBAR_INSET = "1.1em"

# A column narrower than this is rounding, not a column. And the panel holding the
# narrative sections never shrinks below a readable share of the page.
MIN_COLUMN = 0.005
MIN_PANEL = 0.3

def luminance_of(hex_colour: str) -> float:
    """Perceived brightness of a #rrggbb string, 0 (black) to 255 (white)."""
    value = int((hex_colour or "#000000").lstrip("#") or 0, 16)
    return 0.299 * ((value >> 16) & 255) + 0.587 * ((value >> 8) & 255) + 0.114 * (value & 255)

def _page_setup(d: "Density", style: Optional[Style]) -> str:
    """The #set page line: their paper size and page fill when measured, else ours."""
    width = style.page_width_in if style and style.page_width_in else 0
    height = style.page_height_in if style and style.page_height_in else 0
    paper = f"width: {width}in, height: {height}in, " if width and height else ""
    fill = f', fill: rgb("{style.background_color}")' if style and style.background_color else ""

    if style and style.card_inset_in:
        # A framed card: the page fill shows as a border and everything else sits
        # inside it. Their strip of colour around the edge is part of the design.
        return f"#set page({paper}margin: {style.card_inset_in}in{fill})"

    if style and style.sidebar_color:
        # The columns carry their own insets, so the page itself has no margin.
        return f"#set page({paper}margin: 0pt{fill})"

    # Their margins, scaled by however far down the fitting ladder this render is, so a
    # document that runs long can still be tightened rather than being pinned to them.
    across = _scaled(style.margin_x_in if style else 0, d.margin_x, DENSITIES[0].margin_x)
    down = _scaled(style.margin_y_in if style else 0, d.margin_y, DENSITIES[0].margin_y)
    return f"#set page({paper}margin: (x: {across}in, y: {down}in){fill})"

def _icon(code: str) -> str:
    return f'#text(font: "{ICON_FONT}", size: 8.5pt)[\\u{{{code}}}]'

def _glyph(field: str, code: str, style: Optional[Style]) -> str:
    """The icon for one contact detail, as markup, or "" if there is none to draw.

    Their own glyph first. These are cut off their page as pictures, so they are the
    right ones by construction — no icon font has to be installed and no guess is made
    about which set they used. FontAwesome is the fallback, and a plain line is the
    fallback to that.
    """
    picture = (style.icon_images or {}).get(field) if style else ""
    if picture:
        return f'#box(baseline: 0.2em, image("{picture}", height: {ICON_HEIGHT}))'
    if style and style.contact_icons and has_icon_font():
        return _icon(code)
    return ""

def _contact_items(basics: Dict[str, Any], fields: tuple,
                   style: Optional[Style]) -> List[str]:
    """Each contact detail present, escaped, with its glyph in front when there is one."""
    out = []
    for key, code in fields:
        text = escape_typst(basics.get(key))
        if not text:
            continue
        glyph = _glyph(key, code, style)
        out.append(f"{glyph} {text}" if glyph else text)
    return out

def _contact_block(basics: Dict[str, Any], style: Style, heading_lines: List[str]) -> List[str]:
    """The contact details as a section of their own, headed the way they head it.

    Their glyphs are pictures taken off their own page, so this needs no icon font and
    matches whatever set they chose. Falling back to FontAwesome, and then to nothing,
    keeps a resume readable on a server that has neither.
    """
    # Their order first — the icons came off the page top to bottom — then anything they
    # had no glyph for, in ours.
    codes = dict(CONTACT_ICONS + LINK_ICONS)
    order = [f for f in style.icon_images if f in codes]
    order += [f for f in codes if f not in order]

    rows_out = []
    for field, code in ((f, codes[f]) for f in order):
        text = escape_typst(basics.get(field))
        if not text:
            continue
        picture = style.icon_images.get(field)
        if picture:
            glyph = f'image("{picture}", height: {ICON_HEIGHT})'
        elif style.contact_icons and has_icon_font():
            glyph = f'text(font: "{ICON_FONT}")[\\u{{{code}}}]'
        else:
            glyph = "[]"
        rows_out.append(f"  {glyph}, [{text}],")

    if not rows_out:
        return []

    return [
        *heading_lines,
        "#grid(columns: (auto, 1fr), column-gutter: 0.7em, row-gutter: 0.6em,",
        "  align: horizon,",
        *rows_out,
        ")",
    ]

def _picture(style: Optional[Style]) -> str:
    """Their photo, at their size, cut to the shape their page cuts it to."""
    photo = style.photo if style else ""
    if not photo:
        return ""

    width = f"{style.photo_width_in}in" if style.photo_width_in else PHOTO_WIDTH

    # A round crop is a square image inside a clipped, fully-rounded box. Cut to "cover"
    # so the face keeps its proportions instead of being squashed into the square.
    if style.photo_shape == "circle":
        return (f'box(clip: true, radius: 50%, width: {width}, height: {width}, '
                f'image("{photo}", width: 100%, height: 100%, fit: "cover"))')
    return f'image("{photo}", width: {width})'

def _photo_block(style: Optional[Style]) -> List[str]:
    """The photo alone, centred — for the column that has it without the name."""
    picture = _picture(style)
    return [f"#align(center)[#{picture}]", "#v(0.8em)"] if picture else []

# The contact line sits a little under the body, whatever the body turns out to be.
CONTACT_RATIO = 0.9

def _header(basics: Dict[str, Any], style: Optional[Style] = None, stacked: bool = False,
            photo: bool = True, text_pt: float = 10.0, details: bool = True) -> List[str]:
    name = escape_typst(basics.get("name"))
    # Nothing here when the details have a headed block of their own further down.
    contact = _contact_items(basics, CONTACT_ICONS, style) if details else []
    links = _contact_items(basics, LINK_ICONS, style) if details else []
    icons = any(_glyph(key, code, style) for key, code in CONTACT_ICONS + LINK_ICONS)

    size = style.name_size_pt if style else 21.0
    align = style.name_align if style else "center"

    # Whatever colour their name is actually set in. It is often neither the accent nor
    # the body ink — white over a dark band, most often — and inferring it from the
    # accent put an orange name on a navy sidebar that had a white one.
    tint = (style.name_color or style.accent_color) if style else ""
    fill = f', fill: rgb("{tint}")' if tint else ""

    # Set against the body rather than pinned: 9pt is a caption on A4 and unreadable on
    # the landscape A3 sheet these templates export.
    detail = round(text_pt * CONTACT_RATIO, 1)

    stack = [f'#text(size: {size}pt, weight: "bold"{fill})[{name}]']
    if stacked:
        # A narrow band cannot hold "city | phone | email" on one line; their own
        # sidebars put one detail per row, and so does this.
        stack += [f"#text(size: {detail}pt)[{item}]" for item in contact + links]
    else:
        # Typst collapses runs of spaces, so icon-led items need real width between
        # them or the phone number and the email address touch.
        separator = " #h(0.9em) " if icons else "  |  "
        for group in (contact, links):
            if group:
                stack.append(f"#text(size: {detail}pt)[{separator.join(group)}]")

    block = [f"#align({align})[", "  " + " \\\n  ".join(stack), "]"]

    picture = _picture(style) if photo else ""
    if not picture:
        return block

    if stacked:
        # A narrow column has no room for two things side by side: the picture goes
        # above the name, which is how these sidebars are always built.
        return [f"#align(center)[#{picture}]", "#v(0.6em)"] + block

    # Set opposite the name. A centred name keeps the middle and the photo takes the
    # right margin, which is where a resume that has one almost always puts it.
    return [
        "#grid(columns: (1fr, auto), column-gutter: 0.8em, align: horizon,",
        f"  align({align})[",
        "    " + " \\\n    ".join(stack),
        "  ],",
        f"  {picture},",
        ")",
    ]

def _skills(skills: List[Dict[str, Any]], flat: bool = False) -> List[str]:
    """The skills block, grouped under their category labels or run together as one.

    Grouped is our storage shape, not necessarily their resume's. A page that lists
    skills as one comma-separated run and gets seven bold labels back is not a copy of
    itself, and the labels cost six lines on a resume already fighting for the page.
    """
    if flat:
        every = [str(k).strip()
                 for category in skills or []
                 for k in (category.get("keywords") or []) if str(k).strip()]
        return [escape_typst(", ".join(dict.fromkeys(every)))] if every else []

    lines = []
    for category in skills or []:
        keywords = ", ".join(str(k).strip() for k in (category.get("keywords") or []) if str(k).strip())
        if not keywords:
            continue
        label = escape_typst(category.get("name")) or "Skills"
        lines.append(f"*{label}:* {escape_typst(keywords)}")
    return [rows(*lines)] if lines else []

def _experience(experience: List[Dict[str, Any]], cap: Any = None) -> List[str]:
    body: List[str] = []
    for job in experience or []:

        title = escape_typst(job.get("position")) or escape_typst(job.get("company"))
        if not title and not job.get("highlights"):
            continue

        under = escape_typst(job.get("company")) if job.get("position") else ""
        place = escape_typst(job.get("location"))
        if place:
            under = f"{under}, {place}" if under else place

        body.append(rows(
            dated(f"*{title}*", date_range(job.get("start_date"), job.get("end_date"))),
            f"_{under}_" if under else "",
        ))
        body.extend(bullets(job.get("highlights"), cap))
        body.append("")
    return body

def _projects(projects: List[Dict[str, Any]], cap: Any = None) -> List[str]:
    body: List[str] = []
    for project in projects or []:
        name = escape_typst(project.get("name"))
        if not name and not project.get("highlights"):
            continue

        description = (project.get("description") or "").strip()
        subtitle = escape_typst(description) if 0 < len(description) <= SUBTITLE_MAX else ""

        body.append(rows(
            f"*{name}* – {subtitle}" if subtitle else f"*{name}*",
            f'#text(size: 8.5pt)[{escape_typst(project.get("url"))}]' if project.get("url") else "",
        ))

        # A description short enough to sit beside the title is a subtitle. One too long
        # for that is prose about the project — the same kind of thing as a highlight,
        # and setting it as a bare paragraph above the bullets made the first line of
        # every project the one without a dot in front of it.
        lines = list(project.get("highlights") or [])
        if description and not subtitle:
            lines.insert(0, description)
        body.extend(bullets(lines, cap))
        body.append("")
    return body

def _education(education: List[Dict[str, Any]]) -> List[str]:
    body: List[str] = []
    for entry in education or []:
        degree = escape_typst(entry.get("study_type"))
        area = escape_typst(entry.get("area"))
        title = " in ".join(x for x in (degree, area) if x) or escape_typst(entry.get("institution"))
        if not title:
            continue

        institution = escape_typst(entry.get("institution"))

        under = f"_{institution}_" if institution and title != institution else ""
        if entry.get("gpa"):
            grade = escape_typst(f"GPA: {entry['gpa']}")
            under = f"{under} #h(1fr) _{grade}_" if under else f"_{grade}_"

        body.append(rows(
            dated(f"*{title}*", date_range(entry.get("start_date"), entry.get("end_date"))),
            under,
        ))
        body.append("")
    return body

def _certifications(certifications: List[Dict[str, Any]]) -> List[str]:
    body: List[str] = []
    for cert in certifications or []:
        name = escape_typst(cert.get("name"))
        if not name:
            continue
        issuer = escape_typst(cert.get("issuer"))
        credential_url = escape_typst(cert.get("url"))
        details = issuer
        if credential_url:
            details = f"{details} | Credential: {credential_url}" if details else f"Credential: {credential_url}"
        body.append(rows(
            dated(f"*{name}*", cert.get("date") or ""),
            f'_{details}_' if details else "",
        ))
        body.append("")
    return body

# Below this the ink and the paper it is on are too close together to read.
CONTRAST = 45

def _ink(colour: str, against: str, fallback: str) -> str:
    """A Typst colour: theirs when it can be read on `against`, otherwise `fallback`.

    Copying a colour off their page is the point, but a heading the same shade as the
    panel behind it is not a match — it is an invisible section.
    """
    if colour and abs(luminance_of(colour) - luminance_of(against)) >= CONTRAST:
        return f'rgb("{colour}")'
    return fallback

def _scaled(measured: float, step: float, loosest: float) -> float:
    """Their point size, tightened by however far down the ladder this render is.

    Pinning the size outright would take the fitting ladder away: a resume set at 11pt
    that runs to two pages could never be brought back onto one. Scaling keeps their
    proportions and still leaves every rung of the ladder something to do.
    """
    if not measured or not loosest:
        return step
    # Three places, not two: margins are inches, and 0.365 rounded to 0.36 moves the
    # text block by a quarter of a millimetre for no reason.
    return round(measured * step / loosest, 3)

def _heading_block(d: "Density", style: Optional[Style], ink: str = "",
                   size: float = 0.0) -> List[str]:
    """The show-rule that draws every section heading.

    `ink` overrides the colour for a column that sets its own — light headings on a dark
    band. Everything else about how a heading is set is the same in both columns, and
    was worth having in one place rather than written out three times.
    """
    if ink:
        colour = ink
    elif style:
        paper = style.background_color or "#ffffff"
        colour = _ink(style.heading_color, paper, _ink(style.accent_color, paper, "black"))
    else:
        colour = "black"
    body = "upper(it.body)" if style and style.heading_case == "upper" else "it.body"

    # Measured off their page when it could be; otherwise the small amount of tracking
    # that stops all-caps headings reading as one long word.
    tracked = style.heading_tracking_em if style else 0.0
    if not tracked and style and style.heading_case == "upper":
        tracked = 0.06
    tracking = f", tracking: {tracked}em" if tracked else ""

    # Headings are often set in a second face. Named only when this machine has it —
    # falling through to the body font is what an uninstalled family would do anyway.
    wanted = (style.heading_font if style else "") or ""
    font = f'font: "{wanted}", ' if wanted.casefold() in installed_fonts() else ""

    out = [
        f"#show heading: it => block(above: {d.above}em, below: {d.below}em, width: 100%)[",
        f'  #text({font}size: {size or d.heading}pt, weight: "bold", '
        f"fill: {colour}{tracking})[#{body}]",
    ]
    if not style or style.heading_rule:
        out += ["  #v(-0.62em)", f"  #line(length: 100%, stroke: 0.7pt + {colour})"]
    out.append("]")
    return out

def _custom(entries: List[Dict[str, Any]], cap: Any = None) -> List[str]:
    """A section the schema does not model, set like every other one."""
    body: List[str] = []
    for entry in entries or []:
        title = escape_typst(entry.get("title"))
        if not title and not entry.get("highlights"):
            continue

        subtitle = escape_typst(entry.get("subtitle"))
        body.append(rows(
            dated(f"*{title}*" if title else "", entry.get("date") or ""),
            f"_{subtitle}_" if subtitle else "",
        ))
        body.extend(bullets(entry.get("highlights"), cap))
        body.append("")
    return body

def custom_titles(r: Dict[str, Any]) -> List[str]:
    """The headings this resume carries beyond the ones the schema names."""
    return [
        str(section.get("name") or "").strip()
        for section in (r.get("custom_sections") or [])
        if isinstance(section, dict) and str(section.get("name") or "").strip()
        and (section.get("entries") or [])
    ]

def build_typst(
    r: Dict[str, Any],
    density: int = 0,
    bullet_cap: Any = None,
    dropped: Any = (),
    style: Any = None,
    dropped_entries: Any = (),
) -> str:
    """The whole document. Pure, so the layout can be checked without a PDF."""
    d = DENSITIES[max(0, min(density, len(DENSITIES) - 1))]
    dropped = set(dropped or ())
    gone = set(dropped_entries or ())
    style = clean_style(style)

    def kept(section: str) -> List[Dict[str, Any]]:
        """The section's entries minus the individual ones left off the page."""
        return [entry for index, entry in enumerate(r.get(section) or [])
                if f"{section}[{index}]" not in gone]

    basics = r.get("basics") or {}
    summary = ((r.get("summary") or {}).get("content") or "").strip()

    default = SANS_FONTS if style and style.font_family == "sans" else FONTS
    fonts = font_stack(style.body_font if style else "", default)
    marker = style.bullet_marker if style else "•"
    ink = f', fill: rgb("{style.text_color}")' if style and style.text_color else ""

    # Their point sizes, scaled by how far down the fitting ladder this render is.
    text_pt = _scaled(style.body_size_pt if style else 0, d.text, DENSITIES[0].text)
    heading_pt = _scaled(style.heading_size_pt if style else 0,
                         d.heading, DENSITIES[0].heading)

    out = [
        f'#set document(title: "{escape_typst(basics.get("name")) or "Resume"}")',
        _page_setup(d, style),
        f"#set text(font: {fonts}, size: {text_pt}pt{ink})",
        # leading: gaps between wrapped lines. spacing: gaps between blocks.
        f"#set par(leading: {d.leading}em, spacing: {d.par_spacing}em, justify: false)",
        f"#set list(marker: [{marker}], indent: 0.2em, body-indent: 0.45em, spacing: {d.list_spacing}em)",
        "",
    ]

    two_column = bool(style and style.sidebar_color)
    if not two_column:
        # Their accent reaches every bold run — job titles, project names, skill labels —
        # not only the section headings. A resume whose colour stops at the six headings
        # does not look like the coloured resume it was copied from. Body text stays
        # black either way: that is legibility, not taste.
        #
        # A two-column page sets both of these per column instead: each one carries its
        # own ink, and a rule out here would only be shadowed by them.
        if style and style.accent_color:
            out.append(f'#show strong: set text(fill: rgb("{style.accent_color}"))')
        out.extend(_heading_block(d, style, size=heading_pt))
    out.append("")

    def titled(key: str, ours: str) -> str:
        """What they call this section, or what we call it if they had no name for it."""
        theirs = (style.section_titles.get(key) if style else "") or ""
        return escape_typst(theirs) or ours

    bodies = {
        "summary": (titled("summary", "Profile Summary"),
                    [escape_typst(summary)] if summary else []),
        "skills": (titled("skills", "Technical Skills"),
                   _skills(r.get("skills"), flat=bool(style and style.skills_layout == "flat"))),
        "experience": (titled("experience", "Professional Experience"),
                       _experience(kept("experience"), bullet_cap)),
        "projects": (titled("projects", "Projects"), _projects(kept("projects"), bullet_cap)),
        "education": (titled("education", "Education"), _education(kept("education"))),
        "certifications": (titled("certifications", "Certifications"),
                           _certifications(kept("certifications"))),
    }

    # Named sections first, then whatever else the candidate's own resume carried.
    for section in (r.get("custom_sections") or []):
        if not isinstance(section, dict):
            continue
        name = str(section.get("name") or "").strip()
        if name:
            bodies[f"custom:{name}"] = (name, _custom(section.get("entries"), bullet_cap))

    order = list(style.section_order if style else SECTION_KEYS)
    order += [key for key in bodies if key.startswith("custom:") and key not in order]

    def section_lines(keys) -> List[str]:
        lines: List[str] = []
        for key in keys:
            title, body = bodies.get(key, ("", []))
            if key in dropped or title in dropped or not any(line.strip() for line in body):
                continue
            lines.append("")
            lines.append(f"= {title}")
            lines.append("#pad(left: 0.5em)[")
            lines.extend(body)
            lines.append("]")
        return lines

    if not two_column:
        out.extend(_header(basics, style, text_pt=text_pt))
        out.extend(section_lines(order))
        return "\n".join(out) + "\n"

    # Two columns, the way their document is built. Which sections share the coloured
    # band is read off their page; the constant is only the fallback for a document
    # whose headings could not be placed.
    in_band = style.sidebar_sections or SIDEBAR_SECTIONS
    aside = [key for key in order if key in in_band]
    main = [key for key in order if key not in in_band]

    # A dark band needs light text. That is legibility, not a style guess.
    ink = "white" if luminance_of(style.sidebar_color) < 128 else "black"

    # The columns span the card, not the paper, so the measured fractions — which are of
    # the paper — have to be rescaled by however much of it the frame takes.
    frame = (style.card_inset_in / style.page_width_in) if style.page_width_in else 0.0
    usable = max(1 - 2 * frame, 0.01)
    gutter = max((style.sidebar_offset or 0.0) - frame, 0.0) / usable
    fraction = (style.sidebar_width or 0.32) / usable
    rest = max(1 - gutter - fraction, MIN_PANEL)

    # These designs set the body on its own panel. Without an explicit fill it inherits
    # the page colour, which is the sidebar's — and the whole page comes out dark.
    panel = style.main_color or "#ffffff"
    body_ink = "black" if luminance_of(panel) >= 128 else "white"

    # The name and the photo go where their page puts them, which is not always the same
    # column: this design sets the portrait at the top of the band and the name across
    # the panel beside it.
    header_col = style.header_side or "sidebar"
    photo_col = style.photo_side or header_col
    together = photo_col == header_col

    # Their contact details are a section in their own right when their page heads them
    # as one, and they do not belong under the name as well.
    contact_col = style.contact_side if style.contact_title else ""
    contact = _contact_block(basics, style,
                             [f"= {escape_typst(style.contact_title)}"]) if contact_col else []

    header = _header(basics, style, stacked=header_col == "sidebar", photo=together,
                     text_pt=text_pt, details=not contact)
    lone_photo = [] if together else _photo_block(style)

    def opening(column: str) -> List[str]:
        return ([*lone_photo] if photo_col == column else []) + \
               ([*header] if header_col == column else []) + \
               ([*contact] if contact_col == column else [])

    # No leading "#" on the opening line of either: inside #grid(...) Typst is already
    # in code mode.
    side = [
        f'block(width: 100%, height: 100%, fill: rgb("{style.sidebar_color}"), inset: {SIDEBAR_INSET})[',
        f"#set text(fill: {ink})",
        *_heading_block(d, style,
                        ink=_ink(style.sidebar_heading_color, style.sidebar_color, ink),
                        size=heading_pt),
        f"#show strong: set text(fill: {ink})",
        *opening("sidebar"),
        *section_lines(aside),
        "]",
    ]
    body = [
        f'block(width: 100%, height: 100%, fill: rgb("{panel}"), inset: {SIDEBAR_INSET})[',
        f"#set text(fill: {body_ink})",
        *_heading_block(d, style, size=heading_pt,
                        ink=_ink(style.heading_color, panel,
                                 _ink(style.accent_color, panel, body_ink))),
        f"#show strong: set text(fill: {body_ink})",
        *opening("main"),
        *section_lines(main),
        "]",
    ]

    # A strip of the card showing beside the band, when their page leaves one. Without
    # it the band runs to the paper's edge and the frame they drew disappears.
    strip = [f'block(width: 100%, height: 100%, fill: rgb("{style.card_color or panel}"))']

    order_of = [(gutter, strip), (fraction, side), (rest, body)]
    if style.sidebar_side != "left":
        order_of = [(rest, body), (fraction, side), (gutter, strip)]
    order_of = [(share, column) for share, column in order_of if share > MIN_COLUMN]

    widths = ", ".join(f"{round(share, 4)}fr" for share, _ in order_of)
    out.append(f"#grid(columns: ({widths}), rows: (100%),")
    for index, (_, column) in enumerate(order_of):
        if index:
            out.append(",")
        out.extend(column)
    out.append(")")

    return "\n".join(out) + "\n"

def page_count(pdf_path: str) -> int:
    """Pages in the PDF just written, or 1 if that cannot be established.

    Falling back to 1 makes an unreadable PDF look like it fits, which is deliberate:
    the only thing this number decides is whether to start taking things off the page.
    """
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
    except Exception as e:
        logger.warning("Could not read the page count back from %s: %r", pdf_path, e)
        return 1

def droppable_now(r: Dict[str, Any], dropped: Any = ()) -> List[str]:
    """The sections actually on this resume that the user could still take off it."""
    dropped = set(dropped or ())
    present = []
    for key, label in DROPPABLE.items():
        if key in dropped:
            continue
        value = (r.get("summary") or {}).get("content") if key == "summary" else r.get(key)
        if value:
            present.append(label)
    return present

def has_trimmable_bullets(r: Dict[str, Any]) -> bool:
    """Whether trimming to the strongest few would actually take anything off."""
    return any(
        len(entry.get("highlights") or []) > TRIMMED_BULLETS
        for section in ("experience", "projects")
        for entry in (r.get(section) or []) if isinstance(entry, dict)
    )

def entry_names(section: str, r: Dict[str, Any], dropped_entries: Any = ()) -> List[tuple]:
    """(path, label) for each entry of `section` still on the page."""
    dropped_entries = set(dropped_entries or ())
    out = []
    for index, entry in enumerate(r.get(section) or []):
        path = f"{section}[{index}]"
        if not isinstance(entry, dict) or path in dropped_entries:
            continue
        if section == "experience":
            label = " at ".join(x for x in (entry.get("position"), entry.get("company")) if x)
        elif section == "education":
            label = entry.get("study_type") or entry.get("area") or entry.get("institution")
        else:
            label = entry.get("name")
        out.append((path, (label or "").strip() or f"Entry {index + 1}"))
    return out

def entry_question(section: str, r: Dict[str, Any], dropped_entries: Any = ()) -> Dict[str, Any]:
    """Having picked a section, ask which of its entries to leave off."""
    entries = entry_names(section, r, dropped_entries)
    label = SECTION_LABELS.get(section, DROPPABLE.get(section, section.title()))

    return {
        "field": "system",
        "section": FIT_SECTION,
        "question_text": (
            f"Which of these should come off {label.lower()}? "
            "Pick one at a time, or leave the section out altogether."
        ),
        "ui": "chips",
        "options": [name for _, name in entries] + [ALL_CHIP, KEEP_CHIP],
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,
        "meta": {"pick_section": section, "entries": [
            {"path": path, "label": name} for path, name in entries
        ]},
    }

def fit_question(r: Dict[str, Any], pages: int, dropped: Any = (),
                 trimmed: bool = False) -> Dict[str, Any]:
    """Ask what to lose, having already tried everything that loses nothing."""
    options = droppable_now(r, dropped)
    if not trimmed and has_trimmable_bullets(r):
        options = [TRIM_CHIP] + options
    return {
        "field": "system",
        "section": FIT_SECTION,
        "question_text": (
            f"Your resume runs to {pages} pages even set as tightly as I can read it. "
            "What should come off to get it onto one? Nothing is deleted from your "
            "profile — say the word and I'll put it back."
        ),
        "ui": "chips",
        "options": options + [KEEP_CHIP],
        "is_gate": False,
        "missing_fields": [],
        "bullet_index": None,
    }

def _read_drop(answer: str, r: Dict[str, Any]) -> Any:
    """Which section they chose, by chip label or by naming it."""
    reply = (answer or "").strip().casefold()
    for key, label in DROPPABLE.items():
        if reply == label.casefold() or (key in reply and reply):
            return key
    return None

def render_resume(state: ResumeState) -> Dict[str, Any]:
    """Renders the tailored resume, or the master profile, into a PDF using Typst."""
    logger.info("Rendering resume to PDF...")

    generated = state.get("generated_resumes", {})
    resume = generated.get("tailored") or state.get("master_profile", {})
    r = (resume.model_dump() if hasattr(resume, "model_dump") else resume) or {}

    dropped = list(state.get("dropped_sections") or [])
    waived = bool(state.get("page_limit_waived"))
    cap = state.get("bullet_cap")
    gone = list(state.get("dropped_entries") or [])
    answered: Dict[str, Any] = {}

    pending = state.get("current_question") or {}
    answer = state.get("latest_answer")
    if answer and pending.get("section") == FIT_SECTION:
        answered = {"latest_answer": None, "current_question": None}
        if answer.strip() == KEEP_CHIP:
            waived = True
            answered["page_limit_waived"] = True
            logger.info("User would rather have two pages; rendering as-is.")
        elif answer.strip() == TRIM_CHIP:
            cap = TRIMMED_BULLETS
            answered["bullet_cap"] = cap
            logger.info("Showing only the strongest %d bullets per entry.", cap)
        elif (pending.get("meta") or {}).get("pick_section"):
            picking = pending["meta"]["pick_section"]
            if answer.strip() == ALL_CHIP:
                dropped.append(picking)
                answered["dropped_sections"] = dropped
                logger.info("Leaving all of %s off the page.", picking)
            else:
                match = next((e for e in pending["meta"].get("entries") or []
                              if e["label"].casefold() == answer.strip().casefold()), None)
                if match:
                    gone.append(match["path"])
                    answered["dropped_entries"] = gone
                    logger.info("Leaving %s (%s) off the page.", match["path"], match["label"])
                else:
                    waived = True
                    answered["page_limit_waived"] = True
        else:
            chosen = _read_drop(answer, r)
            if chosen in ENTRY_SECTIONS and len(entry_names(chosen, r, gone)) > 1:
                # More than one thing under it: ask which, rather than take them all.
                logger.info("Narrowing %r down to a single entry.", chosen)
                return {**answered, "phase": "rendering",
                        "current_question": entry_question(chosen, r, gone)}
            if chosen:
                dropped.append(chosen)
                answered["dropped_sections"] = dropped
                logger.info("Leaving %s off the page at the user's request.", chosen)
            else:
                # Names no section: two pages beats guessing what to throw away.
                waived = True
                answered["page_limit_waived"] = True
                logger.info("Couldn't place %r as a section; keeping both pages.", answer)

    try:
        from uuid import uuid4

        pdf_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static", "pdfs")
        os.makedirs(pdf_dir, exist_ok=True)

        session_id = state.get("session_id", uuid4().hex)
        filename = f"{session_id}.pdf"
        typ_path = os.path.join(pdf_dir, f"{session_id}.typ")
        pdf_fs_path = os.path.join(pdf_dir, filename)

        # The photo and the contact glyphs, if their own layout is in use and their PDF
        # had them. Written beside the .typ so Typst can read them, and removed with it
        # once the PDF exists — they are inside the document by then, and static/pdfs is
        # served publicly.
        spec = dict(state.get("style_spec") or {})
        cut_out: List[str] = []
        if spec and state.get("source_pdf"):
            source = state["source_pdf"]
            photo_path = photo_from(source, os.path.join(pdf_dir, f"{session_id}_photo"))
            if photo_path:
                cut_out.append(photo_path)
                spec["photo"] = os.path.basename(photo_path)

            icons = icons_from(source, os.path.join(pdf_dir, f"{session_id}_icon"))
            if icons:
                cut_out.extend(icons.values())
                spec["icon_images"] = {f: os.path.basename(p) for f, p in icons.items()}

        ladder = FIT_LADDER if not waived else FIT_LADDER[:1]
        pages = 0
        for step, density in enumerate(ladder):
            with open(typ_path, "w", encoding="utf-8") as f:
                f.write(build_typst(r, density, cap, dropped, spec or None, gone))

            subprocess.run(["typst", "compile", *font_args(), typ_path, pdf_fs_path],
                           check=True, capture_output=True)

            pages = page_count(pdf_fs_path)
            if pages <= PAGE_LIMIT or waived:
                if step:
                    logger.info("Fitted onto %d page(s) at density %d, bullet cap %s.",
                                pages, density, cap)
                break
            logger.info("Still %d pages at density %d, bullet cap %s — tightening.",
                        pages, density, cap)

        os.remove(typ_path)
        for cut in cut_out:
            if os.path.exists(cut):
                os.remove(cut)

        done = {
            **answered,
            "phase": "completed",
            "pdf_path": f"{settings.PUBLIC_BASE_URL}/pdfs/{filename}",
            "render_error": None,
        }

        still_offerable = droppable_now(r, dropped) or (
            cap is None and has_trimmable_bullets(r)
        )
        if pages > PAGE_LIMIT and not waived and still_offerable:
            # The PDF above is real and downloadable; this only offers to shorten it.
            logger.info("Out of lossless room at %d pages; asking what to leave off.", pages)
            return {**done, "phase": "rendering",
                    "current_question": fit_question(r, pages, dropped, trimmed=cap is not None)}

        return done
    except FileNotFoundError:

        logger.error("The `typst` binary is not on PATH — no PDF can be produced.")
        return {**answered, "phase": "completed",
                "render_error": "The PDF renderer is not available on the server."}
    except subprocess.CalledProcessError as e:

        logger.error("Typst compile failed: %s", (e.stderr or b"").decode(errors="replace"))
        return {**answered, "phase": "completed",
                "render_error": "The resume could not be compiled to PDF."}
    except Exception as e:
        logger.error(f"Failed to render resume: {e}")
        return {**answered, "phase": "completed",
                "render_error": "The resume could not be compiled to PDF."}
