"""Pages of other PDFs, laid down as vector drawing: at a point, or inside a line of text.

A formula typeset by LaTeX, or a pictogram from one of its fonts, comes out as a page
of PDF. Rasterised, it stays a grid of pixels that a printer resamples and a zoom
shows; laid down as it is, it stays vector -- sharp at any resolution, its text still
text. reportlab cannot read a PDF, so the page is read by pypdf (BSD, pure Python, an
optional dependency: ``reportlab_layout[pdf]``) and written again as reportlab objects:
its content becomes a *form XObject*, its resources -- fonts, images, graphics states
-- are copied object by object, their streams byte for byte, never decoded.

**Each object is written once per document.** Copied naively, a page brings every
font it uses, and a page cut out of a larger PDF often brings every font of that PDF,
subset for all of its pages: a formula of a few glyphs weighs ten to fifty kilobytes,
nearly all of it fonts. But the formulas typeset together share the very same font
streams, byte for byte. So every object copied is known by a digest of its content --
the digests of the objects it refers to included, so that a font descriptor pointing
to an identical font file is identical too -- and an object whose digest the document
already holds is not written again, whichever file it came from. A hundred formulas
measured this way need their six distinct font streams once, 45 kB in all, instead of
the 1.3 MB of fonts their hundred files carry; and a page drawn twice is one form
XObject, drawn twice.

The page's box is its crop box, the media box by default. The form's bounding box is
that box, so what lies outside it is clipped, as a viewer would; placing it is a matter
of scaling that box onto the rectangle asked for.

**Inside a line**, :func:`inline_pdf` gives the ``<img/>`` tag a paragraph already
knows: reportlab reserves the box, breaks the line and sets the baseline exactly as for
an image -- nothing of its line-breaking is redone here. The image itself is a
one-pixel stand-in, a file named after the page in a temporary folder of the process,
removed when it ends. :class:`~reportlab_layout.InlineParagraph` then catches the call
that would draw that pixel and draws the page in its place, at the position reportlab
computed for it, justified lines included. A plain ``Paragraph`` knows nothing of this
and paints the stand-in instead: a magenta box, so that the slip shows. A ``data:`` URI
would have spared the file, but reportlab reads one only once ``rl_config.trustedHosts``
is set, a process-wide security setting that is not this package's to change.
"""

import atexit
import base64
import functools
import hashlib
import io
import shutil
import tempfile
import threading
import weakref
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, TypeAlias
from xml.sax.saxutils import quoteattr

from reportlab.pdfbase import pdfdoc

from reportlab_layout.boxes import Box

__all__ = ["PdfPage", "PdfSource", "draw_pdf_page", "inline_pdf", "pdf_page", "pdf_placeholders"]

PdfSource: TypeAlias = "str | Path | bytes | IO[bytes] | PdfPage"
"""A PDF page, or a PDF to take a page from: a path, its bytes or a binary file."""

# One magenta pixel: what a plain Paragraph paints where an InlineParagraph puts the page.
_PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP4z/AfAAQAAf8c9+lcAAAAAElFTkSuQmCC"


@dataclass(frozen=True, slots=True)
class PdfPage:
    """One page of a PDF, read and ready to be laid down.

    ``box`` is the page's crop box, ``(x1, y1, x2, y2)`` in points; ``key`` names
    the page by the digest of its file and its index, so that the same page read
    twice is the same page.
    """

    data: bytes = field(repr=False)
    index: int
    box: tuple[float, float, float, float]
    key: str

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    def size(
        self, width: float | None = None, height: float | None = None, scale: float | None = None
    ) -> tuple[float, float]:
        """The drawing size in points, derived as an image's is.

        The page's own size by default; else one of ``width``, ``height`` or
        ``scale``, the aspect ratio kept -- or ``width`` and ``height`` together.
        """
        if scale is not None:
            if width is not None or height is not None:
                raise ValueError("scale is exclusive of width and height")
            return self.width * scale, self.height * scale
        if width is not None and height is not None:
            return float(width), float(height)
        if width is not None:
            return float(width), width * self.height / self.width
        if height is not None:
            return height * self.width / self.height, float(height)
        return self.width, self.height


def pdf_page(source: PdfSource, index: int = 0) -> PdfPage:
    """Read page ``index`` of a PDF given by path, bytes or binary file.

    A page that is rotated, or a PDF that is encrypted, is refused with
    ``ValueError``; a missing page raises ``IndexError``.
    """
    if isinstance(source, PdfPage):
        return source
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, str | Path):
        data = Path(source).read_bytes()
    else:
        data = source.read()
    return _read_page(data, index)


@functools.lru_cache(maxsize=4096)
def _read_page(data: bytes, index: int) -> PdfPage:
    """A page read once: the same formula is asked for on every sheet of a class."""
    page = _reader(data).pages[index]
    if page.rotation % 360:
        raise ValueError(f"page {index} is rotated by {page.rotation}°: rotated pages are not supported")
    crop = page.cropbox
    box = (float(crop.left), float(crop.bottom), float(crop.right), float(crop.top))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"page {index} has an empty box: {box}")
    return PdfPage(data, index, box, f"{hashlib.sha256(data).hexdigest()[:32]}-{index}")


def draw_pdf_page(
    canvas: Any,
    page: PdfSource,
    x: float,
    y: float,
    width: float | None = None,
    height: float | None = None,
    scale: float | None = None,
) -> Box:
    """Draw a PDF page on a reportlab canvas, its lower-left corner at ``(x, y)``.

    The size goes as for an image: the page's own by default, or one of
    ``width``, ``height``, ``scale``, the aspect ratio kept -- or ``width`` and
    ``height`` together. Any canvas will do, a flowable's ``self.canv`` included;
    the page and what it uses are written into its document once.
    """
    page = pdf_page(page)
    width, height = page.size(width, height, scale)
    name = _importer(canvas).form(page)
    x1, y1, x2, y2 = page.box
    sx, sy = width / (x2 - x1), height / (y2 - y1)
    canvas.saveState()
    canvas.transform(sx, 0, 0, sy, x - x1 * sx, y - y1 * sy)
    canvas.doForm(name)
    canvas.restoreState()
    return Box(x, y, width, height)


def inline_pdf(
    page: PdfSource,
    width: float | None = None,
    height: float | None = None,
    scale: float | None = None,
    *,
    depth: float = 0.0,
) -> str:
    """The tag of a PDF page set on the baseline, for an ``InlineParagraph``'s markup.

    The same as :func:`~reportlab_layout.inline_image`, page for image: ``width``,
    ``height`` and ``scale`` in points, ``depth`` how far the page reaches below the
    baseline -- the depth TeX reports for a formula puts the formula's baseline on
    the line's. The style needs ``autoLeading="max"``. Only an
    :class:`~reportlab_layout.InlineParagraph` draws the page: a plain
    ``Paragraph`` paints a magenta box instead.
    """
    page = pdf_page(page)
    width, height = page.size(width, height, scale)
    size = f'width="{width:.3f}" height="{height:.3f}"'
    return f'<img src={quoteattr(_stand_in_file(page))} {size} valign="{0.0 - depth:.3f}"/>'


@contextmanager
def pdf_placeholders(canvas: Any) -> Iterator[None]:
    """While the block runs, the canvas draws the stand-ins of :func:`inline_pdf` as their pages.

    reportlab draws a paragraph's images through ``canvas.drawImage``: that one
    call is caught, for the stand-ins only, and every other image goes through.
    """
    saved = canvas.__dict__.get("drawImage")
    original = canvas.drawImage

    def draw_image(
        image: Any, x: float, y: float, width: Any = None, height: Any = None, *args: Any, **kw: Any
    ) -> Any:
        page = _stand_in(image)
        if page is None:
            return original(image, x, y, width, height, *args, **kw)
        draw_pdf_page(canvas, page, x, y, width, height)
        return (width, height)

    canvas.drawImage = draw_image
    try:
        yield
    finally:
        if saved is None:
            del canvas.drawImage
        else:
            canvas.drawImage = saved


# The stand-in files inline_pdf has written, and the page each one stands for.
_STAND_INS: dict[str, PdfPage] = {}
_STAND_IN_FOLDER: list[Path] = []
_STAND_IN_LOCK = threading.Lock()


def _stand_in_file(page: PdfPage) -> str:
    """The stand-in file of a page, written on first use."""
    with _STAND_IN_LOCK:
        if not _STAND_IN_FOLDER:
            folder = Path(tempfile.mkdtemp(prefix="reportlab_layout-"))
            atexit.register(shutil.rmtree, folder, ignore_errors=True)
            _STAND_IN_FOLDER.append(folder)
        path = _STAND_IN_FOLDER[0] / f"{page.key}.png"
        if str(path) not in _STAND_INS:
            path.write_bytes(base64.b64decode(_PIXEL))
            _STAND_INS[str(path)] = page
    return str(path)


def _stand_in(image: Any) -> PdfPage | None:
    return _STAND_INS.get(getattr(image, "fileName", None) or "")


def _pypdf() -> Any:
    try:
        import pypdf
    except ImportError as error:
        raise ImportError("Laying down PDF pages needs pypdf: pip install 'reportlab_layout[pdf]'") from error
    return pypdf


def _reader(data: bytes) -> Any:
    reader = _pypdf().PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("an encrypted PDF cannot be laid down")
    return reader


# One importer per reportlab document, dropped with it.
_IMPORTERS: "weakref.WeakKeyDictionary[Any, _Importer]" = weakref.WeakKeyDictionary()
_IMPORTERS_LOCK = threading.Lock()


def _importer(canvas: Any) -> "_Importer":
    document = canvas._doc
    with _IMPORTERS_LOCK:
        importer = _IMPORTERS.get(document)
        if importer is None:
            if not isinstance(document.encrypt, pdfdoc.NoEncryption):
                # Streams are copied as they are, and reportlab encrypts only those it encodes.
                raise ValueError("PDF pages cannot be laid down in an encrypted document")
            importer = _IMPORTERS[document] = _Importer(document)
    return importer


class _Importer:
    """Writes pages of other PDFs into one reportlab document, each distinct object once."""

    def __init__(self, document: Any) -> None:
        self.document = document
        self.objects: dict[bytes, Any] = {}  # digest -> what to write in place of a reference
        self.forms: dict[str, str] = {}  # page key -> form name

    def form(self, page: PdfPage) -> str:
        name = self.forms.get(page.key)
        if name is None:
            name = self.forms[page.key] = self._write(page)
        return name

    def _write(self, page: PdfPage) -> str:
        generic = _pypdf().generic
        source = _reader(page.data).pages[page.index]
        digests = _Digests(generic)
        content, entries = _content(source, generic)
        resources = source.get("/Resources", generic.DictionaryObject())
        group = source.get("/Group")
        parts = [repr(page.box).encode(), _sized(content), digests.canonical(resources)]
        parts += [digests.canonical(entry) for entry in entries.values()]
        if group is not None:
            parts.append(digests.canonical(group))
        name = "RLP" + hashlib.sha256(b"\0".join(parts)).hexdigest()[:24]
        if pdfdoc.xObjectName(name) in self.document.idToObject:
            return name  # the same page, from another file
        dictionary = pdfdoc.PDFDictionary(
            {
                "Type": pdfdoc.PDFName("XObject"),
                "Subtype": pdfdoc.PDFName("Form"),
                "FormType": 1,
                "BBox": pdfdoc.PDFArray(list(page.box)),
                "Resources": self._convert(resources, digests, generic),
            }
        )
        for key, value in entries.items():
            dictionary[key] = self._convert(value, digests, generic)
        if group is not None:
            dictionary["Group"] = self._convert(group, digests, generic)
        self.document.Reference(pdfdoc.PDFStream(dictionary, content), pdfdoc.xObjectName(name))
        return name

    def _convert(self, obj: Any, digests: "_Digests", generic: Any) -> Any:
        if isinstance(obj, generic.IndirectObject):
            digest = digests.of(obj)
            found = self.objects.get(digest)
            if found is None:
                found = self.document.Reference(self._direct(obj.get_object(), digests, generic))
                self.objects[digest] = found
            return found
        return self._direct(obj, digests, generic)

    def _direct(self, obj: Any, digests: "_Digests", generic: Any) -> Any:
        if isinstance(obj, generic.StreamObject):
            entries = {
                key[1:]: self._convert(value, digests, generic)
                for key, value in obj.items()
                if key != "/Length"
            }
            # Filter kept, data untouched: reportlab encodes only a stream without one.
            return pdfdoc.PDFStream(pdfdoc.PDFDictionary(entries), _raw(obj))
        if isinstance(obj, generic.DictionaryObject):
            return pdfdoc.PDFDictionary(
                {key[1:]: self._convert(value, digests, generic) for key, value in obj.items()}
            )
        if isinstance(obj, generic.ArrayObject):
            return pdfdoc.PDFArray([self._convert(value, digests, generic) for value in obj])
        return _token(obj)


class _Digests:
    """The content digest of each object of one source PDF, memoised.

    Two objects with equal digests are equal, references followed: the digest of a
    reference is the digest of what it refers to, not its object number.
    """

    def __init__(self, generic: Any) -> None:
        self.generic = generic
        self.done: dict[tuple[int, int], bytes] = {}
        self.open: set[tuple[int, int]] = set()

    def of(self, reference: Any) -> bytes:
        ident = (reference.idnum, reference.generation)
        found = self.done.get(ident)
        if found is None:
            if ident in self.open:
                raise ValueError("the page's resources refer back to themselves: it cannot be laid down")
            self.open.add(ident)
            found = self.done[ident] = hashlib.sha256(self.canonical(reference.get_object())).digest()
            self.open.discard(ident)
        return found

    def canonical(self, obj: Any) -> bytes:
        generic = self.generic
        if isinstance(obj, generic.IndirectObject):
            return b"R" + self.of(obj)
        if isinstance(obj, generic.StreamObject):
            return b"S" + self._dictionary(obj) + _sized(_raw(obj))
        if isinstance(obj, generic.DictionaryObject):
            return self._dictionary(obj)
        if isinstance(obj, generic.ArrayObject):
            return b"[" + b"".join(_sized(self.canonical(value)) for value in obj) + b"]"
        return _token(obj)

    def _dictionary(self, obj: Any) -> bytes:
        items = sorted((key, value) for key, value in obj.items() if key != "/Length")
        return (
            b"<<"
            + b"".join(_sized(key.encode()) + _sized(self.canonical(value)) for key, value in items)
            + b">>"
        )


def _content(page: Any, generic: Any) -> tuple[bytes, dict[str, Any]]:
    """The page's content, and the stream entries it needs to be read.

    A single stream is copied as it is, filter and all; several are decoded, joined
    and compressed again, as one.
    """
    contents = page.get("/Contents")
    contents = contents.get_object() if contents is not None else None
    if contents is None:
        return b"", {}
    if isinstance(contents, generic.StreamObject):
        entries = {key[1:]: contents[key] for key in ("/Filter", "/DecodeParms") if key in contents}
        return _raw(contents), entries
    joined = b"\n".join(part.get_object().get_data() for part in contents)
    return zlib.compress(joined), {"Filter": generic.NameObject("/FlateDecode")}


def _raw(stream: Any) -> bytes:
    """A stream's data as stored, still encoded."""
    data: bytes = stream._data
    return data


def _token(obj: Any) -> bytes:
    """A number, name, string, boolean or null, written as pypdf writes it."""
    buffer = io.BytesIO()
    obj.write_to_stream(buffer)
    return buffer.getvalue()


def _sized(data: bytes) -> bytes:
    return len(data).to_bytes(8, "big") + data
