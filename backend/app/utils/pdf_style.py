"""Colours read off a PDF, rather than guessed at from a picture of one.

A vision model asked "what colour are the headings?" answers with a plausible hex and
is routinely a shade or two out — it is describing an image, and #1a4f8a and #1f5090
look identical in one. The PDF already carries the answer: every text span records the
colour it was set in, so the accent can be measured exactly instead of estimated.
"""

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Above this, text is too pale to set a resume in, whatever the original did.
MAX_BODY_LUMINANCE = 140

NEAR_WHITE = 225

def as_hex(colour: int) -> str:
    return f"#{colour & 0xFFFFFF:06x}"

def luminance(colour: int) -> float:
    """Perceived brightness, 0 (black) to 255 (white)."""
    red, green, blue = (colour >> 16) & 255, (colour >> 8) & 255, colour & 255
    return 0.299 * red + 0.587 * green + 0.114 * blue

def is_grey(colour: int, tolerance: int = 18) -> bool:
    """Whether the channels are close enough that this reads as black, white or grey."""
    channels = ((colour >> 16) & 255, (colour >> 8) & 255, colour & 255)
    return max(channels) - min(channels) <= tolerance

def spans(pdf_path: str, page: int = 0, with_font: bool = False) -> List[Tuple]:
    """(colour, size, character count) per piece of text, plus the font when asked."""
    out: List[Tuple[int, float, int]] = []
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if page >= doc.page_count:
                return out
            for block in doc[page].get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue
                        row = (span.get("color", 0), span.get("size", 0), len(text))
                        out.append(row + (span.get("font", ""),) if with_font else row)
    except Exception as e:
        logger.warning("Could not read text colours from %s: %r", pdf_path, e)
    return out

def measured_colours(pdf_path: str, page: int = 0) -> Dict[str, str]:
    """The document's body colour and its accent, as hex, or {} if neither is readable.

    Body is whatever most of the page is set in — found at the commonest text size, so a
    document with more coloured headings than paragraphs still resolves the right way
    round. The accent is the heaviest colour that is not the body and not so pale it
    would vanish; a plain black resume has none, and says so by omitting the key.
    """
    found = spans(pdf_path, page)
    if not found:
        return {}

    by_size: Counter = Counter()
    by_colour: Counter = Counter()
    for colour, size, chars in found:
        by_size[round(size)] += chars
        by_colour[colour] += chars

    body_size = by_size.most_common(1)[0][0]
    at_body_size: Counter = Counter()
    for colour, size, chars in found:
        if round(size) == body_size:
            at_body_size[colour] += chars

    body = (at_body_size or by_colour).most_common(1)[0][0]

    accent = next(
        (colour for colour, _ in by_colour.most_common()
         if colour != body and luminance(colour) < NEAR_WHITE and not is_grey(colour)),
        None,
    )
    # A document whose body is itself coloured has said what its colour is; there is no
    # separate accent to look for.
    if accent is None and not is_grey(body):
        accent = body

    out: Dict[str, str] = {}
    if accent is not None:
        out["accent_color"] = as_hex(accent)
    if not is_grey(body) and luminance(body) <= MAX_BODY_LUMINANCE:
        out["text_color"] = as_hex(body)

    if out:
        logger.info("Measured colours in %s: %s", pdf_path, out)
    return out

# What a headshot looks like, as opposed to a logo, an icon or a scanned background.
MIN_PHOTO_PX = 90
PHOTO_RATIO = (0.5, 1.6)
PHOTO_PAGE_AREA = (0.005, 0.40)

def _photo_candidates(doc: Any, sheet: Any):
    """Every embedded image on the page that could plausibly be a headshot.

    What has to be got right is telling one apart from everything else embedded on the
    page — a company logo, a contact icon, a scanned background — which is what the
    three filters below are for.
    """
    area = sheet.rect.width * sheet.rect.height or 1

    for xref, *_ in sheet.get_images(full=True):
        try:
            image = doc.extract_image(xref)
        except Exception:
            continue

        width, height = image.get("width", 0), image.get("height", 0)
        if min(width, height) < MIN_PHOTO_PX or not height:
            continue
        if not PHOTO_RATIO[0] <= width / height <= PHOTO_RATIO[1]:
            continue

        placed = sheet.get_image_rects(xref)
        if not placed:
            continue
        covers = (placed[0].width * placed[0].height) / area
        if not PHOTO_PAGE_AREA[0] <= covers <= PHOTO_PAGE_AREA[1]:
            continue

        yield xref, image, placed[0]

def photo_from(pdf_path: str, out_path: str, page: int = 0) -> Optional[str]:
    """Extract the candidate's photo to `out_path`, or None if the page has none.

    Asking them to upload it again is the obvious move and the wrong one: the picture is
    already inside the PDF they gave us.
    """
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if page >= doc.page_count:
                return None
            sheet = doc[page]

            for _, image, _ in _photo_candidates(doc, sheet):
                path = f"{out_path}.{image.get('ext', 'png')}"
                with open(path, "wb") as out:
                    out.write(image["image"])
                logger.info("Extracted a %dx%d photo from %s.",
                            image.get("width", 0), image.get("height", 0), pdf_path)
                return path
    except Exception as e:
        logger.warning("Could not look for a photo in %s: %r", pdf_path, e)
    return None

# How far a shape may be off a perfect circle, or off the photo's size, and still count.
ROUND_SLACK = 0.18

# Below this the mask is cut away; above it, it is showing the picture.
CLEAR = 40
OPAQUE = 200

def _cut_round(doc: Any, image: Dict[str, Any]) -> bool:
    """Whether the picture's own transparency cuts its corners away.

    A round headshot is almost never a round image — it is a rectangle with a mask over
    it, and the mask is in the file. Reading the four corners of that mask answers
    "is this a circle?" outright, where looking at the picture only guesses.
    """
    try:
        import pymupdf

        smask = image.get("smask")
        pix = pymupdf.Pixmap(doc, smask) if smask else pymupdf.Pixmap(image["image"])
        if not smask and not pix.alpha:
            return False

        width, height = pix.width, pix.height
        if width < 8 or height < 8:
            return False

        # Inside the very edge: PDF masks are often antialiased a pixel or two in.
        inset_x, inset_y = max(1, width // 40), max(1, height // 40)
        corners = [
            pix.pixel(inset_x, inset_y), pix.pixel(width - 1 - inset_x, inset_y),
            pix.pixel(inset_x, height - 1 - inset_y),
            pix.pixel(width - 1 - inset_x, height - 1 - inset_y),
        ]
        middle = pix.pixel(width // 2, height // 2)
        return all(c[-1] < CLEAR for c in corners) and middle[-1] > OPAQUE
    except Exception:
        return False

def _round_shapes(sheet: Any):
    """Every circle on the page: drawn as one, or used to cut something into one.

    A round headshot is a rectangle with a circle cut out of it, and a PDF records that
    cut as a clipping path — four bezier curves and a scissor rectangle — rather than as
    anything visible. get_drawings() leaves those out unless asked, which is why the
    crop kept coming back square on documents that plainly had a round photo on them.
    """
    try:
        drawings = sheet.get_drawings(extended=True)
    except Exception:
        drawings = sheet.get_drawings()

    for drawing in drawings:
        if not any(item and item[0] == "c" for item in drawing.get("items") or []):
            continue
        shape = drawing.get("rect") or drawing.get("scissor")
        if shape is not None and shape.width and shape.height:
            yield shape

def _ringed(sheet: Any, rect: Any) -> bool:
    """Whether a circle is drawn over the photo, or the photo is clipped to one."""
    width, height = rect.width, rect.height
    if not width or not height:
        return False

    for shape in _round_shapes(sheet):
        if abs(shape.width - shape.height) / max(shape.width, shape.height) > ROUND_SLACK:
            continue
        if abs(shape.width - width) / max(shape.width, width) > ROUND_SLACK:
            continue
        if shape.intersects(rect):
            return True
    return False

def photo_shape(pdf_path: str, page: int = 0) -> str:
    """"circle" when their headshot is cut round, "rect" otherwise.

    Defaulting to a rectangle is deliberate: cropping a square portrait into a circle
    when it was never round takes the top of someone's head off, and there is no
    undoing that from the rendered page.
    """
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if page >= doc.page_count:
                return "rect"
            sheet = doc[page]
            for _, image, rect in _photo_candidates(doc, sheet):
                return "circle" if (_cut_round(doc, image) or _ringed(sheet, rect)) else "rect"
    except Exception as e:
        logger.warning("Could not read the photo's shape in %s: %r", pdf_path, e)
    return "rect"

# Under this a shape is see-through, and what it says about colour is not what shows.
OPAQUE_ENOUGH = 0.5

# Past this far in from the corner, a page-sized fill is a card inside a frame.
CARD_INSET = 0.005

# A sidebar is a tall band hugging one edge; a background is a fill over the whole page.
SIDEBAR_HEIGHT = 0.55
SIDEBAR_WIDTH = (0.15, 0.48)
EDGE_SLACK = 0.08
FULL_PAGE = 0.9

def _rgb(fill: Any) -> Optional[int]:
    """A pymupdf 0-1 float triple as a packed sRGB int."""
    try:
        red, green, blue = (max(0, min(1, float(c))) for c in fill[:3])
    except Exception:
        return None
    return (round(red * 255) << 16) | (round(green * 255) << 8) | round(blue * 255)

def measured_layout(pdf_path: str, page: int = 0) -> Dict[str, Any]:
    """Page size, page fill and sidebar band, as the document actually defines them.

    None of this is guessable from a picture. The page is a rectangle in points, the
    sidebar is a filled path with coordinates, and both are written in the file — a
    vision model asked "how wide is the dark strip?" is estimating something the PDF
    states outright.
    """
    out: Dict[str, Any] = {}
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if page >= doc.page_count:
                return out
            sheet = doc[page]
            width, height = sheet.rect.width, sheet.rect.height
            if not width or not height:
                return out

            out["page_width_in"] = round(width / 72, 2)
            out["page_height_in"] = round(height / 72, 2)

            best = None
            for drawing in sheet.get_drawings():
                fill, rect = drawing.get("fill"), drawing.get("rect")
                if not fill or not rect:
                    continue
                # Design tools leave fully transparent shapes behind — a black rectangle
                # over the whole page at zero opacity paints nothing, but read as an
                # instruction it says the page is black. It is not a shape at all.
                if float(drawing.get("fill_opacity", 1) or 0) < OPAQUE_ENOUGH:
                    continue
                colour = _rgb(fill)
                if colour is None:
                    continue

                wide, tall = rect.width / width, rect.height / height

                if wide >= FULL_PAGE and tall >= FULL_PAGE:
                    # A fill this size that does not start at the corner is a card
                    # sitting inside a border, not the page. The strip left showing
                    # around it is a deliberate frame and part of the design.
                    if min(rect.x0 / width, rect.y0 / height) >= CARD_INSET:
                        out["card_inset_in"] = round(rect.x0 / 72, 3)
                        out["card_color"] = as_hex(colour)
                    elif luminance(colour) < NEAR_WHITE:
                        out["background_color"] = as_hex(colour)
                    continue

                if tall < SIDEBAR_HEIGHT:
                    continue
                if wide > SIDEBAR_WIDTH[1]:
                    # The wide panel beside the sidebar: these designs set the body on
                    # its own colour rather than on the page fill.
                    out["main_color"] = as_hex(colour)
                    continue
                if wide < SIDEBAR_WIDTH[0]:
                    continue
                on_left = rect.x0 / width <= EDGE_SLACK
                on_right = rect.x1 / width >= 1 - EDGE_SLACK
                if not (on_left or on_right):
                    continue
                # Widest band wins: a panel drawn over a stripe is the real sidebar.
                if best is None or wide > best[1]:
                    gap = rect.x0 / width if on_left else 1 - rect.x1 / width
                    best = ("left" if on_left else "right", wide, colour, gap)

            if best:
                side, wide, colour, gap = best
                out["sidebar_side"] = side
                out["sidebar_width"] = round(wide, 3)
                out["sidebar_color"] = as_hex(colour)
                # How far in from the edge the band starts. Flush is the common case;
                # this design leaves a strip of the card showing beside it.
                out["sidebar_offset"] = round(max(gap, 0.0), 4)
    except Exception as e:
        logger.warning("Could not read the layout of %s: %r", pdf_path, e)

    if out:
        logger.info("Measured layout of %s: %s", pdf_path, out)
    return out

# Big enough to tell one panel from another, small enough to walk in Python. The
# question here is "what colour is this area", not "what does it say".
SAMPLE_DPI = 36

# Keep clear of the seam between two columns, and of the very edge of the page.
INSET = 0.02

def _modal_colour(pix: Any, x0: float, y0: float, x1: float, y1: float) -> Optional[str]:
    """The commonest colour inside a fraction-of-the-page rectangle.

    Text is a small minority of the pixels in a panel, so the mode is the fill behind
    it. Reading that off the rendered page rather than off the drawing instructions is
    what makes it immune to everything the file does on the way there — shapes at zero
    opacity, one fill painted over another, gradients, blend modes.
    """
    tally: Counter = Counter()
    for x in range(max(0, int(x0 * pix.width)), min(pix.width, int(x1 * pix.width)), 2):
        for y in range(max(0, int(y0 * pix.height)), min(pix.height, int(y1 * pix.height)), 2):
            tally[pix.pixel(x, y)[:3]] += 1
    if not tally:
        return None
    red, green, blue = tally.most_common(1)[0][0]
    return as_hex((red << 16) | (green << 8) | blue)

def sampled_colours(pdf_path: str, layout: Dict[str, Any], page: int = 0) -> Dict[str, str]:
    """The page's fills as they actually come out, given where `layout` says they are.

    The geometry has to come from the drawing list — a rendered image cannot tell you
    the band is 42.4% wide. The colours are the other way round.
    """
    out: Dict[str, str] = {}
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if page >= doc.page_count:
                return out
            pix = doc[page].get_pixmap(dpi=SAMPLE_DPI)

            side, width = layout.get("sidebar_side"), float(layout.get("sidebar_width") or 0)
            gap = float(layout.get("sidebar_offset") or 0)
            if side in ("left", "right") and width:
                near, far = (gap, gap + width) if side == "left" \
                    else (1 - gap - width, 1 - gap)
                band = (near + INSET, far - INSET)
                rest = (far + INSET, 1 - INSET) if side == "left" else (INSET, near - INSET)
                for key, (left, right) in (("sidebar_color", band), ("main_color", rest)):
                    found = _modal_colour(pix, left, 0.05, right, 0.95)
                    if found:
                        out[key] = found

            # The page itself, read from the strip outside whatever is drawn on it. Only
            # reported when it is dark: white paper is the default already.
            edge = _modal_colour(pix, 0.0, 0.0, 1.0, INSET)
            if edge and luminance(int(edge.lstrip("#"), 16)) < NEAR_WHITE:
                out["background_color"] = edge
    except Exception as e:
        logger.warning("Could not sample the colours of %s: %r", pdf_path, e)

    if out:
        logger.info("Sampled colours in %s: %s", pdf_path, out)
    return out

_SUBSET = re.compile(r"^[A-Z]{6}\+")
_SUFFIX = re.compile(r"(MT|PS|PSMT|Std|Pro)$")

def family_of(font: str) -> str:
    """"ABCDEE+Poppins-BoldItalic" -> "Poppins".

    PDFs name the face, not the family: a subset prefix, the family, then the weight and
    slant. Only the family is worth carrying over — Typst picks the bold and the italic
    out of whatever is installed.
    """
    name = _SUBSET.sub("", (font or "").strip())
    name = name.split(",")[0].split("-")[0]
    name = _SUFFIX.sub("", name).strip()
    return name

def measured_fonts(pdf_path: str, page: int = 0) -> Dict[str, str]:
    """The typeface the document is set in, and the one its headings use.

    This is what closes the gap between "a sans-serif resume" and their resume. The
    family is written into the file for every span; guessing it off a picture is not
    something a model can do, and matching only serif-vs-sans is what makes a copy look
    like a different document.
    """
    found = spans(pdf_path, page, with_font=True)
    if not found:
        return {}

    by_size: Counter = Counter()
    for _, size, chars, _ in found:
        by_size[round(size)] += chars
    body_size = by_size.most_common(1)[0][0]

    body: Counter = Counter()
    heading: Counter = Counter()
    for _, size, chars, font in found:
        family = family_of(font)
        if not family:
            continue
        (body if round(size) <= body_size else heading)[family] += chars

    out: Dict[str, str] = {}
    if body:
        out["body_font"] = body.most_common(1)[0][0]
    if heading:
        out["heading_font"] = heading.most_common(1)[0][0]

    if out:
        logger.info("Measured fonts in %s: %s", pdf_path, out)
    return out

# ---------------------------------------------------------------------------
# Geometry. Colour said what the page is set in; this says where things sit.
# ---------------------------------------------------------------------------

def page_facts(pdf_path: str, page: int = 0) -> Dict[str, Any]:
    """One page, opened once: its size, its text with boxes, its shapes, its pictures.

    Everything below is a pure function of this dict. Measuring six more things one
    function at a time would mean opening the document six more times and re-deriving
    the page rectangle in each of them.
    """
    facts: Dict[str, Any] = {"width": 0.0, "height": 0.0,
                             "spans": [], "shapes": [], "images": []}
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            if page >= doc.page_count:
                return facts
            sheet = doc[page]
            facts["width"], facts["height"] = sheet.rect.width, sheet.rect.height

            # rawdict rather than dict: the per-character boxes are the only way to see
            # how far apart a heading's letters are set.
            for block in sheet.get_text("rawdict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        chars = span.get("chars") or []
                        text = "".join(c.get("c", "") for c in chars)
                        if not text.strip():
                            continue
                        font = span.get("font", "")
                        facts["spans"].append({
                            "text": text,
                            "size": float(span.get("size", 0.0)),
                            "font": font,
                            # Bit 4 of the span flags, or the face name saying so.
                            "bold": bool(span.get("flags", 0) & 16)
                            or "bold" in font.casefold(),
                            "color": span.get("color", 0),
                            "bbox": tuple(span.get("bbox") or (0, 0, 0, 0)),
                            "chars": [(c.get("c", ""), tuple(c.get("bbox") or (0, 0, 0, 0)))
                                      for c in chars],
                        })

            for drawing in sheet.get_drawings():
                rect = drawing.get("rect")
                if not rect:
                    continue
                facts["shapes"].append({
                    "rect": (rect.x0, rect.y0, rect.x1, rect.y1),
                    "filled": bool(drawing.get("fill")),
                    "curved": any(item and item[0] == "c"
                                  for item in drawing.get("items") or []),
                })

            for xref, *_ in sheet.get_images(full=True):
                for placed in sheet.get_image_rects(xref):
                    facts["images"].append({"xref": xref,
                                            "rect": (placed.x0, placed.y0,
                                                     placed.x1, placed.y1)})
    except Exception as e:
        logger.warning("Could not read the geometry of %s: %r", pdf_path, e)
    return facts

# What their headings are called, and which of our sections each name means. Longest
# match wins, so "Academic Projects" is projects rather than education.
SECTION_WORDS = {
    "summary": ("summary", "profile", "objective", "about me", "overview"),
    "skills": ("skill", "expertise", "competenc", "proficienc", "technolog", "tech stack"),
    "experience": ("experience", "employment", "work history", "career history"),
    "projects": ("project", "portfolio"),
    "education": ("education", "qualification", "academic background"),
    "certifications": ("certificat", "licence", "license", "course", "training"),
}

# Longer than this is a sentence that happens to contain the word, not a heading.
TITLE_MAX = 42

def section_of(text: str) -> Optional[str]:
    """Which of our sections one of their headings is, or None if it is not one."""
    label = re.sub(r"\s+", " ", (text or "").strip().casefold())
    if not label or len(label) > TITLE_MAX:
        return None

    best: Optional[Tuple[str, int]] = None
    for key, words in SECTION_WORDS.items():
        for word in words:
            if word in label and (best is None or len(word) > best[1]):
                best = (key, len(word))
    return best[0] if best else None

def body_size(facts: Dict[str, Any]) -> float:
    """The size most of the page is set at."""
    tally: Counter = Counter()
    for span in facts.get("spans") or []:
        tally[round(span["size"])] += len(span["text"])
    return float(tally.most_common(1)[0][0]) if tally else 0.0

def headings_in(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Their section headings, in the order the page sets them out.

    A heading is a short run of text that names one of our sections and is set bigger
    than the body, or bold at the same size. Accepting body-sized text turned the skills
    bullet "Project Management (Scrum, Agile)" into a Projects section, and gave it that
    line as its heading.
    """
    floor = body_size(facts)
    found = []
    for span in facts.get("spans") or []:
        key = section_of(span["text"])
        if not key:
            continue
        size = round(span["size"])
        if size > floor or (size == floor and span.get("bold")):
            found.append({**span, "key": key})
    return found

RULE_THICKNESS = 3.5
RULE_WIDTH = 0.12

def measured_headings(facts: Dict[str, Any],
                      layout: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """How their headings are set: case, tracking, rule, and the colour in each column.

    Two columns often set their headings two different ways — the accent in the white
    panel, plain white in the coloured band. Deriving one from the other by contrast
    gets it wrong about as often as it gets it right, and both spans state their colour.
    """
    found = headings_in(facts)
    if not found:
        return {}

    out: Dict[str, Any] = {}

    band = _bands(facts, layout or {})
    main_ink: Counter = Counter()
    aside_ink: Counter = Counter()
    for heading in found:
        target = aside_ink if _in_sidebar(heading["bbox"], facts, band) else main_ink
        target[heading["color"]] += len(heading["text"])
    if main_ink:
        out["heading_color"] = as_hex(main_ink.most_common(1)[0][0])
    if aside_ink:
        out["sidebar_heading_color"] = as_hex(aside_ink.most_common(1)[0][0])

    lettered = [h for h in found if any(c.isalpha() for c in h["text"])]
    if lettered:
        upper = sum(1 for h in lettered if h["text"].isupper())
        out["heading_case"] = "upper" if upper * 2 >= len(lettered) else "title"

    # Tracking, from the gaps between one letter's box and the next. Set wide, a heading
    # reads as a different design even in the right typeface at the right size.
    gaps: List[float] = []
    for heading in found:
        chars = [(c, box) for c, box in heading["chars"] if c.strip()]
        for (_, left), (_, right) in zip(chars, chars[1:]):
            if right[0] >= left[2] and heading["size"]:
                gaps.append((right[0] - left[2]) / heading["size"])
    if gaps:
        gaps.sort()
        tracked = gaps[len(gaps) // 2]
        # Under this is kerning and rounding, not a decision anybody made.
        out["heading_tracking_em"] = round(tracked, 3) if tracked >= 0.02 else 0.0

    width = facts.get("width") or 0
    if width:
        ruled = 0
        for heading in found:
            _, _, _, bottom = heading["bbox"]
            for shape in facts.get("shapes") or []:
                x0, y0, x1, y1 = shape["rect"]
                if (y1 - y0) > RULE_THICKNESS or (x1 - x0) < RULE_WIDTH * width:
                    continue
                if bottom - 1 <= y0 <= bottom + 1.2 * heading["size"]:
                    ruled += 1
                    break
        out["heading_rule"] = ruled * 2 >= len(found)

    return out

def _bands(facts: Dict[str, Any], layout: Dict[str, Any]) -> Tuple[float, float]:
    """The x range the sidebar covers, as a fraction of the page. (0, 0) if there is none."""
    width = float(layout.get("sidebar_width") or 0)
    if not width or layout.get("sidebar_side") not in ("left", "right"):
        return (0.0, 0.0)
    return (0.0, width) if layout["sidebar_side"] == "left" else (1 - width, 1.0)

def _in_sidebar(bbox: Tuple, facts: Dict[str, Any], band: Tuple[float, float]) -> bool:
    page = facts.get("width") or 0
    if not page or band == (0.0, 0.0):
        return False
    middle = ((bbox[0] + bbox[2]) / 2) / page
    return band[0] <= middle <= band[1]

def measured_sections(facts: Dict[str, Any], layout: Dict[str, Any]) -> Dict[str, Any]:
    """The order their sections run in, and which of them sit in the coloured band.

    Which sections go in the sidebar was a rule of mine — skills, education,
    certifications — applied to every two-column resume regardless of what theirs did.
    The page says where each heading is; there is no reason to guess.
    """
    found = headings_in(facts)
    if not found:
        return {}

    band = _bands(facts, layout)

    placed = []
    for heading in found:
        aside = _in_sidebar(heading["bbox"], facts, band)
        placed.append((0 if aside else 1, heading["bbox"][1], heading["key"], aside))
    placed.sort()

    order, aside, seen = [], [], set()
    for _, _, key, in_band in placed:
        if key in seen:
            continue
        seen.add(key)
        order.append(key)
        if in_band:
            aside.append(key)

    # What they call each section. "PROFILE" is not "Profile Summary", and a copy of
    # someone's resume that renames every heading on it is not a copy of it.
    titles = {}
    for heading in found:
        titles.setdefault(heading["key"], re.sub(r"\s+", " ", heading["text"].strip()))

    out: Dict[str, Any] = {"section_order": order, "section_titles": titles}
    if band != (0.0, 0.0):
        out["sidebar_sections"] = aside
    return out

def measured_sizes(facts: Dict[str, Any]) -> Dict[str, float]:
    """How big the body and the headings are set, in points."""
    body = body_size(facts)
    out: Dict[str, float] = {}
    if body:
        out["body_size_pt"] = float(body)

    found = headings_in(facts)
    if found:
        sizes = sorted(h["size"] for h in found)
        out["heading_size_pt"] = round(sizes[len(sizes) // 2], 1)
    return out

# How far off centre a line may sit and still read as centred.
CENTRED = 0.06

def measured_name(facts: Dict[str, Any], layout: Dict[str, Any]) -> Dict[str, Any]:
    """How big their name is set, whether it is centred, and which column it is in."""
    spans_ = [s for s in facts.get("spans") or [] if any(c.isalpha() for c in s["text"])]
    width, height = facts.get("width") or 0, facts.get("height") or 0
    if not spans_ or not width or not height:
        return {}

    # The name is the biggest thing on the page and it is near the top of it. Without
    # the second half, a display-sized section heading further down wins.
    top = [s for s in spans_ if s["bbox"][1] <= 0.35 * height]
    name = max(top or spans_, key=lambda s: s["size"])

    band = _bands(facts, layout)
    aside = _in_sidebar(name["bbox"], facts, band)

    if aside:
        left, right = band[0] * width, band[1] * width
    elif band != (0.0, 0.0):
        left, right = (band[1] * width, width) if band[0] == 0 else (0.0, band[0] * width)
    else:
        left, right = 0.0, width

    column = right - left or width
    middle = (name["bbox"][0] + name["bbox"][2]) / 2
    off = abs(middle - (left + right) / 2) / column

    out: Dict[str, Any] = {
        "name_size_pt": round(name["size"], 1),
        "name_align": "center" if off <= CENTRED else "left",
        # Their name is often neither the accent nor the body ink — white on a dark
        # band, most commonly. Working it out from contrast guesses; the span says.
        "name_color": as_hex(name["color"]),
    }
    if band != (0.0, 0.0):
        out["header_side"] = "sidebar" if aside else "main"
    return out

def measured_photo(facts: Dict[str, Any], layout: Dict[str, Any]) -> Dict[str, str]:
    """Which column their photo sits in.

    Not necessarily the one their name is in: this design puts the portrait at the top
    of the coloured band and the name across the white panel beside it. Sending the
    photo wherever the header went put it in the wrong half of the page.
    """
    band = _bands(facts, layout)
    if band == (0.0, 0.0) or not facts.get("images"):
        return {}

    def area(image):
        x0, y0, x1, y1 = image["rect"]
        return (x1 - x0) * (y1 - y0)

    biggest = max(facts["images"], key=area)
    out = {"photo_side": "sidebar" if _in_sidebar(biggest["rect"], facts, band) else "main"}

    # How big they actually print it. A fixed inch and a bit is a thumbnail on a sheet
    # this size, and the page states the rectangle it was placed in.
    placed = (biggest["rect"][2] - biggest["rect"][0]) / 72
    if placed:
        out["photo_width_in"] = round(placed, 2)
    return out

# What these templates call the block of contact details, when they give it a heading.
CONTACT_WORDS = ("contact", "get in touch", "reach me", "details", "find me")

def contact_heading(facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Their "Contact" heading, if the page gives the details one of their own."""
    floor = body_size(facts)
    for span in facts.get("spans") or []:
        label = re.sub(r"\s+", " ", span["text"].strip().casefold())
        if len(label) <= TITLE_MAX and any(word in label for word in CONTACT_WORDS):
            if round(span["size"]) > floor or (round(span["size"]) == floor
                                               and span.get("bold")):
                return span
    return None

_DIGITS = re.compile(r"^[\d\s+()./-]{7,}$")

def contact_field(text: str) -> Optional[str]:
    """Which contact detail a line is — the name of the field it would be stored in.

    Which glyph goes with which detail is not written anywhere. What is written is the
    text beside each glyph, and an email address announces itself.
    """
    line = (text or "").strip()
    if not line:
        return None
    low = line.casefold()

    if "github.com" in low:
        return "github"
    if "linkedin.com" in low or "linked.in" in low:
        return "linkedin"
    if "@" in line and "." in line.split("@")[-1]:
        return "email"
    if _DIGITS.match(line) and sum(c.isdigit() for c in line) >= 7:
        return "phone"
    if low.startswith(("www.", "http://", "https://")) or (
            " " not in low and any(low.endswith(tld) or f"{tld}/" in low
                                   for tld in (".com", ".dev", ".io", ".net", ".org", ".me"))):
        return "website"
    if any(c.isalpha() for c in line):
        return "location"
    return None

def measured_contact(facts: Dict[str, Any], layout: Dict[str, Any]) -> Dict[str, str]:
    """Where their contact details live, and what they head that block with."""
    heading = contact_heading(facts)
    if not heading:
        return {}

    band = _bands(facts, layout)
    out = {"contact_title": re.sub(r"\s+", " ", heading["text"].strip())}
    if band != (0.0, 0.0):
        out["contact_side"] = "sidebar" if _in_sidebar(heading["bbox"], facts, band) else "main"
    return out

# An icon is small, and it has its label immediately to the right of it.
ICON_MIN_PT = 8

# How far from square a glyph may be: an envelope is squat, a divider rule is not a glyph.
ICON_SQUAT = 0.5
ICON_MAX_SHARE = 0.06
ICON_GAP = 3.0
ICON_PAD = 1.5
ICON_DPI = 300

def _merged(boxes: List[Tuple], pad: float) -> List[Tuple]:
    """Small shapes that touch or nearly touch, joined into one box each.

    One icon is a dozen separate paths — a ring, a handset, three highlights. Each on
    its own is too small to be anything; together they are the glyph.
    """
    out: List[Tuple] = []
    for x0, y0, x1, y1 in boxes:
        for i, (a0, b0, a1, b1) in enumerate(out):
            if x0 <= a1 + pad and a0 <= x1 + pad and y0 <= b1 + pad and b0 <= y1 + pad:
                out[i] = (min(x0, a0), min(y0, b0), max(x1, a1), max(y1, b1))
                break
        else:
            out.append((x0, y0, x1, y1))
    return out

def icons_from(pdf_path: str, out_prefix: str, page: int = 0) -> Dict[str, str]:
    """Their contact glyphs, cut out of the page as pictures.

    These icons are vector paths, not a font: there is no codepoint to look up and no
    guarantee this machine has the face they were drawn in. Rendering the patch of page
    each one occupies gives the icon itself — the same move as pulling the photo out,
    applied to something smaller. Which glyph is which comes from the text beside it.
    """
    found: Dict[str, str] = {}
    try:
        import pymupdf

        facts = page_facts(pdf_path, page)
        width = facts.get("width") or 0
        if not width:
            return found

        small = [s["rect"] for s in facts["shapes"]
                 if 0 < (s["rect"][2] - s["rect"][0]) <= ICON_MAX_SHARE * width]
        clusters = _merged(small, ICON_GAP)
        for _ in range(3):
            clusters = _merged(clusters, ICON_GAP)

        with pymupdf.open(pdf_path) as doc:
            sheet = doc[page]
            # Down the page, then across: the order they list their details in, which is
            # the order the finished block should list them in too.
            for x0, y0, x1, y1 in sorted(clusters, key=lambda box: (box[1], box[0])):
                # Sized on the longer side, not both. An envelope is half again as wide
                # as it is tall, and a square minimum threw it away while keeping the
                # phone and the pin beside it — one icon missing from a row of five.
                long_side, short_side = max(x1 - x0, y1 - y0), min(x1 - x0, y1 - y0)
                if long_side < ICON_MIN_PT or short_side < long_side * ICON_SQUAT:
                    continue

                # The nearest text starting to the right of it, on the same line.
                label = None
                for span in facts["spans"]:
                    sx0, sy0, _, sy1 = span["bbox"]
                    if sx0 < x1 or sx0 > x1 + (x1 - x0) * 3:
                        continue
                    if sy1 < y0 or sy0 > y1:
                        continue
                    if label is None or sx0 < label["bbox"][0]:
                        label = span
                if not label:
                    continue

                field = contact_field(label["text"])
                if not field or field in found:
                    continue

                clip = pymupdf.Rect(x0 - ICON_PAD, y0 - ICON_PAD, x1 + ICON_PAD, y1 + ICON_PAD)
                path = f"{out_prefix}_{field}.png"
                sheet.get_pixmap(clip=clip, dpi=ICON_DPI).save(path)
                found[field] = path

        if found:
            logger.info("Cut %d contact icons out of %s: %s",
                        len(found), pdf_path, ", ".join(sorted(found)))
    except Exception as e:
        logger.warning("Could not cut the icons out of %s: %r", pdf_path, e)
    return found

def measured_margins(facts: Dict[str, Any],
                     layout: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """How much paper their page keeps clear around the content.

    Only for a single column. A two-column page has no margin of its own — the bands run
    to the edge of the paper and each column carries its own inset.
    """
    if (layout or {}).get("sidebar_color"):
        return {}

    width, height = facts.get("width") or 0, facts.get("height") or 0
    boxes = [span["bbox"] for span in facts.get("spans") or []]
    boxes += [shape["rect"] for shape in facts.get("shapes") or []]
    boxes += [image["rect"] for image in facts.get("images") or []]
    if not boxes or not width or not height:
        return {}

    side = min(min(b[0] for b in boxes), width - max(b[2] for b in boxes))
    # The top only. Content often stops short of the bottom margin, and on the last page
    # of a two-page resume it stops well short — that is where it ran out, not a margin.
    top = min(b[1] for b in boxes)

    out = {}
    for key, value in (("margin_x_in", side / 72), ("margin_y_in", top / 72)):
        if MARGIN_RANGE[0] <= value <= MARGIN_RANGE[1]:
            out[key] = round(value, 3)
    return out

MARGIN_RANGE = (0.15, 1.5)

def measured_skills(facts: Dict[str, Any]) -> Dict[str, str]:
    """Whether their skills run as one list or are broken into labelled groups.

    Ours are stored in categories because that is how they were collected, and printing
    the categories on a resume that never had them turns one line of skills into seven
    labelled rows. The page says which it is: a grouped list sets its labels in bold.
    """
    found = headings_in(facts)
    start = next((h["bbox"][1] for h in found if h["key"] == "skills"), None)
    if start is None:
        return {}

    after = [h["bbox"][1] for h in found if h["bbox"][1] > start]
    end = min(after) if after else float("inf")

    inside = [s for s in facts.get("spans") or [] if start < s["bbox"][1] < end]
    if not inside:
        return {}
    return {"skills_layout": "grouped" if any(s.get("bold") for s in inside) else "flat"}

MARKER_CHARS = ("•", "‣", "▪", "◦", "–", "-")

def measured_marker(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The character their bullets are drawn with, if the page uses one consistently."""
    tally: Counter = Counter()
    for span in facts.get("spans") or []:
        text = span["text"].strip()
        if text and text[0] in MARKER_CHARS:
            tally[text[0]] += 1

    if not tally:
        return {}
    marker, count = tally.most_common(1)[0]
    # One is a stray dash in a date range, not a bullet style.
    return {"bullet_marker": marker} if count >= 2 else {}

# Private-use codepoints: where every icon font keeps its glyphs.
PUA = (0xE000, 0xF8FF)

ICON_FONTS = ("awesome", "icomoon", "glyphicon", "material icons", "iconfont", "entypo")

def measured_icons(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Whether their contact line is drawn with glyphs rather than separators."""
    for span in facts.get("spans") or []:
        family = family_of(span["font"]).casefold()
        if any(name in family or name in (span["font"] or "").casefold()
               for name in ICON_FONTS):
            return {"contact_icons": True}
        if any(PUA[0] <= ord(c) <= PUA[1] for c in span["text"]):
            return {"contact_icons": True}
    return {"contact_icons": False}

def measured_style(pdf_path: str, page: int = 0) -> Dict[str, Any]:
    """Everything about their layout that the file states rather than implies.

    One place for the whole measurement, because the caller should not have to know
    which of these needs the page rectangle and which needs the sidebar band.
    """
    layout = measured_layout(pdf_path, page)
    facts = page_facts(pdf_path, page)

    out: Dict[str, Any] = {
        **measured_colours(pdf_path, page),
        **layout,
        **measured_fonts(pdf_path, page),
        **measured_headings(facts, layout),
        **measured_sizes(facts),
        **measured_sections(facts, layout),
        **measured_name(facts, layout),
        **measured_photo(facts, layout),
        **measured_contact(facts, layout),
        **measured_margins(facts, layout),
        **measured_skills(facts),
        **measured_marker(facts),
        **measured_icons(facts),
        # Last, so the composited page overrules what the drawing list claimed.
        **sampled_colours(pdf_path, layout, page),
        "photo_shape": photo_shape(pdf_path, page),
    }
    logger.info("Measured %s: %s", pdf_path, out)
    return out
