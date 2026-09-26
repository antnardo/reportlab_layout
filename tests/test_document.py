"""The cursor document: flow, absolute placement, pagination."""

import io
import logging
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import paragraph as platypus_paragraph

from conftest import fill_rgb
from reportlab_layout import Box, PDFMaker, TextMetrics, add_style

#: Capitals whose ink runs from the baseline to the cap height and no further,
#: in Helvetica as in Times: no bowl overshooting, no point dipping below the
#: baseline as Times's A, N, V and W do, no punctuation.
FLAT_CAPITALS = "THE FILM KIT HELIX TIME EXIT MYTH ITEM LIFE THEME TILE"

#: The page the capitals are centred on, in points.
PAGE = (250, 120)


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
        bottom, top = ink(out)
        assert (bottom + top) / 2 == pytest.approx(PAGE[1] / 2, abs=0.1)

    @pytest.mark.ink
    def test_middle_leaves_capitals_set_solid_low(self, out, ink):
        """The flaw "cap" corrects: reportlab keeps a whole type size above the first baseline."""
        metrics = centre_on_page(out, "Helvetica", 15, 15, valign="middle")
        bottom, top = ink(out)
        sink = (metrics.font_size - metrics.cap_height) / 2
        assert (bottom + top) / 2 == pytest.approx(PAGE[1] / 2 - sink, abs=0.1)

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
            doc.draw_paragraph("Une ligne parmi beaucoup d'autres.")
        doc.save()
        assert len(read(out).pages) > 1

    def test_page_break_false_keeps_everything_on_one_page(self, out, stylesheet):
        doc = PDFMaker(out, auto_page_break=True, stylesheet=stylesheet)
        for _ in range(80):
            doc.draw_paragraph("Une ligne parmi beaucoup d'autres.", page_break=False)
        doc.save()
        assert len(read(out).pages) == 1


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
        assert lines["HEADER TEXT"] - lines["FIRST BLOCK"] == pytest.approx(first.height)

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
        assert lines["HEADER TEXT"] - lines["FIRST BLOCK"] == pytest.approx(first.height + 6)

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

    def test_bands_that_fit_their_margins_log_nothing(self, out, stylesheet, caplog):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_header(doc.make_paragraph("HEADER TEXT"))
        doc.set_footer(doc.make_paragraph("FOOTER TEXT"))
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.document"):
            doc.save()
        assert caplog.records == []


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
