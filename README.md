# reportlab_layout

[![CI](https://github.com/antnardo/reportlab_layout/actions/workflows/ci.yml/badge.svg)](https://github.com/antnardo/reportlab_layout/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/reportlab_layout.svg)](https://pypi.org/project/reportlab_layout/)
[![Python](https://img.shields.io/pypi/pyversions/reportlab_layout.svg)](https://pypi.org/project/reportlab_layout/)
[![License MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/antnardo/reportlab_layout/blob/main/LICENSE)

PDF generation made easier, on top of `reportlab` and `platypus`.
A cursor that moves down the page, with the reportlab canvas still at hand to
draw exactly where you want on the page.

```bash
pip install reportlab_layout
```

```python
from reportlab_layout import PDFMaker

with PDFMaker("report.pdf", top=25, auto_page_break=True) as doc:
    doc.set_footer(doc.make_paragraph("Acme Ltd", "Right"))
    doc.draw_paragraph("Third-term report", "Heading1 Centered")
    doc.draw_centered_line(wscale=0.4)
    doc.add_space()
    doc.draw_table([["Subject", "Mark"], ["Mathematics", "17"]])

    # And right there, without switching tool or file:
    doc.draw_round_rect(doc.x_left, doc.cursor_y - 40, doc.content_width, 40, radius=6, fill="#eef4fb")
    doc.draw_string("Distinction", *doc.cursor_point, halign="left", valign="cap")
```

## The problem it solves

reportlab gives you two ways to work, and they do not mix well.

The **canvas** draws wherever you tell it, in points, from the bottom-left
corner. Precise, but you hold the current position yourself, you recompute
heights by hand, and one line inserted in the middle shifts everything after it.

**Platypus** threads *flowables* through frames and handles flow, pagination and
table splitting. But it takes over the page: to draw a box behind a paragraph at
an exact point you have to go through a `BaseDocTemplate`'s `onPage` callbacks,
which means writing the layout in two separate places and out of order.

This package keeps platypus flowables but lays them down itself, at the position
of a cursor you can read, move and question at any time. The canvas stays
reachable through `doc.canvas`. The two modes mix line by line.

```python
doc.draw_paragraph("This paragraph moves the cursor down.")  # flow
y = doc.cursor_y                                             # current position
doc.draw_rect(doc.x_left, y - 30, doc.content_width, 30)     # absolute
doc.advance(30)                                              # the cursor follows
```

## What it brings

- **An explicit cursor.** `doc.cursor.depth`, `doc.cursor_y`,
  `doc.remaining_height`, `doc.advance(h)`. No magic: you always know where you
  are on the page.
- **One method for plain text.** `draw_string(text, x, y, halign=…, valign=…,
  scale=…, angle=…)` replaces the half-dozen variants everyone ends up writing,
  and **the vertical centring is right** — including the `cap` anchor that
  centres short labels on their capitals, which is what a table cell or a badge
  actually wants. See
  [`middle` or `cap`?](https://github.com/antnardo/reportlab_layout/blob/main/docs/DOC.md#middle-or-cap)
- **One uniform return.** Every drawing call returns a `Box(x, y, width,
  height)` that unpacks as a plain 4-tuple. You know what you just laid down,
  and where.
- **The two coordinate systems kept apart.** The canvas ordinate goes up, the
  cursor depth goes down; `PageGeometry` is the only place that converts.
- **Nothing leaks.** Every drawing is wrapped in `saveState`/`restoreState`, so
  a colour or a line width never contaminates the next call.
- **Two dependencies**, reportlab and Pillow. No headless browser, no LaTeX, no
  system binary.

## How it compares

### The landscape

| Tool | Model | System deps | Licence | Status (August 2026) |
| --- | --- | --- | --- | --- |
| [reportlab](https://pypi.org/project/reportlab/) canvas | absolute, points | no | BSD | 5.0.1, very active |
| reportlab platypus | flow, flowables | no | BSD | same |
| **`reportlab_layout`** | **cursor + canvas** | **no** | **MIT** | **this package** |
| [fpdf2](https://pypi.org/project/fpdf2/) | native cursor | no | LGPL-3.0 | 2.8.8, very active |
| [pdfino](https://pypi.org/project/pdfino/) | platypus wrapper | no | MIT | 0.1.0, 2023 |
| [pdfdocument](https://pypi.org/project/pdfdocument/) | platypus wrapper | no | BSD | 4.0.0, 2020 |
| [borb](https://pypi.org/project/borb/) | object model | no | AGPL-3.0 | 3.0.9, active |
| [WeasyPrint](https://pypi.org/project/weasyprint/) | HTML + CSS | no | BSD | 69.0, very active |
| [pdfme](https://pypi.org/project/pdfme/) | document as a dict | no | MIT | 0.5.0 |
| [rst2pdf](https://pypi.org/project/rst2pdf/) | reStructuredText | no | MIT | 0.105, active |
| pypdf / pikepdf | manipulation, not generation | no | BSD / MPL | active |
| pylatex, Typst, wkhtmltopdf | markup + external engine | **yes** | various | various |

### What the community already offers

**reportlab platypus** is an excellent package, and it does far more than this
one: tables split across pages, `KeepTogether`, tables of contents, bookmarks,
multi-frame templates. If your document is a report that flows from start to
finish, **use platypus**: this package has nothing to add. The difference comes
down to one point: as soon as you need to alternate free drawing and flow in the
same gesture, platypus makes you separate the content (the *story*) from the
decoration (the `onPage` callbacks). Here, everything is written in the order it
is drawn.

**fpdf2** is the fairest comparison, because it is already a cursor model —
`set_xy`, `cell`, `multi_cell`, `ln()` — and it is excellent: an HTML subset,
tables, digital signing, a lively community. Three concrete differences. Its
licence is LGPL-3.0, which is enough to rule it out in some settings; reportlab
is BSD and this package MIT. Its rich-text engine is an HTML subset, where
reportlab's `Paragraph` takes proper markup (`<super>`, `<font>`, subscripts,
bullets) and knows how to wrap within a given width. And its cursor *is* the
API: you cannot lay a reportlab flowable in the middle of it. If you are
starting from scratch and the LGPL does not bother you, fpdf2 is a very good
choice.

**pdfino** and **pdfdocument** sit in exactly the same slot: a sequential layer
on top of platypus. They are older and simpler — `h1()`, `p()`, `table()` — and
pdfino even lets you insert a raw flowable. What neither offers: reading and
moving the cursor explicitly, absolute placement in points within the same API,
corrected font metrics, and a `Box` returned from every call. They publish a
document; this one lets you build a page. Worth noting too: pdfdocument has not
released since 2020, and pdfino is at a 0.1.0 from 2023.

**borb** offers a complete object model and reads existing PDFs as well. It is
more ambitious; it is also AGPL-3.0, a licence that reaches any service exposing
it over a network. Rule it out up front in a proprietary setting.

**WeasyPrint** produces the finest typography of the list and handles paged CSS
(`@page`, running headers, breaks). The price: you have to express the layout in
HTML and CSS, and rendering goes through a full layout engine. For a document
whose geometry is computed — a yearly planner, a slot table, a grid of photos —
describing coordinates in CSS is a detour. For an invoice or a report whose
template you already have on the web, WeasyPrint wins hands down.

**pdfme**, **rst2pdf** and **pylatex** share one stance: describe the document in
some format (a dict, reStructuredText, LaTeX) and let an engine typeset it.
Excellent when the content is the subject; unsuited when the coordinates are.
pylatex and Typst add a heavy system dependency on top.

**pypdf** and **pikepdf** do not generate documents: they merge, split and sign.
Complementary, not competing.

### In short

| What you need | Prefer |
| --- | --- |
| A report that flows on its own, tables split across pages, a table of contents | reportlab platypus |
| The template already exists in HTML/CSS | WeasyPrint |
| A simple cursor, without reportlab, and the LGPL is no problem | fpdf2 |
| To publish a simple document in a handful of calls | pdfino |
| To split, merge or sign existing PDFs | pypdf, pikepdf |
| The content is marked-up text | rst2pdf, pylatex |
| **A page whose geometry is computed, alternating flow and point-exact drawing** | **`reportlab_layout`** |

This package fills a narrow slot, but one that turns out to come up often:
documents where you know the formula that gives each element's position —
planners, grids, calendars, slot tables, contact sheets, mail merges — and where
you still want to write text as it comes, without counting points by hand.

## Going further

- [`docs/DOC.md`](https://github.com/antnardo/reportlab_layout/blob/main/docs/DOC.md) — the full API
  reference: coordinate systems, placement, styles, metrics, frames, pagination.
- [`examples/certificate.py`](https://github.com/antnardo/reportlab_layout/blob/main/examples/certificate.py) — a one-page
  document, flow and absolute drawing mixed.
- [`scripts/centering_proof.py`](https://github.com/antnardo/reportlab_layout/blob/main/scripts/centering_proof.py) — the visual
  and numeric proof of the centring.

## Compatibility

Python 3.11 to 3.14, reportlab 4.x and 5.x. The continuous-integration matrix
covers each of these eight combinations.

## Licence

MIT. reportlab is under a BSD licence, Pillow under MIT-CMU.
