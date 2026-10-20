"""Markdown with LaTeX formulas, turned into flowables and laid down page after page.

A text written once in Markdown, its formulas between dollars, shows on a web page
through markdown-it and KaTeX; this module sets the same text in a PDF. It reads it
with **markdown-it-py**, in CommonMark with tables, strikethrough and the
``dollarmath`` plugin of mdit-py-plugins -- the reading a site built on markdown-it
gives it, so that the PDF and the page cut the text the same way. Raw HTML is not
interpreted: it is written as text. Both packages are an optional dependency,
``reportlab_layout[markdown]``.

**The formulas are not typeset here.** No renderer that does without LaTeX knows
what a real preamble defines, and this package depends on no TeX. A *formula
composer* does it: any callable that takes the list of the text's formulas, as
:class:`MathFragment` (the LaTeX, and whether it is displayed), and returns for each
one, in the same order, an object with the attributes of :class:`TypesetMath`: a
file, a one-page PDF or an image, and its box. It is called **once per text**, with
every distinct formula, so that a composer that compiles can do it in one batch.
:class:`reportlab_layout.texmath.TexFormulas` is one, built on texformules.

A formula in the line (``$…$``) sits on the baseline, its depth below it, through
:func:`~reportlab_layout.inline_pdf` or :func:`~reportlab_layout.inline_image`, in
an :class:`~reportlab_layout.InlineParagraph` whose lines make room for it. A
displayed one (``$$…$$``, on its own lines or inside a paragraph) is centred on a
line of its own, its label, ``$$…$$ (1)``, flush right on its baseline. Each is
scaled from the size it was typeset at to the type size of the text around it.

A formula the composer refuses -- or every formula, without a composer -- is
written as it stands, dollars included, in the font of inline code; the refusal is
logged and kept in the list of problems, and the document goes on. So is an image
whose file cannot be read.
"""

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, StyleSheet1
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, ListFlowable, ListItem, Table, TableStyle, XPreformatted
from reportlab.platypus.flowables import HRFlowable

from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.columns import _UNBOUNDED, pack_columns
from reportlab_layout.images import image_spec, inline_image
from reportlab_layout.paragraphs import InlineParagraph
from reportlab_layout.styles import StyleLike, resolve_style

if TYPE_CHECKING:
    from markdown_it.tree import SyntaxTreeNode

__all__ = [
    "MarkdownProblem",
    "MarkdownStyles",
    "MathComposer",
    "MathFragment",
    "TypesetMath",
    "markdown_flowables",
]

logger = logging.getLogger(__name__)

_FUZZ = 1e-6
_PDF = b"%PDF"


@dataclass(frozen=True, slots=True)
class MathFragment:
    """A formula of the text, as the composer receives it.

    ``latex`` is the formula without its dollars, as written; ``display`` is true
    for ``$$…$$``.
    """

    latex: str
    display: bool

    @property
    def source(self) -> str:
        """The formula as written in the text, dollars included."""
        dollars = "$$" if self.display else "$"
        return f"{dollars}{self.latex}{dollars}"


class TypesetMath(Protocol):
    """What a composer returns for each formula: a file and its box, or a refusal.

    ``file`` is a one-page PDF (laid down as vector drawing, which takes the
    ``pdf`` extra) or an image, told apart by their content; ``None`` refuses the
    formula. ``width`` and ``height`` are the total size of the file's box, in
    PDF points, and ``depth`` how far below the baseline it reaches. ``size`` is
    the type size it was typeset at, in PDF points: the formula is scaled to the
    type size of its line. ``error`` says why a formula is refused.
    """

    @property
    def file(self) -> str | Path | None: ...
    @property
    def width(self) -> float: ...
    @property
    def height(self) -> float: ...
    @property
    def depth(self) -> float: ...
    @property
    def size(self) -> float: ...
    @property
    def error(self) -> str | None: ...


#: Typesets the formulas of a text, all at once: one result per fragment, in order.
MathComposer = Callable[[Sequence[MathFragment]], Sequence[TypesetMath]]


@dataclass(frozen=True, slots=True)
class MarkdownProblem:
    """Something of the text that could not be set as written, and was set as text.

    ``kind`` is ``"formula"`` or ``"image"``; ``source`` is what the text says.
    """

    kind: str
    source: str
    message: str


@dataclass(frozen=True)
class MarkdownStyles:
    """The style of each element of the text: a style of the sheet, or its name.

    The names that :func:`~reportlab_layout.make_stylesheet` defines are the
    defaults. A name the sheet lacks -- a sheet of one's own -- falls back on the
    style the field describes, derived from ``paragraph``, so a text always sets.

    :param paragraph: the paragraphs, and the base of the derived styles.
    :param headings: ``#`` to ``######``, one style per level; a heading is kept
        with the block that follows it.
    :param code: the code blocks; its font is that of inline code too.
    :param quote: the paragraphs of a quotation (``>``), which is indented by
        ``quote_indent`` with a rule on its left.
    :param item: the paragraphs of a list item.
    :param cell, header: the cells of a table, and those of its heading row.
    :param display: the displayed formulas and images: its space before and
        after, and the font of an equation's label.
    """

    paragraph: StyleLike = "BodyText"
    headings: tuple[StyleLike, ...] = ("Heading1", "Heading2", "Heading3", "Heading4", "Heading5", "Heading6")
    code: StyleLike = "Code"
    quote: StyleLike = "Quote"
    item: StyleLike = "List Item"
    cell: StyleLike = "Table Cell"
    header: StyleLike = "Table Header"
    display: StyleLike = "Display"
    #: Behind inline code; ``None`` for none.
    code_background: ColorLike | None = "#eeeeee"
    link_color: ColorLike = "#1a5fb4"
    #: The rules: ``---``, the lines of a table, the bar of a quotation.
    rule_color: ColorLike = "#999999"
    rule_width: float = 0.5
    #: How far a list's text is indented, in points, at every level.
    list_indent: float = 18
    #: The bullets of each level of an unordered list, in turn.
    bullets: tuple[str, ...] = ("•", "–", "◦")
    quote_indent: float = 14


def _parser() -> Any:
    try:
        from markdown_it import MarkdownIt
        from mdit_py_plugins.dollarmath import dollarmath_plugin
    except ImportError as error:  # pragma: no cover - depends on the installation
        raise ImportError(
            'Markdown needs markdown-it-py and mdit-py-plugins: pip install "reportlab_layout[markdown]"'
        ) from error
    parser = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    parser.enable(["table", "strikethrough"])
    dollarmath_plugin(parser, double_inline=True)
    return parser


def parse_markdown(text: str) -> "SyntaxTreeNode":
    """The syntax tree of ``text``, read as :func:`markdown_flowables` reads it."""
    from markdown_it.tree import SyntaxTreeNode

    return SyntaxTreeNode(_parser().parse(text or ""))


_MATH_INLINE = frozenset({"math_inline", "math_inline_double"})
_MATH_BLOCK = frozenset({"math_block", "math_block_label"})


def math_fragments(tree: "SyntaxTreeNode") -> list[MathFragment]:
    """The distinct formulas of a tree, in the order of the text."""
    found: dict[MathFragment, None] = {}
    for node in tree.walk():
        if node.type in _MATH_INLINE or node.type in _MATH_BLOCK:
            found[_fragment(node)] = None
    return list(found)


def _fragment(node: "SyntaxTreeNode") -> MathFragment:
    return MathFragment(node.content, node.type != "math_inline")


@dataclass(frozen=True, slots=True)
class _Set:
    """A formula the composer typeset: its file, read once, and its box."""

    file: Path
    pdf: bool
    width: float
    height: float
    depth: float
    size: float


def markdown_flowables(
    text: str,
    *,
    stylesheet: StyleSheet1 | None = None,
    styles: MarkdownStyles | None = None,
    formulas: MathComposer | None = None,
    base: str | Path | None = None,
    width: float | None = None,
    problems: list[MarkdownProblem] | None = None,
) -> list[Flowable]:
    """The flowables of a Markdown text, ready for a frame, columns or a document.

    :param stylesheet: where the names of ``styles`` are looked up; the shared
        :data:`~reportlab_layout.STYLES` by default.
    :param formulas: the formula composer; without one, the formulas are
        written as they stand.
    :param base: the folder relative image paths start from; the current one
        by default.
    :param width: the width the text will be set in, in points: images and
        tables are sized to fit it. Without it, they keep their natural width.
    :param problems: a list to which the formulas refused and the images not
        found are appended, besides being logged.
    """
    tree = parse_markdown(text)
    builder = _Builder(
        stylesheet,
        styles or MarkdownStyles(),
        Path(base) if base is not None else Path(),
        problems if problems is not None else [],
    )
    builder.typeset(math_fragments(tree), formulas)
    return builder.blocks(tree.children, _UNBOUNDED if width is None else width, 0)


class _Builder:
    """Turns a syntax tree into flowables, the formulas typeset beforehand."""

    def __init__(
        self,
        stylesheet: StyleSheet1 | None,
        styles: MarkdownStyles,
        base: Path,
        problems: list[MarkdownProblem],
    ) -> None:
        self.sheet = stylesheet
        self.styles = styles
        self.base = base
        self.problems = problems
        self.math: dict[MathFragment, _Set | None] = {}
        self._derived: dict[tuple[str, tuple[tuple[str, Any], ...]], ParagraphStyle] = {}
        self._resolved: dict[str, ParagraphStyle] = {}
        self.body = self.style("paragraph")

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------
    _FALLBACKS: dict[str, dict[str, Any]] = {  # noqa: RUF012 - read only
        "quote": {"textColor": "#444444"},
        "item": {"spaceBefore": 2},
        "cell": {"spaceBefore": 0, "spaceAfter": 0},
        "header": {"spaceBefore": 0, "spaceAfter": 0, "fontName": "Helvetica-Bold"},
        "display": {"alignment": TA_CENTER, "spaceBefore": 6, "spaceAfter": 6},
        "code": {"fontName": "Courier", "fontSize": 8, "leading": 8.8},
    }

    def style(self, name: str, level: int = 0) -> ParagraphStyle:
        """The style of an element, by the name of its field in :class:`MarkdownStyles`."""
        key = f"{name}{level}"
        if key in self._resolved:
            return self._resolved[key]
        wanted = getattr(self.styles, name)
        if name == "headings":
            wanted = wanted[min(level, len(wanted)) - 1]
        try:
            style = resolve_style(wanted, self.sheet)
        except KeyError:
            if name == "paragraph":
                style = resolve_style("Normal", self.sheet)
            elif name == "headings":
                size = max(18 - 2 * level, 9)
                style = ParagraphStyle(
                    f"md-h{level}",
                    parent=self.body,
                    fontName="Helvetica-Bold",
                    fontSize=size,
                    leading=1.2 * size,
                )
            else:
                style = ParagraphStyle(f"md-{name}", parent=self.body, **self._FALLBACKS[name])
        if name == "headings":
            style = self.derive(style, keepWithNext=1)
        self._resolved[key] = style
        return style

    def derive(self, style: ParagraphStyle, **changes: Any) -> ParagraphStyle:
        key = (style.name, tuple(sorted(changes.items())))
        if key not in self._derived:
            self._derived[key] = ParagraphStyle(f"{style.name}~{len(self._derived)}", parent=style, **changes)
        return self._derived[key]

    def warn(self, kind: str, source: str, message: str) -> None:
        self.problems.append(MarkdownProblem(kind, source, message))
        logger.warning("%s %s set as text: %s", kind, source, message)

    # ------------------------------------------------------------------
    # Formulas
    # ------------------------------------------------------------------
    def typeset(self, fragments: list[MathFragment], composer: MathComposer | None) -> None:
        if not fragments:
            return
        if composer is None:
            self.math = dict.fromkeys(fragments)
            return
        results = list(composer(fragments))
        if len(results) != len(fragments):
            raise ValueError(f"The composer returned {len(results)} results for {len(fragments)} formulas")
        for fragment, result in zip(fragments, results, strict=True):
            self.math[fragment] = self._accept(fragment, result)

    def _accept(self, fragment: MathFragment, result: TypesetMath) -> _Set | None:
        file = result.file
        if file is None or result.error:
            self.warn("formula", fragment.source, result.error or "refused by the composer")
            return None
        path = Path(file)
        try:
            with path.open("rb") as handle:
                pdf = handle.read(4) == _PDF
        except OSError as error:
            self.warn("formula", fragment.source, f"cannot read {path}: {error.strerror}")
            return None
        if result.width <= 0 or result.height <= 0 or result.size <= 0:
            self.warn("formula", fragment.source, "the composer gave it an empty box")
            return None
        return _Set(path, pdf, result.width, result.height, result.depth, result.size)

    def _as_text(self, source: str) -> str:
        return self.code_markup(escape(source))

    def inline_math(self, node: "SyntaxTreeNode", style: ParagraphStyle) -> tuple[str, bool]:
        fragment = _fragment(node)
        typeset = self.math.get(fragment)
        if typeset is None:
            return self._as_text(fragment.source), False
        scale = style.fontSize / typeset.size
        width, height, depth = typeset.width * scale, typeset.height * scale, typeset.depth * scale
        if typeset.pdf:
            from reportlab_layout.pdfpages import inline_pdf

            return inline_pdf(typeset.file, width, height, depth=depth), True
        return inline_image(typeset.file, width, height, depth=depth), True

    def display_math(self, node: "SyntaxTreeNode") -> Flowable:
        fragment = _fragment(node)
        style = self.style("display")
        typeset = self.math.get(fragment)
        label = node.info if node.type == "math_block_label" else ""
        if typeset is None:
            source = fragment.source + (f" ({label})" if label else "")
            return InlineParagraph(self._as_text(source), style)
        scale = style.fontSize / typeset.size
        return _Figure(
            typeset.file,
            typeset.pdf,
            typeset.width * scale,
            typeset.height * scale,
            style,
            depth=typeset.depth * scale,
            label=f"({label})" if label else "",
        )

    # ------------------------------------------------------------------
    # Blocks
    # ------------------------------------------------------------------
    def blocks(self, nodes: Sequence["SyntaxTreeNode"], width: float, depth: int) -> list[Flowable]:
        story: list[Flowable] = []
        for node in nodes:
            story += self.block(node, width, depth)
        return story

    def block(self, node: "SyntaxTreeNode", width: float, depth: int) -> list[Flowable]:
        kind = node.type
        if kind == "paragraph":
            return self.paragraph(node, self.style("paragraph"), width)
        if kind == "heading":
            return self.paragraph(node, self.style("headings", int(node.tag[1:])), width)
        if kind in _MATH_BLOCK:
            return [self.display_math(node)]
        if kind in ("fence", "code_block"):
            return [XPreformatted(escape(node.content.rstrip("\n")), self.style("code"))]
        if kind in ("bullet_list", "ordered_list"):
            return [self.listing(node, width, depth)]
        if kind == "blockquote":
            indent = self.styles.quote_indent
            content = [self._restyle(node, "quote", width - indent, depth)]
            return [_Quote(content[0], indent, to_color(self.styles.rule_color), self.styles.rule_width)]
        if kind == "table":
            return [self.table(node, width)]
        if kind == "hr":
            return [
                HRFlowable(
                    width="100%",
                    thickness=self.styles.rule_width,
                    color=to_color(self.styles.rule_color),
                    spaceBefore=6,
                    spaceAfter=6,
                )
            ]
        # html_block cannot occur with html off; anything unknown is set as its text.
        return [InlineParagraph(escape(node.content), self.style("paragraph"))] if node.content else []

    def _restyle(self, node: "SyntaxTreeNode", name: str, width: float, depth: int) -> list[Flowable]:
        """The blocks inside a quotation or a list item: their paragraphs in that element's style."""
        story: list[Flowable] = []
        for child in node.children:
            if child.type == "paragraph":
                story += self.paragraph(child, self.style(name), width)
            else:
                story += self.block(child, width, depth)
        return story

    def listing(self, node: "SyntaxTreeNode", width: float, depth: int) -> Flowable:
        indent = self.styles.list_indent
        body = self.style("item")
        items = [ListItem(self._restyle(item, "item", width - indent, depth + 1)) for item in node.children]
        common = {
            "leftIndent": indent,
            "bulletFontName": body.fontName,
            "bulletFontSize": body.fontSize,
            "bulletColor": body.textColor,
            "spaceBefore": body.spaceBefore,
        }
        if node.type == "ordered_list":
            start = int(node.attrs.get("start", 1))
            return ListFlowable(items, bulletType="1", start=start, bulletFormat="%s.", **common)
        bullet = self.styles.bullets[depth % len(self.styles.bullets)]
        return ListFlowable(items, bulletType="bullet", start=bullet, **common)

    # ------------------------------------------------------------------
    # Paragraphs
    # ------------------------------------------------------------------
    def paragraph(self, node: "SyntaxTreeNode", style: ParagraphStyle, width: float) -> list[Flowable]:
        """A paragraph, cut where a ``$$…$$`` stands inside it, or an image alone in it."""
        inline = node.children[0] if node.children else None
        if inline is None:
            return []
        pieces = list(inline.children)
        alone = [child for child in pieces if not (child.type == "text" and not child.content.strip())]
        if len(alone) == 1 and alone[0].type == "image":
            return [self.figure(alone[0], width, style)]
        story: list[Flowable] = []
        run: list[SyntaxTreeNode] = []
        for child in pieces:
            if child.type == "math_inline_double":
                story += self._paragraph_of(run, style, width)
                story.append(self.display_math(child))
                run = []
            else:
                run.append(child)
        story += self._paragraph_of(run, style, width)
        return story

    def _paragraph_of(
        self, nodes: list["SyntaxTreeNode"], style: ParagraphStyle, width: float
    ) -> list[Flowable]:
        markup, inline = self.markup(nodes, style, width)
        if not markup.strip() or markup.strip() == "<br/>":
            return []
        if inline:
            style = self.derive(style, autoLeading="max")
        return [InlineParagraph(markup.strip(), style)]

    def markup(
        self, nodes: Sequence["SyntaxTreeNode"], style: ParagraphStyle, width: float
    ) -> tuple[str, bool]:
        """reportlab's paragraph markup for inline nodes, and whether it holds images."""
        out: list[str] = []
        images = False
        for node in nodes:
            kind = node.type
            if kind == "text":
                out.append(escape(node.content))
            elif kind == "softbreak":
                out.append(" ")
            elif kind == "hardbreak":
                out.append("<br/>")
            elif kind == "code_inline":
                out.append(self.code_markup(escape(node.content)))
            elif kind in _MATH_INLINE:
                tag, image = self.inline_math(node, style)
                out.append(tag)
                images |= image
            elif kind == "image":
                tag, image = self.inline_picture(node, style, width)
                out.append(tag)
                images |= image
            else:
                inner, image = self.markup(node.children, style, width)
                images |= image
                out.append(self._wrap(node, inner))
        return "".join(out), images

    def _wrap(self, node: "SyntaxTreeNode", inner: str) -> str:
        kind = node.type
        if kind == "strong":
            return f"<b>{inner}</b>"
        if kind == "em":
            return f"<i>{inner}</i>"
        if kind == "s":
            return f"<strike>{inner}</strike>"
        if kind == "link":
            href = str(node.attrs.get("href", ""))
            color = _markup_color(self.styles.link_color)
            colored = f' color="{color}"' if color else ""
            return f"<a href={quoteattr(href)}{colored}>{inner}</a>"
        return inner

    def code_markup(self, escaped: str) -> str:
        font = self.style("code").fontName
        background = _markup_color(self.styles.code_background)
        back = f' backColor="{background}"' if background else ""
        return f'<font face="{font}"{back}>{escaped}</font>'

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    def _image_file(self, node: "SyntaxTreeNode") -> tuple[Path | None, str]:
        """The image's file, or None after a warning; and the markdown that names it."""
        src = str(node.attrs.get("src", ""))
        written = f"![{node.content}]({src})"
        if re.match(r"[a-z][a-z0-9+.-]*:", src, re.IGNORECASE):
            self.warn("image", written, "only local files are read, not addresses")
            return None, written
        path = Path(src) if Path(src).is_absolute() else self.base / src
        if not path.is_file():
            self.warn("image", written, f"no file {path}")
            return None, written
        return path, written

    def _image_size(self, path: Path, written: str) -> tuple[bool, float, float] | None:
        """Whether the file is a PDF, and its natural size in points (a pixel per point)."""
        try:
            with path.open("rb") as handle:
                pdf = handle.read(4) == _PDF
            if pdf:
                from reportlab_layout.pdfpages import pdf_page

                page = pdf_page(path)
                return True, page.width, page.height
            spec = image_spec(path)
        except Exception as error:
            self.warn("image", written, f"cannot read {path}: {error}")
            return None
        return False, float(spec.width), float(spec.height)

    def _alt(self, node: "SyntaxTreeNode") -> str:
        return f"[{escape(node.content)}]"

    def figure(self, node: "SyntaxTreeNode", width: float, style: ParagraphStyle) -> Flowable:
        """An image alone in its paragraph: a block, centred, no wider than the text."""
        path, written = self._image_file(node)
        size = self._image_size(path, written) if path is not None else None
        if path is None or size is None:
            return InlineParagraph(self._alt(node), style)
        pdf, natural_width, natural_height = size
        scale = min(1.0, width / natural_width)
        return _Figure(path, pdf, natural_width * scale, natural_height * scale, self.style("display"))

    def inline_picture(self, node: "SyntaxTreeNode", style: ParagraphStyle, width: float) -> tuple[str, bool]:
        path, written = self._image_file(node)
        size = self._image_size(path, written) if path is not None else None
        if path is None or size is None:
            return self._alt(node), False
        pdf, natural_width, natural_height = size
        scale = min(1.0, width / natural_width)
        if pdf:
            from reportlab_layout.pdfpages import inline_pdf

            return inline_pdf(path, natural_width * scale, natural_height * scale), True
        return inline_image(path, natural_width * scale, natural_height * scale), True

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    def table(self, node: "SyntaxTreeNode", width: float) -> Flowable:
        rows: list[list[Flowable]] = []
        naturals: list[list[float]] = []
        header_rows = 0
        for section in node.children:
            for row in section.children:
                cells: list[Flowable] = []
                lengths: list[float] = []
                for cell in row.children:
                    base = self.style("header" if cell.type == "th" else "cell")
                    align = str(cell.attrs.get("style", "")).removeprefix("text-align:")
                    alignment = {"right": TA_RIGHT, "center": TA_CENTER}.get(align, TA_LEFT)
                    style = self.derive(base, alignment=alignment)
                    nodes = cell.children[0].children if cell.children else []
                    markup, inline = self.markup(nodes, style, width)
                    if inline:
                        style = self.derive(style, autoLeading="max")
                    paragraph = InlineParagraph(markup, style)
                    cells.append(paragraph)
                    lengths.append(_natural_width(paragraph))
                rows.append(cells)
                naturals.append(lengths)
                if section.type == "thead":
                    header_rows += 1
        columns = max((len(row) for row in rows), default=0)
        padding = 12.0  # reportlab's 6 pt on either side of a cell
        natural = [
            max((row[i] for row in naturals if i < len(row)), default=0.0) + padding for i in range(columns)
        ]
        widths = _fit(natural, width)
        rule = to_color(self.styles.rule_color)
        thickness = self.styles.rule_width
        commands: list[tuple[Any, ...]] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), thickness, rule),
        ]
        if header_rows:
            commands.append(("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 2 * thickness, rule))
        table = Table(rows, colWidths=widths, repeatRows=header_rows, hAlign="LEFT")
        table.setStyle(TableStyle(commands))
        table.spaceBefore = table.spaceAfter = 6
        return table


def _markup_color(value: ColorLike | None) -> str | None:
    """A colour as paragraph markup writes it, ``#rrggbb``; ``None`` for none."""
    color = to_color(value)
    if color is None:
        return None
    red, green, blue = (round(255 * channel) for channel in color.rgb())
    return f"#{red:02x}{green:02x}{blue:02x}"


def _natural_width(paragraph: InlineParagraph) -> float:
    """The width of a paragraph's longest line set unbroken, formulas and bold included."""
    paragraph.wrap(_UNBOUNDED, _UNBOUNDED)
    return float(max(paragraph.getActualLineWidths0(), default=0.0))


def _fit(natural: list[float], width: float) -> list[float]:
    """Column widths: natural when they fit; else a short column keeps its own, the others share the rest.

    A column is short when it needs less than an equal share. What is left goes to
    the long ones in proportion to what they need.
    """
    if not natural or sum(natural) <= width:
        return natural
    share = width / len(natural)
    short = [w if w <= share else None for w in natural]
    room = width - sum(w for w in short if w is not None)
    wanted = sum(w for w, s in zip(natural, short, strict=True) if s is None)
    return [s if s is not None else w * room / wanted for w, s in zip(natural, short, strict=True)]


class _Figure(Flowable):
    """An image or a PDF page, centred on a line of its own; a label flush right on its baseline.

    It takes the whole width it is offered and centres itself in it; offered
    less room than it needs, label included, it is scaled down to fit.
    """

    def __init__(
        self,
        file: Path,
        pdf: bool,
        width: float,
        height: float,
        style: ParagraphStyle,
        *,
        depth: float = 0.0,
        label: str = "",
    ) -> None:
        super().__init__()
        self.file, self.pdf = file, pdf
        self.natural = (width, height)
        self.style = style
        self.depth = depth
        self.label = label
        self.spaceBefore, self.spaceAfter = style.spaceBefore, style.spaceAfter
        self.scale = 1.0

    def _label_width(self) -> float:
        return stringWidth(self.label, self.style.fontName, self.style.fontSize) if self.label else 0.0

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        width, height = self.natural
        label = self._label_width()
        room = available_width - (2 * (label + self.style.fontSize) if label else 0.0)
        self.scale = min(1.0, room / width) if width > _FUZZ and room > _FUZZ else 1.0
        # The whole line: PDFMaker.draw places a block by its own halign, not the flowable's.
        self.width = available_width
        self.height = height * self.scale
        return self.width, self.height

    def draw(self) -> None:
        width, height = self.natural[0] * self.scale, self.natural[1] * self.scale
        x = (self.width - width) / 2
        if self.pdf:
            from reportlab_layout.pdfpages import draw_pdf_page

            draw_pdf_page(self.canv, self.file, x, 0, width, height)
        else:
            self.canv.drawImage(str(self.file), x, 0, width, height, mask="auto")
        if self.label:
            canvas = self.canv
            canvas.saveState()
            canvas.setFont(self.style.fontName, self.style.fontSize)
            canvas.setFillColor(self.style.textColor)
            canvas.drawRightString(self.width, self.depth * self.scale, self.label)
            canvas.restoreState()


class _Quote(Flowable):
    """Blocks indented, with a rule down their left: a quotation, which splits between them."""

    def __init__(self, content: list[Flowable], indent: float, color: Any, thickness: float) -> None:
        super().__init__()
        self.content = content
        self.indent, self.color, self.thickness = indent, color, thickness
        self.spaceBefore = content[0].getSpaceBefore() if content else 0
        self.spaceAfter = content[-1].getSpaceAfter() if content else 0
        self._placements: Sequence[Any] = ()

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        packing = pack_columns(self.canv, self.content, available_width - self.indent, _UNBOUNDED, 1)
        self._placements = packing.placements
        self.width, self.height = available_width, packing.height
        return self.width, self.height

    def split(self, available_width: float, available_height: float) -> list[Flowable]:
        packing = pack_columns(self.canv, self.content, available_width - self.indent, available_height, 1)
        if not packing.placements or not packing.rest:
            return []
        rule = (self.indent, self.color, self.thickness)
        return [_Quote([p.flowable for p in packing.placements], *rule), _Quote(list(packing.rest), *rule)]

    def draw(self) -> None:
        canvas = self.canv
        for placement in self._placements:
            placement.flowable.drawOn(canvas, self.indent, self.height - placement.bottom)
        canvas.saveState()
        canvas.setStrokeColor(self.color)
        canvas.setLineWidth(2 * self.thickness)
        x = self.indent / 3
        canvas.line(x, 0, x, self.height)
        canvas.restoreState()
