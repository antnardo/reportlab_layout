"""The cursor document: flow, absolute placement, pagination."""

import io
import logging
import re
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, KeepTogether, Paragraph
from reportlab.platypus import paragraph as platypus_paragraph

from conftest import fill_rgb
from reportlab_layout import Box, NumberedCanvas, PDFMaker, TextMetrics, add_style

#: Capitals whose ink runs from the baseline to the cap height and no further,
#: in Helvetica as in Times: no bowl overshooting, no point dipping below the
#: baseline as Times's A, N, V and W do, no punctuation.
FLAT_CAPITALS = "THE FILM KIT HELIX TIME EXIT MYTH ITEM LIFE THEME TILE"

#: The page the capitals are centred on, in points.
PAGE = (250, 120)

#: How far from y the ink may land, in points. The measure is good to 0.06 pt;
#: the rest is the font poppler draws with. Linux has the URW clones, whose
#: Nimbus Sans stands its capitals at 729 thousandths of an em where Helvetica
#: has 718: that lifts the ink by 0.11 pt at 20 pt.
INK_TOLERANCE = 0.2


def read(path):
    return PdfReader(str(path))


def page_text(path, index=0):
    return read(path).pages[index].extract_text()


def baselines(path, index=0):
    """Map each line of text on a page to the canvas ordinate of its baseline.

    pypdf hands the visitor the text matrix and the transformation in force;
    reportlab lays a flowable down by translating the canvas, so both count.
    """
    found = {}

    def record(text, cm, tm, font_dict, font_size):
        if text.strip():
            found[text.strip()] = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]

    read(path).pages[index].extract_text(visitor_text=record)
    return found


def first_and_last_baselines(path):
    """The baselines of the top and bottom lines of text on the first page."""
    found = baselines(path).values()
    return max(found), min(found)


def centre_on_page(path, font, size, leading, valign="cap", **attributes):
    """Centre FLAT_CAPITALS on the middle of PAGE, then return the style's metrics."""
    style = ParagraphStyle(
        "centred", fontName=font, fontSize=size, leading=leading, alignment=TA_CENTER, **attributes
    )
    with PDFMaker(path, pagesize=PAGE, unit=1, left=10, right=10, top=5, bottom=5) as doc:
        doc.draw_paragraph(
            FLAT_CAPITALS,
            style,
            x=doc.x_left,
            y=PAGE[1] / 2,
            width=doc.content_width,
            absolute=True,
            valign=valign,
        )
    return TextMetrics(style)


class TestGeometryExport:
    def test_content_width_matches_the_margins(self, doc):
        assert doc.content_width == pytest.approx(doc.width - 30 * mm)

    def test_landscape_is_wider_than_tall(self, out, stylesheet):
        doc = PDFMaker(out, landscape=True, stylesheet=stylesheet)
        assert doc.width > doc.height

    def test_named_pagesize_is_accepted(self, out, stylesheet):
        assert (
            PDFMaker(out, pagesize="A5", stylesheet=stylesheet).width
            < PDFMaker(out, pagesize="A4", stylesheet=stylesheet).width
        )

    def test_exported_attributes_stay_writable(self, doc):
        """Subclasses recompute y_top as they go: that has to stay possible."""
        doc.y_top = 123
        assert doc.y_top == 123


class TestFlow:
    def test_cursor_starts_at_the_top_margin(self, doc):
        assert doc.cursor.depth == pytest.approx(doc.top)

    def test_paragraph_moves_the_cursor_down(self, doc):
        before = doc.cursor.depth
        doc.draw_paragraph("Hello")
        assert doc.cursor.depth > before

    def test_successive_paragraphs_stack_downwards(self, doc):
        first = doc.draw_paragraph("First")
        second = doc.draw_paragraph("Second")
        assert second.y < first.y

    def test_add_space_advances_by_the_font_size(self, doc):
        before = doc.cursor.depth
        doc.add_space(2)
        assert doc.cursor.depth - before == pytest.approx(2 * doc.font_size)

    def test_explicit_depth_leaves_the_cursor_alone(self, doc):
        before = doc.cursor.depth
        doc.draw_paragraph("Anchored", y=100)
        assert doc.cursor.depth == before

    def test_draw_returns_a_box(self, doc):
        assert isinstance(doc.draw_paragraph("Hello"), Box)

    def test_box_unpacks_as_four_numbers(self, doc):
        _x, _y, width, height = doc.draw_paragraph("Hello")
        assert width > 0 and height > 0

    def test_halign_right_pushes_a_narrow_block_to_the_margin(self, doc):
        left = doc.draw_paragraph("Hello", wscale=0.5)
        right = doc.draw_paragraph("Hello", wscale=0.5, halign="right")
        assert right.x - left.x == pytest.approx(doc.content_width / 2)

    def test_unknown_halign_is_rejected(self, doc):
        with pytest.raises(ValueError, match="halign"):
            doc.draw_paragraph("Hello", halign="middle")


class TestAbsolutePlacement:
    def test_absolute_coordinates_are_points(self, doc):
        box = doc.draw_paragraph("Hello", x=100, y=200, width=200, absolute=True)
        assert (box.x, box.y) == pytest.approx((100, 200))

    def test_valign_top_puts_the_top_edge_on_y(self, doc):
        box = doc.draw_paragraph("Hello", x=100, y=200, width=200, absolute=True, valign="top")
        assert box.top == pytest.approx(200)

    def test_valign_middle_centres_the_block(self, doc):
        box = doc.draw_paragraph("Hello", x=100, y=200, width=200, absolute=True, valign="middle")
        assert box.center[1] == pytest.approx(200)

    def test_absolute_without_coordinates_is_rejected(self, doc):
        with pytest.raises(ValueError, match="explicit x and y"):
            doc.draw_paragraph("Hello", absolute=True)

    def test_unknown_valign_is_rejected(self, doc):
        """1.3.0 let a KeyError through instead."""
        with pytest.raises(ValueError, match="valign must be"):
            doc.draw_paragraph("Hello", x=100, y=200, width=200, absolute=True, valign="center")

    @pytest.mark.parametrize(("halign", "share"), [("left", 0), ("center", 0.5), ("right", 1)])
    def test_halign_puts_that_point_of_the_element_on_x(self, doc, halign, share):
        """1.5.0 left the left edge on x whatever halign said."""
        box = doc.draw_table(
            [["Name", "Mark"]], col_widths=[120, 60], x=306, y=400, absolute=True, halign=halign
        )
        assert box.x + share * box.width == pytest.approx(306)

    def test_left_keeps_x_as_it_was_given(self, doc):
        """The Box a reader prints shows x=10, as it did before halign counted here."""
        box = doc.draw_table([["a"]], col_widths=[30], x=10, y=100, absolute=True, valign="top")
        assert repr(box).startswith("Box(x=10, ")

    def test_halign_centres_a_paragraph_block_on_x(self, doc):
        box = doc.draw_paragraph("Hello", x=300, y=200, width=200, absolute=True, halign="center")
        assert box.x == pytest.approx(200)

    def test_unknown_halign_is_rejected_here_too(self, doc):
        """1.5.0 only refused it in flow."""
        with pytest.raises(ValueError, match="halign must be"):
            doc.draw_table([["a", "b"]], x=306, y=400, absolute=True, halign="sideways")

    @pytest.mark.ink
    @pytest.mark.parametrize(("halign", "share"), [("left", 0), ("center", 0.5), ("right", 1)])
    def test_ink_of_a_table_lands_where_halign_says(self, out, ink, halign, share):
        rule = 1
        with PDFMaker(out, pagesize=PAGE, unit=1, left=10, right=10, top=5, bottom=5) as doc:
            doc.draw_table(
                [["A", "B"]],
                col_widths=[60, 30],
                row_heights=40,
                style=[("GRID", (0, 0), (-1, -1), rule, "black")],
                x=PAGE[0] / 2,
                y=PAGE[1] / 2,
                absolute=True,
                halign=halign,
                valign="middle",
            )
        measured = ink(out)
        # The rules stick out of the table by half their width on either side.
        expected = PAGE[0] / 2 + (share - 0.5) * rule
        assert measured.left + share * (measured.right - measured.left) == pytest.approx(
            expected, abs=INK_TOLERANCE
        )


class TestOffThePage:
    """An element laid past an edge of the page is logged: a viewer shows nothing of that part."""

    def test_table_running_off_the_bottom_is_logged(self, out, stylesheet, caplog):
        """30 rows hung from y = 100: 25 of them went under the page without a word."""
        doc = PDFMaker(out, pagesize="letter", stylesheet=stylesheet)
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.draw_table(
                [["Name", "Mark"]] * 30, col_widths=[120, 60], x=10, y=100, absolute=True, valign="top"
            )
        assert "Table runs off page 1: 440.0 pt past its bottom edge" in caplog.text

    @pytest.mark.parametrize(("x", "y", "edge"), [(-5, 300, "left"), (560, 300, "right"), (100, 830, "top")])
    def test_every_edge_is_watched(self, doc, caplog, x, y, edge):
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.draw_table([["a", "b"]], col_widths=[30, 30], x=x, y=y, absolute=True)
        assert f"past its {edge} edge" in caplog.text

    def test_flow_without_page_breaks_is_watched_too(self, doc, caplog):
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.draw_table([["Name", "Mark"]] * 60)
        assert "past its bottom edge" in caplog.text

    def test_element_up_against_the_edges_logs_nothing(self, doc, caplog):
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.draw_table([["a"]], col_widths=doc.width, row_heights=doc.height, x=0, y=0, absolute=True)
        assert caplog.records == []


#: Set solid, at the usual 1.2, looser, tighter, over three lines, and in Times.
CAP_STYLES = [
    pytest.param("Helvetica", 15, 15, id="solid"),
    pytest.param("Helvetica", 10, 12, id="normal"),
    pytest.param("Helvetica", 12, 18, id="loose"),
    pytest.param("Helvetica", 11, 9, id="tight"),
    pytest.param("Helvetica-Bold", 20, 22, id="three-lines"),
    pytest.param("Times-Roman", 14, 14, id="times-solid"),
    pytest.param("Times-Roman", 12, 16, id="times-loose"),
]


class TestCapAnchor:
    """valign="cap" on a paragraph: the middle of its capitals on y, not the middle of its block."""

    @pytest.mark.parametrize(("font", "size", "leading"), CAP_STYLES)
    def test_capitals_straddle_y_whatever_the_leading(self, out, font, size, leading):
        metrics = centre_on_page(out, font, size, leading)
        first, last = first_and_last_baselines(out)
        assert (first + metrics.cap_height + last) / 2 == pytest.approx(PAGE[1] / 2, abs=0.01)

    @pytest.mark.ink
    @pytest.mark.parametrize(("font", "size", "leading"), CAP_STYLES)
    def test_ink_is_centred_on_y_whatever_the_leading(self, out, ink, font, size, leading):
        centre_on_page(out, font, size, leading)
        measured = ink(out)
        assert (measured.bottom + measured.top) / 2 == pytest.approx(PAGE[1] / 2, abs=INK_TOLERANCE)

    @pytest.mark.ink
    def test_middle_leaves_capitals_set_solid_low(self, out, ink):
        """The flaw "cap" corrects: reportlab keeps a whole type size above the first baseline."""
        metrics = centre_on_page(out, "Helvetica", 15, 15, valign="middle")
        measured = ink(out)
        sink = (metrics.font_size - metrics.cap_height) / 2
        assert (measured.bottom + measured.top) / 2 == pytest.approx(PAGE[1] / 2 - sink, abs=INK_TOLERANCE)

    def test_one_line_shares_the_baseline_of_draw_string(self, out, stylesheet):
        """A one-line title and a label anchored the same way line up."""
        with PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("TITLE", "Heading2", x=100, y=400, width=200, absolute=True, valign="cap")
            doc.draw_string("LABEL", 400, 400, style="Heading2", valign="cap")
        lines = baselines(out)
        assert lines["TITLE"] == pytest.approx(lines["LABEL"], abs=0.01)

    @pytest.mark.parametrize("auto_leading,leading", [("max", 9), ("min", 20)])
    def test_auto_leading_pitch_is_followed(self, out, auto_leading, leading):
        """autoLeading spaces the lines by the font's height, not by the style's leading."""
        metrics = centre_on_page(out, "Helvetica", 15, leading, autoLeading=auto_leading)
        first, last = first_and_last_baselines(out)
        assert (first + metrics.cap_height + last) / 2 == pytest.approx(PAGE[1] / 2, abs=0.01)

    @pytest.mark.parametrize("drop_by_size", [0, 1])
    def test_first_line_drop_setting_is_followed(self, out, monkeypatch, drop_by_size):
        """Switched off, paraFontSizeHeightOffset drops the first line by the ascent instead."""
        monkeypatch.setattr(platypus_paragraph, "paraFontSizeHeightOffset", drop_by_size)
        metrics = centre_on_page(out, "Times-Roman", 14, 14)
        first, last = first_and_last_baselines(out)
        assert (first + metrics.cap_height + last) / 2 == pytest.approx(PAGE[1] / 2, abs=0.01)

    def test_empty_paragraph_lands_on_y(self, doc):
        box = doc.draw_paragraph("", x=100, y=200, width=200, absolute=True, valign="cap")
        assert box.y == pytest.approx(200)

    def test_table_is_refused(self, doc):
        with pytest.raises(ValueError, match="needs a Paragraph, and Table is not one"):
            doc.draw_table([["a", "b"]], x=100, y=200, absolute=True, valign="cap")

    def test_image_is_refused(self, doc, picture):
        with pytest.raises(ValueError, match="needs a Paragraph, and Image is not one"):
            doc.draw_image(picture, width=80, x=100, y=200, absolute=True, valign="cap")


class TestPagination:
    def test_new_page_resets_the_cursor(self, doc):
        doc.draw_paragraph("Hello")
        doc.new_page()
        assert doc.cursor.depth == pytest.approx(doc.top)

    def test_new_page_increments_the_counter(self, doc):
        doc.new_page()
        assert doc.page == 2

    def test_auto_page_break_starts_a_second_page(self, out, stylesheet):
        doc = PDFMaker(out, auto_page_break=True, stylesheet=stylesheet)
        for _ in range(80):
            doc.draw_paragraph("One line among many others.")
        doc.save()
        assert len(read(out).pages) > 1

    def test_page_break_false_keeps_everything_on_one_page(self, out, stylesheet):
        doc = PDFMaker(out, auto_page_break=True, stylesheet=stylesheet)
        for _ in range(80):
            doc.draw_paragraph("One line among many others.", page_break=False)
        doc.save()
        assert len(read(out).pages) == 1


def marks(count):
    """A heading row, then count - 1 rows of one line each: 18 pt a row."""
    return [["Name", "Mark"]] + [[f"Student {n}", str(n % 20)] for n in range(1, count)]


def students(path):
    """The numbers of the students on each page, in the order drawn."""
    return [[int(n) for n in re.findall(r"Student (\d+)", page.extract_text())] for page in read(path).pages]


def text_baselines(path, index=0):
    """Every line of text on a page and its baseline, repeated lines included."""
    found = []

    def record(text, cm, tm, font_dict, font_size):
        if text.strip():
            found.append((text.strip(), tm[4] * cm[1] + tm[5] * cm[3] + cm[5]))

    read(path).pages[index].extract_text(visitor_text=record)
    return found


#: How far past the content area the ink of a table split over pages may reach,
#: in points: half its 0.5 pt rules, and a pixel at 300 dpi.
SPLIT_INK_TOLERANCE = 0.25 + 72 / 300


class TestTooTallForAPage:
    """In flow, with page breaks on, a block no page can hold is split rather than moved.

    Up to 1.5.0 it went to a new page even from the top of an empty one, which
    left that page blank, then ran off the bottom of the next without a word.
    """

    def test_table_starts_on_the_first_page_and_loses_no_row(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.draw_table(marks(60))  # 1080 pt, for 757 pt of content on A4
        found = students(out)
        assert len(found) == 2 and found[0][0] == 1
        assert [n for page in found for n in page] == list(range(1, 60))

    @pytest.mark.ink
    def test_ink_of_every_part_stays_in_the_content_area(self, out, stylesheet, ink):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.draw_table(marks(60), style=[("GRID", (0, 0), (-1, -1), 0.5, "black")])
        for page in (1, 2):
            measured = ink(out, page=page, dpi=300)
            assert measured.bottom >= doc.y_bottom - SPLIT_INK_TOLERANCE
            assert measured.top <= doc.y_top + SPLIT_INK_TOLERANCE

    def test_heading_rows_open_every_part(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.draw_table(marks(60), repeat_rows=1)
        assert [page.extract_text().split()[:2] for page in read(out).pages] == [["Name", "Mark"]] * 2

    def test_first_part_fills_what_is_left_of_the_page(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("INTRODUCTION")
            doc.draw_table(marks(60))
        found = students(out)
        assert found[0][0] == 1 and "INTRODUCTION" in page_text(out, 0)

    def test_block_that_fits_a_page_still_moves_whole(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.advance(doc.remaining_height / 2)
            doc.draw_table(marks(30))  # 540 pt: a page holds it, what is left of this one does not
        assert students(out) == [[], list(range(1, 30))]

    def test_paragraph_loses_no_word_and_keeps_off_the_footer(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.set_footer(doc.make_paragraph("FOOTER"))
            doc.draw_paragraph("word " * 1500)
        pages = [page.extract_text().split() for page in read(out).pages]
        assert sum(page.count("word") for page in pages) == 1500
        assert all(page.count("FOOTER") == 1 for page in pages)
        for index in range(len(pages)):
            lowest = min(y for text, y in text_baselines(out, index) if text.startswith("word"))
            assert lowest > doc.y_bottom

    def test_cursor_carries_on_under_the_last_part(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            last = doc.draw_table(marks(60))
            after = doc.draw_paragraph("AFTER THE TABLE")
        assert doc.page == 2 and last.top == pytest.approx(doc.y_top)
        assert after.top == pytest.approx(last.y)
        assert "AFTER THE TABLE" in page_text(out, 1)

    def test_what_cannot_split_goes_at_the_top_and_is_logged(self, out, stylesheet, picture, caplog):
        doc = PDFMaker(out, auto_page_break=True, stylesheet=stylesheet)
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            box = doc.draw_image(picture, width=100, height=900)
        doc.save()
        assert len(read(out).pages) == 1 and box.top == pytest.approx(doc.y_top)
        assert "Image is 900.0 pt tall and cannot split" in caplog.text

    def test_what_cannot_split_leaves_a_started_page(self, out, stylesheet, picture, caplog):
        doc = PDFMaker(out, auto_page_break=True, stylesheet=stylesheet)
        doc.draw_paragraph("INTRODUCTION")
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            box = doc.draw_image(picture, width=100, height=900)
        doc.save()
        assert doc.page == 2 and box.top == pytest.approx(doc.y_top)
        assert "INTRODUCTION" in page_text(out, 0) and "cannot split" in caplog.text

    def test_without_page_breaks_the_block_stays_whole(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            box = doc.draw_table(marks(60), page_break=False)
        assert len(read(out).pages) == 1 and box.height == pytest.approx(60 * 18)


BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=12)


def group(*texts):
    return KeepTogether([Paragraph(text, BODY) for text in texts])


class Marker(Flowable):
    """A flowable of a fixed size that records where on the page it was drawn."""

    def __init__(self, width, height, align="LEFT"):
        super().__init__()
        self.width, self.height, self.hAlign = width, height, align
        self.drawn_at = None

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        self.drawn_at = self.canv.absolutePosition(0, 0)


class TestKeepTogether:
    """draw() lays a KeepTogether as the block its flowables make.

    reportlab's own reports 16777215 pt, for a frame to split it, and has
    nothing to draw: 1.5.0 raised AttributeError on it, whatever the mode.
    """

    def test_flowables_are_stacked_in_one_box(self, doc, out):
        start = doc.cursor.depth
        box = doc.draw(group("ALPHA", "BRAVO"))
        doc.save()
        found = baselines(out)
        assert box.height == pytest.approx(24) and doc.cursor.depth == pytest.approx(start + 24)
        assert (found["ALPHA"], found["BRAVO"]) == pytest.approx((box.top - 10, box.top - 22))

    @pytest.mark.parametrize("page_break", [False, True])
    def test_group_of_one_paragraph_is_drawn(self, out, stylesheet, page_break):
        with PDFMaker(out, auto_page_break=page_break, stylesheet=stylesheet) as doc:
            doc.draw(group("ALONE"))
        assert len(read(out).pages) == 1 and page_text(out).split() == ["ALONE"]

    def test_group_a_page_can_hold_moves_to_the_next_one_whole(self, out, stylesheet):
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.advance(doc.remaining_height - 15)  # room for one line, not two
            doc.draw(group("ALPHA", "BRAVO"))
        assert page_text(out, 0).split() == [] and page_text(out, 1).split() == ["ALPHA", "BRAVO"]

    @pytest.mark.parametrize("after", [[], ["AFTER"]])
    def test_group_no_page_can_hold_flows_over_the_pages(self, out, stylesheet, after):
        # Its first flowable is taller than a page: it starts under INTRODUCTION, as it would alone.
        words = [f"word{n}" for n in range(1500)]
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("INTRODUCTION")
            doc.draw(group(" ".join(words), *after))
        pages = [text_baselines(out, index) for index in range(len(read(out).pages))]
        found = [word for page in pages for text, _ in page for word in text.split()]
        assert found == ["INTRODUCTION", *words, *after] and "word0" in page_text(out, 0)
        assert all(y > doc.y_bottom for page in pages for _, y in page)

    def test_absolute_group_is_placed_by_its_box(self, doc, out):
        box = doc.draw(
            group("ALPHA", "BRAVO"), x=300, y=500, width=200, absolute=True, halign="center", valign="top"
        )
        doc.save()
        assert (box.x + box.width / 2, box.top) == pytest.approx((300, 500))
        assert baselines(out)["ALPHA"] == pytest.approx(490)

    def test_cap_is_refused_in_the_name_of_the_group(self, doc):
        with pytest.raises(ValueError, match="needs a Paragraph, and KeepTogether is not one"):
            doc.draw(group("ALPHA"), x=100, y=100, absolute=True, valign="cap")

    def test_narrower_flowable_is_placed_by_its_own_halign(self, doc):
        wide, narrow = Marker(400, 20), Marker(100, 20, align="CENTER")
        box = doc.draw(KeepTogether([wide, narrow]))
        assert (box.width, box.height) == (400, 40)
        assert wide.drawn_at == pytest.approx((box.x, box.y + 20))
        assert narrow.drawn_at == pytest.approx((box.x + 150, box.y))

    def test_groups_nested_in_it_are_opened(self, doc, out):
        # The outer group counts the inner one at 16777215 pt: packed as they come, it lost them.
        box = doc.draw(KeepTogether([Paragraph("ALPHA", BODY), KeepTogether([group("BRAVO", "CHARLIE")])]))
        doc.save()
        assert box.height == pytest.approx(36) and page_text(out).split() == ["ALPHA", "BRAVO", "CHARLIE"]

    def test_empty_group_draws_nothing(self, doc):
        start = doc.cursor.depth
        box = doc.draw(KeepTogether([]))
        assert box.height == 0 and doc.cursor.depth == start

    def test_space_around_it_is_that_of_its_first_and_last_flowables(self, doc):
        spaced = ParagraphStyle("spaced", parent=BODY, spaceBefore=6, spaceAfter=8)
        top, start = doc.cursor_y, doc.cursor.depth
        box = doc.draw(KeepTogether([Paragraph("ALPHA", spaced), Paragraph("BRAVO", spaced)]))
        assert (box.top, box.height) == pytest.approx((top - 6, 12 + 8 + 6 + 12))
        assert doc.cursor.depth == pytest.approx(start + 6 + box.height + 8)

    def test_flowable_taller_than_a_page_kept_with_the_next_overflows_alone(self, out, stylesheet, caplog):
        # keepWithNext binds the two again when the group is split over the pages.
        tall = Marker(100, 900)
        tall.keepWithNext = 1
        with (
            caplog.at_level(logging.WARNING),
            PDFMaker(out, auto_page_break=True, stylesheet=stylesheet) as doc,
        ):
            doc.draw(KeepTogether([tall, Paragraph("CAPTION", BODY)]))
        assert "Marker is 900.0 pt tall and cannot split" in caplog.text
        assert page_text(out, 1).split() == ["CAPTION"]


class TestHeaderFooter:
    @pytest.mark.parametrize("setter", ["set_header", "set_footer"])
    def test_band_is_repeated_on_every_page(self, out, stylesheet, setter):
        doc = PDFMaker(out, stylesheet=stylesheet)
        getattr(doc, setter)(doc.make_paragraph("Band text"))
        doc.draw_paragraph("Page one")
        doc.new_page()
        doc.draw_paragraph("Page two")
        doc.save()
        assert "Band text" in page_text(out, 0)
        assert "Band text" in page_text(out, 1)

    def test_footer_accepts_several_flowables(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer([doc.make_paragraph("Left"), doc.make_paragraph("Right side")])
        doc.save()
        text = page_text(out)
        assert "Left" in text and "Right side" in text

    @pytest.mark.parametrize("setter", ["set_header", "set_footer"])
    def test_drawing_the_band_leaves_the_cursor_alone(self, doc, setter):
        getattr(doc, setter)(doc.make_paragraph("Band"))
        before = doc.cursor.depth
        doc.draw_header_footer()
        assert doc.cursor.depth == before

    def test_header_stands_right_above_the_first_block(self, out, stylesheet):
        """1.2.0 hung the header from the line the cursor starts on: both overprinted."""
        doc = PDFMaker(out, top=25, stylesheet=stylesheet)
        doc.set_header(doc.make_paragraph("HEADER TEXT"))
        first = doc.draw_paragraph("FIRST BLOCK")
        doc.save()
        lines = baselines(out)
        expected = first.height + overhang(doc.metrics())
        assert lines["HEADER TEXT"] - lines["FIRST BLOCK"] == pytest.approx(expected)

    def test_header_lies_in_the_top_margin(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_header(doc.make_paragraph("HEADER TEXT"))
        doc.save()
        assert doc.y_top < baselines(out)["HEADER TEXT"] < doc.height

    def test_footer_lies_in_the_bottom_margin(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer(doc.make_paragraph("FOOTER TEXT"))
        doc.save()
        assert 0 < baselines(out)["FOOTER TEXT"] < doc.y_bottom

    def test_header_space_after_widens_the_gap(self, out, stylesheet):
        add_style(stylesheet, "Header", spaceAfter=6)
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_header(doc.make_paragraph("HEADER TEXT", "Header"))
        first = doc.draw_paragraph("FIRST BLOCK")
        doc.save()
        lines = baselines(out)
        expected = first.height + overhang(doc.metrics("Header")) + 6
        assert lines["HEADER TEXT"] - lines["FIRST BLOCK"] == pytest.approx(expected)

    def test_header_taller_than_the_top_margin_is_logged(self, out, stylesheet, picture, caplog):
        doc = PDFMaker(out, top=10, stylesheet=stylesheet)
        doc.set_header(doc.make_image(picture, height=40))
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.save()
        assert "Header taller than the top margin" in caplog.text

    def test_footer_taller_than_the_bottom_margin_is_logged(self, out, stylesheet, picture, caplog):
        doc = PDFMaker(out, bottom=10, stylesheet=stylesheet)
        doc.set_footer(doc.make_image(picture, height=40))
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.save()
        assert "Footer taller than the bottom margin" in caplog.text

    def test_band_too_tall_is_logged_once_however_many_pages(self, out, stylesheet, picture, caplog):
        """1.5.0 said it again on every page."""
        doc = PDFMaker(out, top=10, stylesheet=stylesheet)
        doc.set_header(doc.make_image(picture, height=40))
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            for _ in range(3):
                doc.new_page()
            doc.save()
        assert len(read(out).pages) == 4
        assert [record.getMessage() for record in caplog.records] == [
            "Header taller than the top margin: 11.7 pt off the page"
        ]

    def test_bands_that_fit_their_margins_log_nothing(self, out, stylesheet, caplog):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_header(doc.make_paragraph("HEADER TEXT"))
        doc.set_footer(doc.make_paragraph("FOOTER TEXT"))
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.save()
        assert caplog.records == []


def overhang(metrics):
    """How far a paragraph's descenders reach below its block, where reportlab leaves leading - size."""
    return max(0.0, -metrics.descent - (metrics.leading - metrics.font_size))


#: Header styles as (font, size, leading): the usual 1.2, set solid, and loose.
HEADER_STYLES = [
    pytest.param("Helvetica", 10, 12, id="normal"),
    pytest.param("Helvetica", 12, 12, id="solid-12"),
    pytest.param("Helvetica-Bold", 16, 16, id="solid-16"),
    pytest.param("Helvetica-Bold", 24, 24, id="solid-24"),
    pytest.param("Times-Roman", 14, 14, id="times-solid"),
    pytest.param("Helvetica", 14, 18, id="loose"),
]

#: How far below the declared descent the glyphs a viewer draws may reach, as a
#: fraction of the type size: Apple's Helvetica draws its g 1.4% lower.
GLYPH_OVERSHOOT = 0.02


class TestHeaderDescenders:
    """A paragraph in the header keeps its descenders, not just its block, out of the content area.

    1.3.0 to 1.5.0 stood the block on the edge. reportlab leaves only
    leading - size under the last baseline, so the descenders reached below
    it: over the top rule of a table laid first, by 3.3 pt set solid at 16/16.
    """

    @pytest.mark.parametrize(("font", "size", "leading"), HEADER_STYLES)
    @pytest.mark.parametrize("space_after", [0, 6])
    def test_header_is_as_low_as_its_block_and_descenders_allow(
        self, out, stylesheet, font, size, leading, space_after
    ):
        style = ParagraphStyle("band", fontName=font, fontSize=size, leading=leading, spaceAfter=space_after)
        doc = PDFMaker(out, top=30, stylesheet=stylesheet)
        doc.set_header(doc.make_paragraph("Quarterly gypsy report", style))
        doc.save()
        baseline = baselines(out)["Quarterly gypsy report"]
        descent_line = baseline + TextMetrics(style).descent
        block_bottom = baseline - (leading - size)
        floor = doc.y_top + space_after
        assert descent_line >= floor - 1e-9 and block_bottom >= floor - 1e-9
        assert min(descent_line, block_bottom) == pytest.approx(floor)

    @pytest.mark.ink
    @pytest.mark.parametrize("size", [16, 24])
    def test_ink_of_a_header_set_solid_stays_in_the_margin(self, out, stylesheet, ink, size):
        style = ParagraphStyle("band", fontName="Helvetica-Bold", fontSize=size, leading=size)
        geometry = {"unit": 1, "left": 10, "right": 10, "top": 40, "bottom": 5}
        with PDFMaker(out, pagesize=(200, 100), stylesheet=stylesheet, **geometry) as doc:
            doc.set_header(doc.make_paragraph("gypsy", style))
        assert ink(out).bottom >= doc.y_top - GLYPH_OVERSHOOT * size

    def test_header_paragraphs_share_their_last_baseline(self, out, stylesheet):
        """A heading 14/18 beside a 10/12 line sat 2 pt above it: each block stood on the edge."""
        left = ParagraphStyle("left", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceAfter=6)
        right = ParagraphStyle("right", fontSize=10, leading=12, alignment=TA_RIGHT, spaceAfter=6)
        doc = PDFMaker(out, top=25, stylesheet=stylesheet)
        doc.set_header(
            [
                doc.make_paragraph("Acme Ltd", left),
                doc.make_paragraph("Quarterly report<br/>September 2026", right),
            ]
        )
        doc.save()
        lines = baselines(out)
        assert lines["Acme Ltd"] == pytest.approx(lines["September 2026"])
        assert lines["Acme Ltd"] - (18 - 14) == pytest.approx(doc.y_top + 6)

    def test_footer_paragraphs_share_their_first_baseline(self, out, stylesheet):
        left = ParagraphStyle("left", fontName="Helvetica-Bold", fontSize=14, leading=18)
        right = ParagraphStyle("right", fontSize=10, leading=12, alignment=TA_RIGHT)
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer([doc.make_paragraph("Acme Ltd", left), doc.make_paragraph("Page 3<br/>of 12", right)])
        doc.save()
        lines = baselines(out)
        assert lines["Page 3"] == pytest.approx(lines["Acme Ltd"])
        assert lines["Acme Ltd"] == pytest.approx(doc.y_bottom - 14)

    def test_lone_footer_hangs_where_it_did(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer(doc.make_paragraph("FOOTER TEXT"))
        doc.save()
        assert baselines(out)["FOOTER TEXT"] == pytest.approx(doc.y_bottom - doc.metrics().font_size)


class TestTables:
    def test_default_columns_split_the_content_width(self, doc):
        box = doc.draw_table([["a", "b", "c"], ["1", "2", "3"]])
        assert box.width == pytest.approx(doc.content_width)

    def test_scalar_column_width_applies_to_every_column(self, doc):
        box = doc.draw_table([["a", "b"]], col_widths=60)
        assert box.width == pytest.approx(120)

    def test_extra_style_commands_are_applied(self, doc):
        """A plain list of commands has to be accepted as it comes."""
        doc.draw_table(
            [["a", "b"]],
            style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.5, "black")],
        )
        doc.save()
        assert read(doc.canvas._filename).pages

    def test_empty_table_is_rejected(self, doc):
        with pytest.raises(ValueError, match="at least one non-empty row"):
            doc.draw_table([])


class TestImages:
    def test_image_keeps_its_aspect_ratio(self, doc, picture):
        box = doc.draw_image(picture, width=80)
        assert box.height == pytest.approx(40)


class TestDirectDrawing:
    def test_draw_string_centres_at_any_scale(self, doc):
        box = doc.draw_string("Title", 300, 400, halign="center", valign="middle", scale=0.6)
        assert box.center == pytest.approx((300, 400))

    def test_apply_style_arms_the_canvas_font(self, doc):
        metrics = doc.apply_style("Small", scale=2)
        assert doc.canvas._fontsize == pytest.approx(metrics.font_size)

    def test_rect_and_round_rect_return_their_box(self, doc):
        assert tuple(doc.draw_rect(0, 0, 10, 20)) == pytest.approx((0, 0, 10, 20))
        assert tuple(doc.draw_round_rect(0, 0, 10, 20)) == pytest.approx((0, 0, 10, 20))

    def test_centered_line_spans_the_content_width(self, doc):
        box = doc.draw_centered_line(y=50)
        assert box.width == pytest.approx(doc.content_width)

    def test_centered_line_can_be_narrowed(self, doc):
        box = doc.draw_centered_line(y=50, wscale=0.5)
        assert box.width == pytest.approx(doc.content_width / 2)


class TestFrames:
    def test_frame_paragraph_lands_in_the_pdf(self, doc):
        doc.new_frame(height=60)
        doc.frame_paragraph("Inside the frame")
        doc.save()
        assert "Inside the frame" in page_text(doc.canvas._filename)

    def test_overflow_is_reported_not_swallowed(self, doc):
        doc.new_frame(height=12)
        leftover = doc.draw_frame([doc.make_paragraph("Hello " * 200)])
        assert leftover

    def test_frame_before_new_frame_is_rejected(self, doc):
        with pytest.raises(RuntimeError, match="No active frame"):
            doc.frame_space()


class TestLifecycle:
    def test_context_manager_writes_the_file(self, out, stylesheet):
        with PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
        assert "Hello" in page_text(out)

    def test_context_manager_does_not_write_on_error(self, out, stylesheet):
        with pytest.raises(RuntimeError), PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
            raise RuntimeError("boom")
        assert not out.exists()

    def test_metadata_reaches_the_pdf(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_metadata(author="A. Marchand", title="Test")
        doc.draw_paragraph("Hello")
        doc.save()
        assert read(out).metadata.author == "A. Marchand"


class TestOutput:
    """Where the PDF goes: a path, or a file object as a web view needs."""

    @pytest.mark.parametrize("as_path", [str, Path])
    def test_path_is_written_whether_str_or_pathlike(self, out, stylesheet, as_path):
        with PDFMaker(as_path(out), stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
        assert "Hello" in page_text(out)

    def test_bytesio_receives_the_pdf(self, stylesheet):
        buffer = io.BytesIO()
        with PDFMaker(buffer, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
        assert buffer.getvalue().startswith(b"%PDF-")

    def test_bytesio_is_not_turned_into_a_file_name(self, tmp_path, monkeypatch, stylesheet):
        """1.2.0 wrote a file called `<_io.BytesIO object at 0x...>` instead."""
        monkeypatch.chdir(tmp_path)
        with PDFMaker(io.BytesIO(), stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
        assert list(tmp_path.iterdir()) == []

    def test_bytesio_is_left_open_for_the_caller(self, stylesheet):
        buffer = io.BytesIO()
        with PDFMaker(buffer, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
        assert not buffer.closed

    def test_bytesio_reads_back_as_the_document(self, stylesheet):
        buffer = io.BytesIO()
        with PDFMaker(buffer, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
        buffer.seek(0)
        assert "Hello" in PdfReader(buffer).pages[0].extract_text()

    def test_nothing_reaches_the_buffer_before_save(self, stylesheet):
        buffer = io.BytesIO()
        doc = PDFMaker(buffer, stylesheet=stylesheet)
        doc.draw_paragraph("Hello")
        assert buffer.getvalue() == b""

    def test_file_opened_in_binary_mode_is_left_open(self, out, stylesheet):
        with out.open("wb") as handle:
            with PDFMaker(handle, stylesheet=stylesheet) as doc:
                doc.draw_paragraph("Hello")
            assert not handle.closed
        assert "Hello" in page_text(out)

    def test_any_object_with_a_write_method_is_accepted(self, stylesheet):
        """All a Django HttpResponse offers of a file is write()."""

        class Sink:
            def __init__(self):
                self.chunks = []

            def write(self, data):
                self.chunks.append(data)

        sink = Sink()
        with PDFMaker(sink, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Hello")
        assert b"".join(sink.chunks).startswith(b"%PDF-")

    @pytest.mark.parametrize("output", [None, 42, b"output.pdf"])
    def test_neither_path_nor_file_is_rejected_at_once(self, stylesheet, output):
        with pytest.raises(TypeError, match="path or a binary file object"):
            PDFMaker(output, stylesheet=stylesheet)


class TestCanvas:
    """The canvas a document draws on: built by canvasmaker, or replaced afterwards."""

    def test_canvasmaker_numbers_the_pages(self, out, stylesheet):
        """PDFMaker used to build its own canvas: NumberedCanvas only served SimpleDocTemplate."""
        with PDFMaker(out, auto_page_break=True, stylesheet=stylesheet, canvasmaker=NumberedCanvas) as doc:
            for n in range(150):
                doc.draw_paragraph(f"Line {n}")
        texts = [page.extract_text() for page in read(out).pages]
        total = len(texts)
        assert total > 1 and "Line 149" in texts[-1]
        assert all(f"Page {n} of {total}" in text for n, text in enumerate(texts, start=1))

    def test_canvasmaker_is_handed_the_output_and_the_page_size(self, out, stylesheet):
        calls = []

        def maker(target, **options):
            calls.append((target, options))
            return Canvas(target, **options)

        PDFMaker(out, pagesize="letter", stylesheet=stylesheet, canvasmaker=maker)
        assert calls == [(str(out), {"pagesize": (612.0, 792.0)})]

    def test_drawing_follows_a_replaced_canvas(self, out, stylesheet):
        """Replacing doc.canvas left draw_string and draw_rect on the old canvas, never saved."""
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.canvas = NumberedCanvas(str(out), pagesize=(doc.width, doc.height))
        doc.draw_string("Drawn by draw_string", 100, 400)
        doc.draw_rect(90, 390, 200, 30)
        doc.draw_paragraph("Laid by draw_paragraph")
        doc.save()
        page = read(out).pages[0]
        text = page.extract_text()
        assert "Drawn by draw_string" in text and "Laid by draw_paragraph" in text and "Page 1 of 1" in text
        assert b" re" in page.get_contents().get_data()


class TestApplyStyleColour:
    """apply_style arms the canvas for a direct drawString: colour included."""

    def test_resets_the_fill_to_black_by_default(self, doc):
        doc.canvas.setFillColorRGB(1, 1, 1)
        doc.apply_style("Small")
        assert fill_rgb(doc.canvas) == (0, 0, 0)

    def test_explicit_colour_is_applied(self, doc):
        doc.apply_style("Small", color=(0.2, 0.4, 0.6))
        assert fill_rgb(doc.canvas) == pytest.approx((0.2, 0.4, 0.6))

    def test_colour_none_keeps_the_current_fill(self, doc):
        doc.canvas.setFillColorRGB(1, 1, 1)
        doc.apply_style("Small", color=None)
        assert fill_rgb(doc.canvas) == (1, 1, 1)
