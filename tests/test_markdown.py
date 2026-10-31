"""Markdown with formulas: the reading, the composer called once, the blocks, the pages."""

import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import KeepTogether, ListFlowable, Table, XPreformatted
from reportlab.platypus.flowables import HRFlowable

pytest.importorskip("markdown_it")
pytest.importorskip("mdit_py_plugins")

from reportlab_layout import (
    MARKDOWN_CLASSES,
    InlineParagraph,
    MarkdownClass,
    MarkdownStyles,
    MathFragment,
    PDFMaker,
    markdown_flowables,
    pdf_elements,
)
from reportlab_layout.markdown import _Figure, _fit, _Quote, math_fragments, parse_markdown


@dataclass
class Result:
    file: Path | None
    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0
    size: float = 10.0
    error: str | None = None


class Composer:
    """Typesets each formula as a black PDF page, 20 x 10 pt in the line, 60 x 30 displayed.

    A formula holding ``bad`` is refused; ``png`` makes it an image instead.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.calls: list[list[MathFragment]] = []

    def __call__(self, fragments):
        self.calls.append(list(fragments))
        results = []
        for rank, fragment in enumerate(fragments):
            if "bad" in fragment.latex:
                results.append(Result(None, error="Undefined control sequence"))
                continue
            width, height, depth = (60.0, 30.0, 10.0) if fragment.display else (20.0, 10.0, 3.0)
            if "png" in fragment.latex:
                path = self.folder / f"formula{len(self.calls)}-{rank}.png"
                PILImage.new("RGB", (int(width), int(height))).save(path)
            else:
                path = self.folder / f"formula{len(self.calls)}-{rank}.pdf"
                canvas = pdfcanvas.Canvas(str(path), pagesize=(width, height))
                canvas.drawString(0, depth, fragment.latex)  # distinct pages, one font
                canvas.save()
            results.append(Result(path, width, height, depth))
        return results


@pytest.fixture
def composer(tmp_path: Path) -> Composer:
    return Composer(tmp_path)


def build(text: str, stylesheet: StyleSheet1, **kwargs) -> list:
    return markdown_flowables(text, stylesheet=stylesheet, width=400, **kwargs)


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------
def test_the_formulas_are_gathered_once_in_the_order_of_the_text():
    tree = parse_markdown("$a$ and $$b$$ then\n\n$$\nc\n$$\n\n$a$ again")
    assert math_fragments(tree) == [
        MathFragment("a", False),
        MathFragment("b", True),
        MathFragment("\nc\n", True),
    ]


def test_a_fragment_gives_back_its_source():
    assert MathFragment("x", False).source == "$x$"
    assert MathFragment("x", True).source == "$$x$$"


def test_the_composer_is_called_once_with_every_distinct_formula(stylesheet, composer):
    build("# $a$\n\nText $a$, $b$.\n\n- $c$\n\n| $d$ |\n|---|\n| $e$ |", stylesheet, formulas=composer)
    assert len(composer.calls) == 1
    assert [fragment.latex for fragment in composer.calls[0]] == ["a", "b", "c", "d", "e"]


def test_no_formula_no_call(stylesheet, composer):
    build("Plain text.", stylesheet, formulas=composer)
    assert composer.calls == []


def test_a_composer_that_miscounts_is_refused(stylesheet):
    with pytest.raises(ValueError, match="1 results for 2 formulas"):
        build("$a$ $b$", stylesheet, formulas=lambda fragments: [Result(None)])


def test_raw_html_is_written_as_text(stylesheet):
    [paragraph] = build("a <b>bold</b>", stylesheet)
    assert "&lt;b&gt;bold&lt;/b&gt;" in paragraph.text


# ----------------------------------------------------------------------
# Formulas
# ----------------------------------------------------------------------
def test_an_inline_formula_sits_on_the_baseline_at_the_size_of_its_line(stylesheet, composer):
    [paragraph] = build("Hence $x$.", stylesheet, formulas=composer)
    assert isinstance(paragraph, InlineParagraph)
    assert paragraph.style.autoLeading == "max"
    # BodyText is 10 pt, the formula was set at 10: drawn as is, its depth below the baseline.
    assert 'width="20.000" height="10.000" valign="-3.000"' in paragraph.text


def test_a_formula_in_a_heading_is_scaled_to_the_heading(stylesheet, composer):
    [heading] = build("# On $x$", stylesheet, formulas=composer)
    assert stylesheet["Heading1"].fontSize == 18
    assert 'width="36.000" height="18.000" valign="-5.400"' in heading.text
    assert heading.style.keepWithNext


def test_an_image_formula_goes_inline_too(stylesheet, composer):
    [paragraph] = build("Hence $png$.", stylesheet, formulas=composer)
    assert ".png" in paragraph.text
    assert 'valign="-3.000"' in paragraph.text


def test_a_refused_formula_is_written_as_it_stands_and_reported(stylesheet, composer, caplog):
    problems = []
    with caplog.at_level(logging.WARNING, logger="reportlab_layout.markdown"):
        [paragraph] = build("Hence $\\bad<1$.", stylesheet, formulas=composer, problems=problems)
    assert '<font face="Courier" backColor="#eeeeee">$\\bad&lt;1$</font>' in paragraph.text
    assert [(p.kind, p.source, p.message) for p in problems] == [
        ("formula", "$\\bad<1$", "Undefined control sequence")
    ]
    assert "Undefined control sequence" in caplog.text


def test_without_a_composer_the_formulas_are_written_silently(stylesheet):
    problems = []
    [paragraph] = build("Hence $x$.", stylesheet, problems=problems)
    assert "$x$</font>" in paragraph.text
    assert problems == []


def test_a_missing_file_refuses_the_formula(stylesheet, tmp_path):
    problems = []
    build("$x$", stylesheet, formulas=lambda f: [Result(tmp_path / "none.pdf", 1, 1, 0)], problems=problems)
    assert "cannot read" in problems[0].message


def test_a_displayed_formula_is_centred_with_its_label(stylesheet, composer):
    [figure] = build("$$\nx\n$$ (2)", stylesheet, formulas=composer)
    assert isinstance(figure, _Figure)
    assert figure.label == "(2)"
    assert figure.wrap(400, 800) == (400, 30.0)
    assert figure.spaceBefore == figure.spaceAfter == 6


def test_a_display_inside_a_paragraph_cuts_it(stylesheet, composer):
    story = build("before $$x$$ after", stylesheet, formulas=composer)
    assert [type(flowable) for flowable in story] == [InlineParagraph, _Figure, InlineParagraph]
    assert story[0].text == "before"
    assert story[2].text == "after"


def test_a_display_too_wide_is_scaled_down(stylesheet, composer):
    [figure] = markdown_flowables("$$x$$", stylesheet=stylesheet, formulas=composer)
    assert figure.wrap(30, 800) == (30, 15.0)


def test_a_refused_display_is_written_centred(stylesheet, composer):
    [paragraph] = build("$$\\bad$$ (1)", stylesheet, formulas=composer)
    assert "$$\\bad$$ (1)" in paragraph.text
    assert paragraph.style.alignment == 1


# ----------------------------------------------------------------------
# Blocks
# ----------------------------------------------------------------------
def test_inline_markup(stylesheet):
    [paragraph] = build("**b** *i* ~~s~~ `c<d` [l](https://x.org/?a=1&b=2)\nnext  \nline", stylesheet)
    text = paragraph.text
    assert "<b>b</b> <i>i</i> <strike>s</strike>" in text
    assert '<font face="Courier" backColor="#eeeeee">c&lt;d</font>' in text
    assert '<a href="https://x.org/?a=1&amp;b=2" color="#1a5fb4">l</a>' in text
    assert "next<br/>line" in text


def test_headings_take_their_level(stylesheet):
    story = build("# one\n\n### three\n\n###### six", stylesheet)
    assert [flowable.style.fontSize for flowable in story] == [18, 12, 7]


def test_lists_nest_and_number(stylesheet):
    # A list from 3 cannot interrupt a paragraph: the blank line opens it.
    [listing] = build("- a\n- b\n\n  3. c\n  4. d\n- e", stylesheet)
    assert isinstance(listing, ListFlowable)
    assert listing._bulletType == "bullet"
    assert listing._start == "•"
    inner = listing._flowables[1]._flowables[1]
    assert isinstance(inner, ListFlowable)
    assert inner._bulletType == "1"
    assert inner._start == 3
    assert listing._flowables[0]._flowables[0].style.name.startswith("List Item")


def test_the_bullets_follow_the_depth(stylesheet):
    [listing] = build("- a\n  - b\n    - c\n      - d", stylesheet)
    starts = []
    while isinstance(listing, ListFlowable):
        starts.append(listing._start)
        listing = listing._flowables[0]._flowables[-1]
    assert starts == ["•", "–", "◦", "•"]


def test_a_code_block_is_preformatted_and_escaped(stylesheet):
    [code] = build("```python\nif a < b:\n    pass\n```", stylesheet)
    assert isinstance(code, XPreformatted)
    assert code.style.name == "Code"
    code.wrap(400, 800)
    assert len(code.blPara.lines) == 2
    assert "if a < b:" in "".join(fragment.text for fragment in code.frags)


def test_a_rule(stylesheet):
    [rule] = build("---", stylesheet)
    assert isinstance(rule, HRFlowable)


def test_a_quotation_is_indented_and_splits(stylesheet, doc):
    [quote] = build("> " + "\n>\n> ".join(f"Paragraph {i}." for i in range(40)), stylesheet)
    assert isinstance(quote, _Quote)
    assert quote.content[0].style.name == "Quote"
    width, height = quote.wrapOn(doc.canvas, 400, 1e6)
    assert width == 400
    first, rest = quote.splitOn(doc.canvas, 400, height / 2)
    assert len(first.content) + len(rest.content) == 40


def test_a_table_repeats_its_heading_and_fits_the_width(stylesheet):
    rows = "\n".join(f"| {'long text ' * 20} | {i} |" for i in range(3))
    [table] = build(f"| a | b |\n|---|--:|\n{rows}", stylesheet)
    assert isinstance(table, Table)
    assert table.repeatRows == 1
    assert sum(table._colWidths) == pytest.approx(400)
    assert table._colWidths[1] < 30  # a short column keeps its own width
    assert table._cellvalues[0][0].style.fontName == "Helvetica-Bold"
    assert table._cellvalues[1][1].style.alignment == 2  # right


def test_a_narrow_table_keeps_its_natural_widths(stylesheet):
    [table] = build("| a | b |\n|---|---|\n| 1 | 2 |", stylesheet)
    assert sum(table._colWidths) < 100


@pytest.mark.parametrize(
    ("natural", "width", "expected"),
    [
        ([10, 20], 100, [10, 20]),
        ([10, 300, 100], 210, [10, 150, 50]),
        ([300, 100], 200, [100, 100]),
    ],
)
def test_fit(natural, width, expected):
    assert _fit(natural, width) == pytest.approx(expected)


# ----------------------------------------------------------------------
# Images
# ----------------------------------------------------------------------
def test_an_image_alone_is_a_block_no_wider_than_the_text(stylesheet, tmp_path):
    PILImage.new("RGB", (800, 400)).save(tmp_path / "wide.png")
    [figure] = build("![wide](wide.png)", stylesheet, base=tmp_path)
    assert isinstance(figure, _Figure)
    assert figure.natural == (400, 200)


def test_an_image_in_a_sentence_goes_in_the_line(stylesheet, picture):
    [paragraph] = build(f"see ![x]({picture}) here", stylesheet)
    assert 'width="200.000" height="100.000" valign="0.000"' in paragraph.text
    assert paragraph.style.autoLeading == "max"


def test_a_pdf_image_is_drawn_as_a_page(stylesheet, composer, tmp_path):
    [result] = composer([MathFragment("x", True)])
    [figure] = build(f"![x]({result.file})", stylesheet)
    assert figure.pdf


def test_an_image_not_found_writes_its_text(stylesheet, tmp_path):
    problems = []
    text = "![a chart](none.png)\n\n![web](https://x.org/a.png)"
    story = build(text, stylesheet, base=tmp_path, problems=problems)
    assert [flowable.text for flowable in story] == ["[a chart]", "[web]"]
    assert [problem.kind for problem in problems] == ["image", "image"]
    assert "addresses" in problems[1].message


# ----------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------
def test_a_sheet_without_the_markdown_names_falls_back(composer):
    sheet = getSampleStyleSheet()
    text = "> q\n\n- i\n\n| h |\n|---|\n| c |\n\n$$x$$"
    story = markdown_flowables(text, stylesheet=sheet, formulas=composer)
    assert [type(flowable) for flowable in story] == [_Quote, ListFlowable, Table, _Figure]


def test_the_styles_can_be_changed(stylesheet):
    big = ParagraphStyle("Big", fontSize=20, leading=24)
    styles = MarkdownStyles(paragraph=big, code_background=None, link_color="red")
    [paragraph] = build("`c` [l](u)", stylesheet, styles=styles)
    assert paragraph.style.fontSize == 20
    assert "backColor" not in paragraph.text
    assert 'color="#ff0000"' in paragraph.text


# ----------------------------------------------------------------------
# The document
# ----------------------------------------------------------------------
def test_draw_markdown_flows_over_the_pages(out, stylesheet, composer):
    text = "\n\n".join(f"Paragraph {i} with $x_{{{i % 3}}}$." for i in range(120))
    with PDFMaker(out, stylesheet=stylesheet) as doc:
        box = doc.draw_markdown(text, formulas=composer)
        assert doc.page > 1
        assert box.y == pytest.approx(doc.cursor_y)
        assert box.top == pytest.approx(doc.geometry.depth_to_y(doc.cursor.top))
    reader = PdfReader(out)
    assert len(reader.pages) > 1
    # The three formulas are three forms, drawn many times over.
    forms = {name for page in reader.pages for name in page["/Resources"]["/XObject"]}
    assert len(forms) == 3


def test_draw_markdown_on_one_page_returns_its_box(doc):
    top = doc.cursor_y
    box = doc.draw_markdown("# Title\n\nText.")
    assert box.top == pytest.approx(top)
    assert box.y == pytest.approx(doc.cursor_y)
    assert box.width == pytest.approx(doc.content_width)


def test_a_heading_moves_with_its_text(out, stylesheet):
    with PDFMaker(out, stylesheet=stylesheet) as doc:
        doc.advance(doc.remaining_height - 30)
        doc.draw_markdown("## Heading\n\nIts text.")
        assert doc.page == 2


def test_draw_markdown_records_the_problems(doc):
    doc.draw_markdown("![a](nowhere.png)")
    doc.draw_markdown("![b](nowhere.png)")
    assert [problem.source for problem in doc.markdown_problems] == ["![a](nowhere.png)", "![b](nowhere.png)"]


def test_the_story_is_grouped_for_frames(stylesheet):
    from reportlab_layout import keep_with_next

    story = keep_with_next(build("# H\n\ntext\n\nmore", stylesheet))
    assert isinstance(story[0], KeepTogether)


# ----------------------------------------------------------------------
# Classes
# ----------------------------------------------------------------------
GRAY = "#777777"


def colour(style):
    return "#{:02x}{:02x}{:02x}".format(*(round(255 * c) for c in style.textColor.rgb()))


class TestClasses:
    def test_a_block_centres_its_headings_and_paragraphs_not_the_items_of_a_list(self, stylesheet):
        flowables = build("::: {.center .gray}\n# Title\n\nText.\n\n- item\n:::\n\nAfter.", stylesheet)
        heading, paragraph, listing, after = flowables
        assert heading.style.alignment == paragraph.style.alignment == TA_CENTER
        item = listing._flowables[0]._flowables[0]
        assert item.style.alignment != TA_CENTER  # its bullet would stay behind, on the left
        assert colour(item.style) == GRAY
        assert after.style.alignment != TA_CENTER

    def test_the_pandoc_form_gives_several_classes(self, stylesheet):
        [paragraph] = build("::: {.right .gray}\nText.\n:::", stylesheet)
        assert paragraph.style.alignment == TA_RIGHT
        assert colour(paragraph.style) == GRAY

    def test_nested_blocks_add_up(self, stylesheet):
        [paragraph] = build(":::: small\n::: small\nText.\n:::\n::::", stylesheet)
        assert paragraph.style.fontSize == pytest.approx(10 * 0.85 * 0.85)
        assert paragraph.style.leading == pytest.approx(stylesheet["BodyText"].leading * 0.85 * 0.85)

    def test_a_span_greys_and_shrinks_its_words(self, stylesheet):
        [paragraph] = build("one [two]{.gray .small} three", stylesheet)
        assert f'<font color="{GRAY}" size="8.500">two</font>' in paragraph.text
        assert paragraph.style.fontSize == 10

    def test_a_formula_takes_the_size_its_class_gives(self, stylesheet, composer):
        for text in ("::: small\nHence $x$.\n:::", "Hence [$x$]{.small}."):
            [paragraph] = build(text, stylesheet, formulas=composer)
            assert 'width="17.000" height="8.500" valign="-2.550"' in paragraph.text

    def test_a_figure_follows_the_alignment_of_its_block(self, stylesheet, tmp_path):
        PILImage.new("RGB", (40, 20)).save(tmp_path / "dot.png")
        [figure] = build("::: right\n![dot](dot.png)\n:::", stylesheet, base=tmp_path)
        assert isinstance(figure, _Figure)
        figure.wrap(400, 100)
        drawn = []
        figure.canv = type("Spy", (), {"drawImage": lambda self, *args, **kw: drawn.append(args[1])})()
        figure.draw()
        assert drawn == [pytest.approx(360)]

    def test_code_and_tables_take_colour_and_size_but_not_alignment(self, stylesheet):
        code, table = build(
            "::: {.center .small .gray}\n```\ncode\n```\n\n| a |\n|---|\n| b |\n:::", stylesheet
        )
        assert isinstance(code, XPreformatted) and isinstance(table, Table)
        assert code.style.fontSize == pytest.approx(stylesheet["Code"].fontSize * 0.85)
        cell = table._cellvalues[1][0]
        assert cell.style.alignment != TA_CENTER
        assert colour(cell.style) == GRAY

    def test_an_unknown_class_is_reported_and_the_text_set_as_without_it(self, stylesheet):
        problems = []
        [paragraph] = build("::: centre\nText [word]{.grey}.\n:::", stylesheet, problems=problems)
        assert [(p.kind, p.message) for p in problems] == [
            ("class", "no class 'centre'"),
            ("class", "no class 'grey'"),
        ]
        assert paragraph.style.alignment != TA_CENTER
        assert "word" in paragraph.text and "font" not in paragraph.text

    def test_an_alignment_inside_a_line_is_reported(self, stylesheet):
        problems = []
        [paragraph] = build("a [b]{.center} c", stylesheet, problems=problems)
        assert [p.message for p in problems] == ["an alignment, a box or a page break acts on blocks"]
        assert paragraph.style.alignment != TA_CENTER

    def test_names_of_your_own(self, stylesheet):
        styles = MarkdownStyles(
            classes={**MARKDOWN_CLASSES, "gris": MARKDOWN_CLASSES["gray"], "red": MarkdownClass(color="red")}
        )
        [paragraph] = build("[a]{.gris} [b]{.red}", stylesheet, styles=styles)
        assert f'<font color="{GRAY}">a</font>' in paragraph.text
        assert '<font color="#ff0000">b</font>' in paragraph.text

    def test_a_fence_without_a_class_changes_nothing(self, stylesheet):
        problems = []
        [plain] = build("Text.", stylesheet)
        [fenced] = build(":::\nText.\n:::", stylesheet, problems=problems)
        assert fenced.style is plain.style or fenced.style.name == plain.style.name
        assert problems == []

    @pytest.mark.parametrize(
        ("arguments", "message"), [({"alignment": "middle"}, "alignment"), ({"scale": 0}, "scale")]
    )
    def test_a_class_that_cannot_be_is_refused(self, arguments, message):
        with pytest.raises(ValueError, match=message):
            MarkdownClass(**arguments)


class TestMoreClasses:
    def test_every_class_that_comes_defined(self):
        alignments = ["left", "center", "right", "justify"]
        text = ["gray", "red", "green", "blue", "small", "large", "underline", "mark"]
        assert sorted(MARKDOWN_CLASSES) == sorted([*alignments, *text, "box", "newpage"])

    @pytest.mark.parametrize(("name", "alignment"), [("left", TA_LEFT), ("justify", TA_JUSTIFY)])
    def test_the_other_alignments(self, stylesheet, name, alignment):
        [paragraph] = build(f"::: {name}\nText.\n:::", stylesheet)
        assert paragraph.style.alignment == alignment

    @pytest.mark.parametrize(
        ("name", "value"), [("red", "#c62828"), ("green", "#2e7d32"), ("blue", "#1565c0")]
    )
    def test_the_colours_of_a_correction(self, stylesheet, name, value):
        [paragraph] = build(f"[word]{{.{name}}}", stylesheet)
        assert f'<font color="{value}">word</font>' in paragraph.text

    def test_large_is_the_reverse_of_small(self, stylesheet):
        [paragraph] = build("::: large\nText.\n:::", stylesheet)
        assert paragraph.style.fontSize == pytest.approx(12)

    def test_underline_and_mark_in_a_line_and_around_a_block(self, stylesheet):
        [inline] = build("a [b]{.underline} [c]{.mark}", stylesheet)
        assert "<u>b</u>" in inline.text
        assert '<font backColor="#fff176">c</font>' in inline.text
        [block] = build("::: {.underline .mark}\nAll of it.\n:::", stylesheet)
        assert block.text == '<u><font backColor="#fff176">All of it.</font></u>'

    @pytest.mark.parametrize("written", ['[w]{color="#c62828"}', "[w]{color=red}"])
    def test_a_colour_given_once_without_a_class(self, stylesheet, written):
        """In a line, a ``#`` colour is quoted: markdown-it-attrs reads ``{color=#c62828}`` as text."""
        [paragraph] = build(written, stylesheet)
        assert '<font color="#' in paragraph.text and ">w</font>" in paragraph.text

    def test_a_block_takes_a_colour_too(self, stylesheet):
        [paragraph] = build("::: {.right color=#2e7d32}\nText.\n:::", stylesheet)
        assert (paragraph.style.alignment, colour(paragraph.style)) == (TA_RIGHT, "#2e7d32")

    def test_a_colour_or_an_attribute_that_is_not_is_reported(self, stylesheet):
        problems = []
        build("[a]{color=nocolour} [b]{width=3}", stylesheet, problems=problems)
        assert [p.message for p in problems] == ["no colour 'nocolour'", "no attribute 'width'"]

    def test_a_class_with_a_colour_that_is_not_is_refused(self):
        with pytest.raises(ValueError):
            MarkdownClass(color="nocolour")

    def test_a_box_frames_its_blocks(self, stylesheet, out):
        flowables = build("Before.\n\n::: box\nInside, framed.\n:::\n\nAfter.", stylesheet)
        assert [type(f).__name__ for f in flowables] == ["InlineParagraph", "_Box", "InlineParagraph"]
        with PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_markdown("::: box\nInside, framed.\n:::")
        elements = pdf_elements(out)
        [frame] = [e for e in elements if e.kind == "path"]
        glyphs = [e for e in elements if e.kind == "text"]
        assert all(frame.box[0] < g.box[0] and g.box[2] < frame.box[2] for g in glyphs)
        assert all(frame.box[1] < g.box[1] and g.box[3] < frame.box[3] for g in glyphs)

    def test_a_box_taller_than_the_page_splits_and_frames_each_part(self, stylesheet, out):
        text = "::: box\n" + "\n\n".join(f"Paragraph {n}." for n in range(80)) + "\n:::"
        with PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_markdown(text)
        pages = len(PdfReader(out).pages)
        assert pages >= 2
        for index in range(pages):
            assert sum(e.kind == "path" for e in pdf_elements(out, index)) == 1

    def test_newpage_starts_its_block_on_a_new_page_never_a_blank_one(self, stylesheet, out):
        with PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_markdown("::: newpage\nFirst.\n:::\n\nStill first.\n\n::: newpage\n:::\n\nSecond.")
        texts = ["".join(e.text for e in pdf_elements(out, index) if e.kind == "text") for index in range(2)]
        assert len(PdfReader(out).pages) == 2
        assert texts == ["First.Still first.", "Second."]

    def test_newpage_is_the_page_break_a_document_template_knows(self, stylesheet, tmp_path):
        from reportlab.platypus import SimpleDocTemplate

        path = tmp_path / "template.pdf"
        SimpleDocTemplate(str(path)).build(build("One.\n\n::: newpage\nTwo.\n:::", stylesheet))
        assert len(PdfReader(path).pages) == 2

    def test_a_block_class_inside_a_line_is_reported(self, stylesheet):
        problems = []
        build("a [b]{.box} [c]{.newpage}", stylesheet, problems=problems)
        assert len(problems) == 2 and all("acts on blocks" in p.message for p in problems)
