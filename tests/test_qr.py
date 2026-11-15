"""QR codes: the matrix, and the drawing that has to show exactly that matrix."""

import pytest
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Path

from reportlab_layout import PDFMaker, qr_drawing, qr_matrix

PAYLOADS = ["DS3-017", "1234567890", "https://example.org/copy/2026/DS3?student=42&page=2"]


def drawn_modules(drawing, side, border):
    """Rebuild the matrix from the rectangles of the drawing's path."""
    (path,) = drawing.contents
    assert isinstance(path, Path)
    # Each run is four corners: top left, top right, bottom right, bottom left.
    points = path.points
    runs = [points[i : i + 8] for i in range(0, len(points), 8)]
    module = runs[0][1] - runs[0][5]
    size = round(side / module) - 2 * border
    grid = [[False] * size for _ in range(size)]
    for left, top, right, *_ in runs:
        row = round((side - top) / module) - border
        for column in range(round(left / module) - border, round(right / module) - border):
            grid[row][column] = True
    return grid


@pytest.mark.parametrize("payload", PAYLOADS)
def test_matrix_is_the_code_reportlabs_widget_encodes(payload):
    widget = QrCodeWidget(payload, barLevel="H")
    widget.qr.make()
    assert qr_matrix(payload) == [[bool(module) for module in row] for row in widget.qr.modules]


def test_matrix_takes_the_smallest_version_that_holds_the_payload():
    assert len(qr_matrix("DS3-017")) == 21
    assert len(qr_matrix(PAYLOADS[2])) == 4 * 6 + 17


def test_a_fixed_version_fixes_the_size():
    assert len(qr_matrix("DS3-017", version=3)) == 4 * 3 + 17


def test_matrix_carries_the_three_finder_patterns():
    matrix = qr_matrix("DS3-017")
    last = len(matrix) - 7
    for top, left in [(0, 0), (0, last), (last, 0)]:
        assert all(matrix[top + i][left] and matrix[top][left + i] for i in range(7))
        assert not matrix[top + 1][left + 1]
        assert all(matrix[top + 2 + i][left + 2 + j] for i in range(3) for j in range(3))


@pytest.mark.parametrize("level", ["L", "M", "Q", "H"])
def test_each_level_gives_its_own_code(level):
    others = {other for other in "LMQH" if other != level}
    matrix = qr_matrix("DS3-017", level=level)
    assert all(matrix != qr_matrix("DS3-017", level=other) for other in others)


@pytest.mark.parametrize("payload", PAYLOADS)
@pytest.mark.parametrize("border", [0, 2, 4])
def test_drawing_shows_exactly_the_matrix(payload, border):
    drawing = qr_drawing(payload, 100, border=border)
    assert drawn_modules(drawing, 100, border) == qr_matrix(payload)


def test_drawing_is_as_wide_as_asked_quiet_zone_included():
    drawing = qr_drawing("DS3-017", 72, border=4)
    assert (drawing.width, drawing.height) == (72, 72)
    xs = drawing.contents[0].points[0::2]
    module = 72 / (21 + 8)
    assert min(xs) == pytest.approx(4 * module)
    assert max(xs) == pytest.approx(72 - 4 * module)


def test_drawing_takes_its_colour():
    path = qr_drawing("DS3-017", 50, color="#b3261e").contents[0]
    assert path.fillColor.hexval() == "0xb3261e"
    assert path.strokeColor is None


def test_drawing_lays_on_a_page(out):
    with PDFMaker(out) as doc:
        box = doc.draw(qr_drawing("DS3-017", 60), x=100, y=500, absolute=True)
    assert (box.width, box.height) == (60, 60)
    assert out.stat().st_size > 0


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"level": "X"}, "level"),
        ({"version": 0}, "version"),
        ({"version": 41}, "version"),
    ],
)
def test_bad_settings_are_refused(arguments, message):
    with pytest.raises(ValueError, match=message):
        qr_matrix("DS3-017", **arguments)


def test_a_payload_too_long_for_its_version_is_refused():
    with pytest.raises(ValueError, match="do not fit a QR code of version 1"):
        qr_matrix("x" * 30, version=1)


@pytest.mark.parametrize(("side", "border"), [(0, 4), (-5, 4), (50, -1)])
def test_a_drawing_needs_a_side_and_a_quiet_zone(side, border):
    with pytest.raises(ValueError):
        qr_drawing("DS3-017", side, border=border)
