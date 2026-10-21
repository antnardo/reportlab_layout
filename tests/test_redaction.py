"""A whole PDF written again without what a predicate refuses, and nothing of it left behind."""

import re
import shutil
import subprocess

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import StreamObject
from reportlab.pdfgen import canvas as pdfcanvas

from reportlab_layout import pdf_elements, redact_pdf

ZONE = (47, 180, 400, 230)  # from just after "Dear" to the right edge, around the first line


def in_zone(element):
    x1, y1, x2, y2 = element.box
    return not (x2 <= ZONE[0] or x1 >= ZONE[2] or y2 <= ZONE[1] or y1 >= ZONE[3])


def keep(element):
    return not in_zone(element)


@pytest.fixture
def letter(tmp_path):
    """Two pages of different sizes, a secret in the zone of each, and a catalogue full of it."""
    path = tmp_path / "letter.pdf"
    canvas = pdfcanvas.Canvas(str(path), pagesize=(400, 300))
    for size, secret in (((400, 300), "SECRETONE"), ((500, 400), "SECRETTWO")):
        canvas.setPageSize(size)
        canvas.setFont("Helvetica", 12)
        canvas.drawString(20, 200, f"Dear {secret}, hello")
        canvas.drawString(20, 100, "Regards")
        canvas.showPage()
    canvas.save()
    writer = PdfWriter(clone_from=str(path))
    writer.add_metadata({"/Title": "SECRETONE", "/Author": "SECRETTWO"})
    writer.add_attachment("secret.txt", b"SECRETONE in an attachment")
    writer.add_annotation(0, _note("SECRETONE in a note"))
    writer.write(path)
    return path


def _note(contents):
    from pypdf.annotations import Text

    return Text(text=contents, rect=(20, 20, 40, 40))


def everything(path):
    reader = PdfReader(path)
    blob = b""
    for number in range(1, int(reader.trailer["/Size"])):
        obj = reader.get_object(number)
        blob += obj.get_data() if isinstance(obj, StreamObject) else repr(obj).encode()
    return blob + repr(reader.trailer).encode()


def test_every_page_comes_out_without_what_keep_refuses(tmp_path, letter):
    out = tmp_path / "out.pdf"
    redact_pdf(letter, out, keep)
    reader = PdfReader(out)
    assert [(float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages] == [
        (400, 300),
        (500, 400),
    ]
    for index in (0, 1):
        assert "".join(e.text for e in pdf_elements(out, index)) == "DearRegards"
        assert not any(in_zone(e) for e in pdf_elements(out, index))


def test_gives_back_what_it_took_out_page_by_page(tmp_path, letter):
    removed = redact_pdf(letter, tmp_path / "out.pdf", keep)
    by_page = ["".join(e.text for e in removed if e.page == page) for page in (0, 1)]
    assert by_page == [" SECRETONE, hello", " SECRETTWO, hello"]


def test_nothing_of_the_source_catalogue_comes_along(tmp_path, letter):
    out = tmp_path / "out.pdf"
    redact_pdf(letter, out, keep)
    assert b"SECRET" in everything(letter)
    assert b"SECRET" not in everything(out)
    assert PdfReader(out).pages[0].get("/Annots") is None


def test_no_word_in_the_zone_reaches_another_reader(tmp_path, letter):
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext (poppler) is not installed")
    out = tmp_path / "out.pdf"
    redact_pdf(letter, out, keep)
    xml = subprocess.run(
        ["pdftotext", "-bbox", str(out), "-"], capture_output=True, text=True, check=True
    ).stdout
    words = re.findall(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)<', xml)
    assert {w[4] for w in words} == {"Dear", "Regards"}
    for page in xml.split("<page")[1:]:
        height = float(re.search(r'height="([\d.]+)"', page).group(1))
        for x1, top, x2, bottom, _ in re.findall(
            r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)<', page
        ):
            word = (float(x1), height - float(bottom), float(x2), height - float(top))
            assert not (
                word[2] > ZONE[0] + 1
                and word[0] < ZONE[2] - 1
                and word[3] > ZONE[1] + 1
                and word[1] < ZONE[3] - 1
            )


def test_the_source_may_be_bytes_or_a_file(tmp_path, letter):
    data = letter.read_bytes()
    first = redact_pdf(data, tmp_path / "a.pdf", keep)
    with letter.open("rb") as handle:
        second = redact_pdf(handle, tmp_path / "b.pdf", keep)
    assert first == second
