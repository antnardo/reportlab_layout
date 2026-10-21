"""What a page of PDF draws, element by element -- and the same page with elements taken out.

A page's content stream is a program: it sets a font, moves a text matrix, shows
strings, builds and paints paths, draws images and forms. To know what the page
shows, and where, this module runs that program without painting anything,
following the graphics state (the CTM, the clipping box, the line width) and the
text state (font, size, spacings, scaling, rise, the text matrix) as a viewer
does. Each glyph, image, painted path and shading it meets becomes a
:class:`PdfElement` with its box on the page.

**Taking elements out** is the same walk, writing the program again as it goes:
an element a predicate refuses is left out, and nothing else changes. A glyph
goes alone -- the glyphs after it in the same string keep their place, the gap
written as a ``TJ`` displacement -- so a word can lose its middle; a path goes
with its construction, an image with its ``Do``. The order of painting is the
original's, the fonts and images are the original's. The alternative, rebuilding
the page from what a text extractor reports, loses that order (a text hidden
under a white box comes back), the images, and every font that is not one of the
fourteen standard ones.

That is what a redaction needs, and it needs more: whatever is not drawn but
still in the file. So, when elements are taken out, the marked-content property
lists lose their ``ActualText``, ``Alt`` and ``E``, which repeat the text in
clear; and only the resources the remaining program uses are copied -- an image
taken out of the content would otherwise ride along in the resources. The
document around the page -- its XMP metadata, structure tree, information
dictionary, annotations, form fields, attachments -- is never copied in the first
place (see :mod:`reportlab_layout.pdfpages`). What stays is the font programs
themselves: a subset embedded for the page keeps the glyphs it was made with,
and its ``ToUnicode`` map lists their characters -- which characters, not where
nor in what order.

**A glyph's box** runs, along the baseline, from its origin to its advance, and
across it from the font's descent to its ascent -- the ``FontDescriptor``'s, else
the ``FontBBox``, else the AFM metrics of the fourteen standard fonts -- raised by
the text rise, then mapped by the text matrix and the CTM onto the page, as an
upright rectangle. A font that cannot be measured is refused rather than
guessed: a wrong width would shift every glyph after it, and a redaction would
then miss what it aims at. Refused are vertical writing, a composite font whose
CMap is not ``Identity-H``, and a simple font without ``/Widths`` that is not one
of the fourteen.
"""

import math
import re
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, TypeAlias

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase._glyphlist import _glyphname2unicode

__all__ = ["Keep", "PdfElement", "page_program", "walk_page"]

Matrix: TypeAlias = tuple[float, float, float, float, float, float]
Rect: TypeAlias = tuple[float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class PdfElement:
    """One thing a page draws: a glyph, an image, a painted path or a shading.

    ``box`` is ``(x1, y1, x2, y2)`` in the source page's own coordinates, in
    points, ``y`` upwards. For a glyph, ``origin`` is its point on the baseline,
    ``text`` its Unicode text as far as the font tells (``""`` when it does not),
    ``font`` the ``/BaseFont`` as written, subset prefix included, and ``size``
    its size on the page in points.
    """

    kind: str
    box: Rect
    page: int
    origin: tuple[float, float] | None = None
    text: str = ""
    font: str = ""
    size: float = 0.0


Keep: TypeAlias = Callable[[PdfElement], bool]
"""Decides whether an element stays: ``False`` takes it out."""


def _multiply(m: Matrix, n: Matrix) -> Matrix:
    """``m`` then ``n``: the matrix product ``m × n`` of PDF's row-vector convention."""
    a, b, c, d, e, f = m
    p, q, r, s, t, u = n
    return (a * p + b * r, a * q + b * s, c * p + d * r, c * q + d * s, e * p + f * r + t, e * q + f * s + u)


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _bounds(points: Iterable[tuple[float, float]]) -> Rect:
    xs, ys = zip(*points, strict=True)
    return (min(xs), min(ys), max(xs), max(ys))


def _mapped(m: Matrix, x1: float, y1: float, x2: float, y2: float) -> Rect:
    """The upright box of a rectangle mapped by ``m``."""
    return _bounds(_apply(m, x, y) for x in (x1, x2) for y in (y1, y2))


def _meet(a: Rect, b: Rect) -> Rect:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    return (x1, y1, max(x1, min(a[2], b[2])), max(y1, min(a[3], b[3])))


# ----------------------------------------------------------------------
# Fonts
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Font:
    """What it takes to measure a font's glyphs and name their characters.

    Widths, ascent and descent are in text space per unit of font size: glyph
    units over 1000, or through the ``FontMatrix`` of a Type 3 font.
    """

    name: str
    code_length: int
    widths: dict[int, float]
    default_width: float
    ascent: float
    descent: float
    unicode: dict[int, str] = field(default_factory=dict)
    names: tuple[str | None, ...] = ()  # glyph name by code, for a simple font without ToUnicode

    def codes(self, data: bytes) -> list[tuple[bytes, int]]:
        n = self.code_length
        return [
            (data[i : i + n], int.from_bytes(data[i : i + n], "big")) for i in range(0, len(data) - n + 1, n)
        ]

    def width(self, code: int) -> float:
        return self.widths.get(code, self.default_width)

    def text(self, code: int) -> str:
        if code in self.unicode:
            return self.unicode[code]
        if code < len(self.names) and (name := self.names[code]):
            return _glyph_text(name)
        return ""


def _glyph_text(name: str) -> str:
    found = _glyphname2unicode.get(name)
    if found is not None:
        return chr(found)
    base = name.split(".")[0]
    for prefix, size in (("uni", 4), ("u", 4)):
        digits = base[len(prefix) :]
        if base.startswith(prefix) and len(digits) >= size and re.fullmatch(r"[0-9A-Fa-f]+", digits):
            return "".join(chr(int(digits[i : i + 4], 16)) for i in range(0, len(digits) - 3, 4))
    return base if len(base) == 1 else ""


def _number(obj: Any, default: float = 0.0) -> float:
    try:
        return float(obj)
    except (TypeError, ValueError):
        return default


def _font(font: Any) -> _Font:
    """Read a font dictionary, or refuse it with ``ValueError``."""
    subtype = font.get("/Subtype")
    name = str(font.get("/BaseFont", font.get("/Name", "")))[1:] or "(unnamed)"
    if subtype == "/Type0":
        return _composite(font, name)
    if subtype == "/Type3":
        return _type3(font, name)
    return _simple(font, name)


def _vertical(descriptor: Any, bbox: Any, scale: float) -> tuple[float, float]:
    """Ascent and descent: the descriptor's when it gives them, else the font box's."""
    ascent = _number(descriptor.get("/Ascent")) if descriptor is not None else 0.0
    descent = _number(descriptor.get("/Descent")) if descriptor is not None else 0.0
    if (ascent == 0 or descent == 0) and bbox is not None and len(bbox) == 4:
        ascent = ascent or _number(bbox[3])
        descent = descent or _number(bbox[1])
    if ascent <= descent:
        raise ValueError("no ascent or descent to measure")
    return ascent * scale, descent * scale


def _composite(font: Any, name: str) -> _Font:
    encoding = font.get("/Encoding")
    if str(encoding) != "/Identity-H":
        raise ValueError(
            f"font {name}: only the Identity-H encoding of composite fonts is supported, not {encoding}"
        )
    descendant = font["/DescendantFonts"][0].get_object()
    descriptor = descendant.get("/FontDescriptor")
    descriptor = descriptor.get_object() if descriptor is not None else None
    bbox = descriptor.get("/FontBBox") if descriptor is not None else None
    ascent, descent = _vertical(descriptor, bbox, 0.001)
    widths: dict[int, float] = {}
    spec = list(descendant.get("/W", []))
    i = 0
    while i < len(spec):
        first = int(spec[i])
        following = spec[i + 1].get_object() if hasattr(spec[i + 1], "get_object") else spec[i + 1]
        if isinstance(following, list):
            for offset, width in enumerate(following):
                widths[first + offset] = _number(width) / 1000
            i += 2
        else:
            for code in range(first, int(following) + 1):
                widths[code] = _number(spec[i + 2]) / 1000
            i += 3
    default = _number(descendant.get("/DW"), 1000) / 1000
    return _Font(name, 2, widths, default, ascent, descent, _to_unicode(font))


def _type3(font: Any, name: str) -> _Font:
    matrix = [_number(v) for v in font.get("/FontMatrix", [0.001, 0, 0, 0.001, 0, 0])]
    if matrix[1] or matrix[2]:
        raise ValueError(f"font {name}: a Type 3 font matrix that skews or rotates is not supported")
    first = int(font.get("/FirstChar", 0))
    widths = {first + i: _number(w) * matrix[0] for i, w in enumerate(font.get("/Widths", []))}
    ascent, descent = _vertical(None, font.get("/FontBBox"), matrix[3])
    return _Font(name, 1, widths, 0.0, ascent, descent, _to_unicode(font), _glyph_names(font, None))


def _simple(font: Any, name: str) -> _Font:
    descriptor = font.get("/FontDescriptor")
    descriptor = descriptor.get_object() if descriptor is not None else None
    standard = name.split("+")[-1]
    face = pdfmetrics.getTypeFace(standard) if standard in pdfmetrics.standardFonts else None
    names = _glyph_names(font, face)
    if "/Widths" in font:
        first = int(font.get("/FirstChar", 0))
        widths = {first + i: _number(w) / 1000 for i, w in enumerate(font["/Widths"])}
        missing = _number(descriptor.get("/MissingWidth")) / 1000 if descriptor is not None else 0.0
    elif face is not None:
        widths = {code: face.glyphWidths.get(glyph, 0) / 1000 for code, glyph in enumerate(names) if glyph}
        missing = 0.0
    else:
        raise ValueError(f"font {name}: no /Widths, and not one of the fourteen standard fonts")
    if descriptor is not None:
        ascent, descent = _vertical(descriptor, descriptor.get("/FontBBox"), 0.001)
    elif face is not None:
        ascent, descent = face.ascent / 1000, face.descent / 1000
    else:
        raise ValueError(f"font {name}: no font descriptor to measure it")
    return _Font(name, 1, widths, missing, ascent, descent, _to_unicode(font), names)


_BUILT_IN = {"Symbol": "SymbolEncoding", "ZapfDingbats": "ZapfDingbatsEncoding"}


def _glyph_names(font: Any, face: Any) -> tuple[str | None, ...]:
    """The glyph name of each code: the base encoding, then the differences."""
    encoding = font.get("/Encoding")
    encoding = encoding.get_object() if hasattr(encoding, "get_object") else encoding
    base_name = "StandardEncoding"
    if face is not None and face.name in _BUILT_IN:
        base_name = _BUILT_IN[face.name]
    differences: list[Any] = []
    if encoding is None and (built_in := _built_in_encoding(font)):
        return built_in
    if hasattr(encoding, "get"):
        base_name = str(encoding.get("/BaseEncoding", "/" + base_name))[1:]
        differences = list(encoding.get("/Differences", []))
    elif encoding is not None:
        base_name = str(encoding)[1:]
    try:
        names: list[str | None] = list(pdfmetrics.getEncoding(base_name).vector)
    except KeyError:
        names = list(pdfmetrics.getEncoding("StandardEncoding").vector)
    code = 0
    for item in differences:
        if isinstance(item, int | float) or str(item).lstrip("-").isdigit():
            code = int(item)
        else:
            if 0 <= code < 256:
                names[code] = str(item)[1:]
            code += 1
    return tuple(names)


def _built_in_encoding(font: Any) -> tuple[str | None, ...]:
    """The encoding an embedded Type 1 program carries, read from its clear-text part.

    A font with no ``/Encoding`` uses its own: TeX's symbol fonts do. It only
    names the glyphs -- their widths come from ``/Widths`` -- so a font program
    that cannot be read costs the text, not the geometry.
    """
    descriptor = font.get("/FontDescriptor")
    program = descriptor.get_object().get("/FontFile") if descriptor is not None else None
    if program is None:
        return ()
    program = program.get_object()
    try:
        clear = program.get_data()[: int(program.get("/Length1", 0)) or None].decode("latin-1")
    except Exception:
        return ()
    if "StandardEncoding def" in clear:
        return ()
    names: list[str | None] = [None] * 256
    for code, name in re.findall(r"dup\s+(\d+)\s*/(\S+)\s+put", clear):
        if int(code) < 256:
            names[int(code)] = name
    return tuple(names) if any(names) else ()


def _to_unicode(font: Any) -> dict[int, str]:
    stream = font.get("/ToUnicode")
    if stream is None:
        return {}
    try:
        data = stream.get_object().get_data().decode("latin-1")
    except Exception:  # an unreadable map only costs the text, never the geometry
        return {}
    mapping: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", data, re.S):
        for source, target in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            mapping[int(source, 16)] = _utf16(bytes.fromhex(target))
    for block in re.findall(r"beginbfrange(.*?)endbfrange", data, re.S):
        pattern = r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])"
        for low, high, target in re.findall(pattern, block):
            first, last = int(low, 16), min(int(high, 16), int(low, 16) + 0xFFFF)
            if target.startswith("["):
                for offset, each in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", target)):
                    mapping[first + offset] = _utf16(bytes.fromhex(each))
            else:
                start = bytes.fromhex(target[1:-1])
                for offset in range(last - first + 1):
                    value = int.from_bytes(start, "big") + offset
                    mapping[first + offset] = _utf16(value.to_bytes(max(len(start), 2), "big"))
    return mapping


def _utf16(data: bytes) -> str:
    return data.decode("utf-16-be", errors="replace")


# ----------------------------------------------------------------------
# The walk
# ----------------------------------------------------------------------


@dataclass(slots=True)
class _State:
    ctm: Matrix = IDENTITY
    clip: Rect = (0.0, 0.0, 0.0, 0.0)
    line_width: float = 1.0
    font: _Font | None = None
    size: float = 0.0
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    scale: float = 1.0
    leading: float = 0.0
    rise: float = 0.0


_PAINTS = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"}
_STROKES = {b"S", b"s", b"B", b"B*", b"b", b"b*"}
_DEVICE_SPACES = {"/DeviceGray", "/DeviceRGB", "/DeviceCMYK", "/Pattern", "/G", "/RGB", "/CMYK"}
_CLEAR_KEYS = ("/ActualText", "/Alt", "/E")
_CATEGORIES = ("/Font", "/XObject", "/ExtGState", "/ColorSpace", "/Pattern", "/Shading", "/Properties")


class _Walk:
    """Runs one content program, collecting its elements and, given ``keep``, rewriting it."""

    def __init__(self, page: int, keep: Keep | None, reader: Any) -> None:
        import pypdf  # optional: pdfpages has already said how to install it

        self.page = page
        self.keep = keep
        self.reader = reader
        self.generic = pypdf.generic
        self.elements: list[PdfElement] = []
        self.removed: list[PdfElement] = []
        self.fonts: dict[Any, _Font] = {}
        self.copies = 0

    def _decide(self, element: PdfElement) -> bool:
        self.elements.append(element)
        if self.keep is None or self.keep(element):
            return True
        self.removed.append(element)
        return False

    def run(
        self, operations: list[tuple[Any, bytes]], resources: Any, state: _State
    ) -> tuple[list[Any], Any]:
        """Walk ``operations``; give back the program to write and the resources it uses.

        A resource counts as used only when an operator that names it is written.
        """
        g = self.generic
        used: dict[str, dict[str, Any]] = {category: {} for category in _CATEGORIES}
        out: list[tuple[Any, bytes]] = []
        stack: list[_State] = []
        state = replace(state)
        text_matrix = line_matrix = IDENTITY
        path: list[tuple[Any, bytes]] = []
        points: list[tuple[float, float]] = []
        clipping = False

        def lookup(category: str, name: Any) -> tuple[Any, Any]:
            entries = resources.get(category) if resources is not None else None
            entries = entries.get_object() if entries is not None else None
            if entries is None or name not in entries:
                raise ValueError(f"the page names {category[1:]} {name}, which its resources lack")
            return entries[name], entries.raw_get(name)

        def use(category: str, name: Any) -> Any:
            resolved, raw = lookup(category, name)
            used[category][str(name)] = raw
            return resolved

        for operands, operator in operations:
            if operator in (b"m", b"l", b"c", b"v", b"y", b"re", b"h"):
                path.append((operands, operator))
                if operator == b"re":
                    x, y, w, h = (_number(v) for v in operands)
                    points += [_apply(state.ctm, px, py) for px in (x, x + w) for py in (y, y + h)]
                elif operator != b"h":
                    numbers = [_number(v) for v in operands]
                    points += [
                        _apply(state.ctm, numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)
                    ]
                continue
            if operator in (b"W", b"W*"):
                path.append((operands, operator))
                clipping = True
                continue
            if operator in _PAINTS:
                keep = True
                if operator != b"n" and points:
                    box = _bounds(points)
                    if operator in _STROKES:
                        ctm = state.ctm
                        stretch = max(math.hypot(ctm[0], ctm[1]), math.hypot(ctm[2], ctm[3]))
                        widen = state.line_width * stretch / 2
                        box = (box[0] - widen, box[1] - widen, box[2] + widen, box[3] + widen)
                    keep = self._decide(PdfElement("path", box, self.page))
                if keep:
                    out += [*path, (operands, operator)]
                elif clipping:
                    out += [*path, ([], b"n")]  # the clip stays, the paint goes
                if clipping and points:
                    state.clip = _meet(state.clip, _bounds(points))
                path, points, clipping = [], [], False
                continue

            if operator == b"q":
                stack.append(replace(state))
            elif operator == b"Q":
                if stack:
                    state = stack.pop()
            elif operator == b"cm":
                state.ctm = _multiply(_matrix(operands), state.ctm)
            elif operator == b"w":
                state.line_width = _number(operands[0])
            elif operator == b"gs":
                extgstate = use("/ExtGState", operands[0])
                if "/LW" in extgstate:
                    state.line_width = _number(extgstate["/LW"])
                if "/Font" in extgstate:
                    reference, size = extgstate.raw_get("/Font")
                    state.font, state.size = self._font_of(reference), _number(size)
            elif operator == b"BT":
                text_matrix = line_matrix = IDENTITY
            elif operator == b"Tf":
                use("/Font", operands[0])
                state.font = self._font_of(used["/Font"][str(operands[0])])
                state.size = _number(operands[1])
            elif operator == b"Tc":
                state.char_spacing = _number(operands[0])
            elif operator == b"Tw":
                state.word_spacing = _number(operands[0])
            elif operator == b"Tz":
                state.scale = _number(operands[0]) / 100
            elif operator == b"TL":
                state.leading = _number(operands[0])
            elif operator == b"Ts":
                state.rise = _number(operands[0])
            elif operator in (b"Td", b"TD"):
                tx, ty = _number(operands[0]), _number(operands[1])
                if operator == b"TD":
                    state.leading = -ty
                text_matrix = line_matrix = _multiply((1, 0, 0, 1, tx, ty), line_matrix)
            elif operator == b"Tm":
                text_matrix = line_matrix = _matrix(operands)
            elif operator == b"T*":
                text_matrix = line_matrix = _multiply((1, 0, 0, 1, 0, -state.leading), line_matrix)
            elif operator in (b"Tj", b"'", b'"', b"TJ"):
                prefix: list[tuple[Any, bytes]] = []
                if operator == b'"':
                    state.word_spacing, state.char_spacing = _number(operands[0]), _number(operands[1])
                    prefix = [([operands[0]], b"Tw"), ([operands[1]], b"Tc"), ([], b"T*")]
                if operator in (b"'", b'"'):
                    text_matrix = line_matrix = _multiply((1, 0, 0, 1, 0, -state.leading), line_matrix)
                    prefix = prefix or [([], b"T*")]
                items = list(operands[0]) if operator == b"TJ" else [operands[-1]]
                pieces, text_matrix, changed = self._show(items, state, text_matrix)
                out += [*prefix, ([g.ArrayObject(pieces)], b"TJ")] if changed else [(operands, operator)]
                continue
            elif operator == b"Do":
                xobject, _ = lookup("/XObject", operands[0])
                drawn = self._do(operands[0], xobject, state, resources)
                if drawn is None:
                    continue
                name, copy = drawn
                used["/XObject"][str(name)] = copy if copy is not None else lookup("/XObject", name)[1]
                operands = [name]
            elif operator == b"INLINE IMAGE":
                if not self._decide(PdfElement("image", _mapped(state.ctm, 0, 0, 1, 1), self.page)):
                    continue
                settings = operands["settings"]
                space = settings.get("/CS", settings.get("/ColorSpace"))
                if isinstance(space, g.NameObject) and space not in _DEVICE_SPACES:
                    use("/ColorSpace", space)
            elif operator == b"sh":
                lookup("/Shading", operands[0])
                if not self._decide(PdfElement("shading", state.clip, self.page)):
                    continue
                use("/Shading", operands[0])
            elif operator in (b"cs", b"CS"):
                if operands[0] not in _DEVICE_SPACES:
                    use("/ColorSpace", operands[0])
            elif operator in (b"scn", b"SCN"):
                if operands and isinstance(operands[-1], g.NameObject):
                    use("/Pattern", operands[-1])
            elif operator in (b"BDC", b"DP"):
                properties = operands[1]
                if isinstance(properties, g.NameObject):
                    use("/Properties", properties)
                elif self.keep is not None and hasattr(properties, "items"):
                    operands = [operands[0], _cleared(properties, g)]
            out.append((operands, operator))
        return out, used

    def _font_of(self, reference: Any) -> _Font:
        key = (reference.idnum, reference.generation) if hasattr(reference, "idnum") else id(reference)
        if key not in self.fonts:
            self.fonts[key] = _font(reference.get_object())
        return self.fonts[key]

    def _show(self, items: list[Any], state: _State, tm: Matrix) -> tuple[list[Any], Matrix, bool]:
        """Show a TJ array's strings and moves; give back the array to write in its place."""
        g = self.generic
        font = state.font
        if font is None:
            raise ValueError("the page shows text before choosing a font")
        horizontal = state.size * state.scale
        pieces: list[Any] = []
        changed = False
        gap = 0.0  # TJ units still to write before the next run of kept glyphs

        for item in items:
            if not isinstance(item, str | bytes):
                move = _number(item)
                tm = _multiply((1, 0, 0, 1, -move / 1000 * horizontal, 0), tm)
                gap += move
                continue
            if hasattr(item, "get_original_bytes"):
                data = item.get_original_bytes()  # a pypdf text string: its bytes as written
            else:
                data = item if isinstance(item, bytes) else item.encode("latin-1")
            run = bytearray()
            for raw, code in font.codes(data):
                width = font.width(code)
                placed = _multiply(tm, state.ctm)
                rendering = _multiply((horizontal, 0, 0, state.size, 0, state.rise), placed)
                element = PdfElement(
                    "text",
                    _mapped(rendering, 0, font.descent, width, font.ascent),
                    self.page,
                    _apply(rendering, 0, 0),
                    font.text(code),
                    font.name,
                    abs(state.size) * math.hypot(placed[2], placed[3]),
                )
                spacing = state.char_spacing + (
                    state.word_spacing if font.code_length == 1 and code == 32 else 0.0
                )
                advance = (width * state.size + spacing) * state.scale
                if self._decide(element):
                    if gap and not run:
                        pieces.append(g.FloatObject(round(gap, 4)))
                        gap = 0.0
                    run += raw
                else:
                    changed = True
                    if run:
                        pieces.append(g.ByteStringObject(bytes(run)))
                        run = bytearray()
                    if advance:
                        if not horizontal:
                            raise ValueError("cannot take a glyph out of text set at size 0")
                        gap -= advance / horizontal * 1000
                tm = _multiply((1, 0, 0, 1, advance, 0), tm)
            if run:
                pieces.append(g.ByteStringObject(bytes(run)))
        if gap:
            pieces.append(g.FloatObject(round(gap, 4)))
        return pieces, tm, changed

    def _do(self, name: Any, xobject: Any, state: _State, resources: Any) -> tuple[Any, Any] | None:
        """Draw an XObject: ``None`` drops the call, else the name to call and a new object, if any."""
        subtype = xobject.get("/Subtype")
        if subtype == "/Image":
            if self._decide(PdfElement("image", _mapped(state.ctm, 0, 0, 1, 1), self.page)):
                return name, None
            return None
        if subtype != "/Form":
            return (name, None) if self.keep is None else None  # PostScript: dropped when filtering
        inner = replace(state, ctm=_multiply(_matrix(xobject.get("/Matrix", IDENTITY)), state.ctm))
        bbox = [_number(v) for v in xobject.get("/BBox", [0, 0, 0, 0])]
        inner.clip = _meet(state.clip, _mapped(inner.ctm, *bbox))
        own = xobject.get("/Resources")
        form_resources = own.get_object() if own is not None else resources  # a form may inherit them
        operations = self.generic.ContentStream(xobject, self.reader).operations
        program, form_used = self.run(operations, form_resources, inner)
        if self.keep is None:
            return name, None
        g = self.generic
        copy = g.DecodedStreamObject()
        for key, value in xobject.items():
            if key not in ("/Length", "/Filter", "/DecodeParms", "/Resources"):
                copy[g.NameObject(key)] = value
        copy[g.NameObject("/Resources")] = pruned(form_resources, form_used, g)
        copy[g.NameObject("/Filter")] = g.NameObject("/FlateDecode")
        copy.set_data(zlib.compress(_written(program, self.reader, g)))
        self.copies += 1
        return g.NameObject(f"/RLK{self.copies}"), copy


def _matrix(values: Any) -> Matrix:
    a, b, c, d, e, f = (_number(v) for v in values)
    return (a, b, c, d, e, f)


def _cleared(properties: Any, g: Any) -> Any:
    """A property list without the texts it repeats in clear."""
    clean = g.DictionaryObject()
    for key, value in properties.items():
        if key not in _CLEAR_KEYS:
            clean[g.NameObject(key)] = value
    return clean


def pruned(resources: Any, used: dict[str, dict[str, Any]], g: Any) -> Any:
    """Only the resources a rewritten program uses; property lists cleared."""
    out = g.DictionaryObject()
    for category, entries in used.items():
        if not entries:
            continue
        kept = g.DictionaryObject()
        for name, value in entries.items():
            if category == "/Properties":
                resolved = value.get_object() if hasattr(value, "get_object") else value
                value = _cleared(resolved, g) if hasattr(resolved, "items") else value
            kept[g.NameObject(name)] = value
        out[g.NameObject(category)] = kept
    return out


def _written(program: list[tuple[Any, bytes]], reader: Any, g: Any) -> bytes:
    stream = g.ContentStream(g.DecodedStreamObject(), reader)
    stream.operations = program
    data: bytes = stream.get_data()
    return data


def page_program(reader: Any, index: int) -> tuple[list[tuple[Any, bytes]], Any, Rect]:
    """A page's operations, its resources, and its crop box."""
    g = __import__("pypdf").generic
    page = reader.pages[index]
    contents = page.get_contents()
    operations = g.ContentStream(contents, reader).operations if contents is not None else []
    resources = page.get("/Resources")
    resources = resources.get_object() if resources is not None else g.DictionaryObject()
    crop = page.cropbox
    return operations, resources, (float(crop.left), float(crop.bottom), float(crop.right), float(crop.top))


def walk_page(reader: Any, index: int, keep: Keep | None) -> tuple[_Walk, bytes, Any]:
    """Walk page ``index``; with ``keep``, also give back its rewritten content and resources."""
    operations, resources, box = page_program(reader, index)
    walk = _Walk(index, keep, reader)
    program, used = walk.run(operations, resources, _State(clip=box))
    if keep is None:
        return walk, b"", resources
    g = walk.generic
    return walk, _written(program, reader, g), pruned(resources, used, g)
