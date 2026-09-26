"""The cursor document: flow, absolute placement, pagination."""

import io
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm

from conftest import fill_rgb
from reportlab_layout import Box, PDFMaker


def read(path):
    return PdfReader(str(path))


def page_text(path, index=0):
    return read(path).pages[index].extract_text()


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
    def test_footer_is_repeated_on_every_page(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer(doc.make_paragraph("Footer text"))
        doc.draw_paragraph("Page one")
        doc.new_page()
        doc.draw_paragraph("Page two")
        doc.save()
        assert "Footer text" in page_text(out, 0)
        assert "Footer text" in page_text(out, 1)

    def test_footer_accepts_several_flowables(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer([doc.make_paragraph("Left"), doc.make_paragraph("Right side")])
        doc.save()
        text = page_text(out)
        assert "Left" in text and "Right side" in text

    def test_footer_does_not_move_the_cursor(self, doc):
        doc.set_footer(doc.make_paragraph("Footer"))
        before = doc.cursor.depth
        doc.draw_header_footer()
        assert doc.cursor.depth == before


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
