# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `repeat_rows` on `make_table` and `draw_table`: the heading rows, repeated at
  the top of every part of a table split across pages.

### Fixed

- **A block taller than the page is split, no longer lost.** With
  `auto_page_break`, `draw` sent a block that would cross the bottom margin to a
  new page even from the top of an empty one, where a new page could not help.
  That page stayed blank, and the block ran off the bottom of the next one
  without a word: 9 rows of a 50-row table, 197 of the 1,500 words of a long
  paragraph, which covered the footer on its way. A block that no page can hold
  is now split, from the cursor, over as many pages as it takes: a paragraph
  between two lines, a table between two rows. What cannot split, such as an
  image, is laid at the top of a page and logged. A block that a page can hold
  still moves to the next one whole, as before.
- **`halign` in absolute mode.** `draw_table(..., x=306, absolute=True,
  halign="center")` left the table's left edge on 306 whatever `halign` said,
  and `halign="sideways"` went through without a word: `halign` was only read
  in flow. It now says what `x` refers to, as it does for `draw_string` — the
  element's left edge, its middle or its right edge, from the width it wraps
  to — and an unknown value raises `ValueError` in every mode, as the 1.4.0
  entry said it already did. A call that passed `"center"` or `"right"` with
  `absolute=True` moves; one that passed `"left"`, or nothing, does not.

## [1.5.0] — 2026-09-26

### Added

- **TrueType font families.** `register_font_family(name, regular, bold=…,
  italic=…, bold_italic=…)` registers the faces of a family together and tells
  reportlab which is which, so that `<b>` and `<i>` switch faces inside a
  paragraph instead of failing with "Can't map determine family/bold/italic".
  The standard fonts stop at Latin-1; a TrueType font draws ł, ș, Greek or
  arrows, and embeds them so the text extracts. A face left out falls back on
  the closest one given. Registering again with the same files does nothing,
  with others raises `ValueError`, as does the name of a standard font. A face
  whose OS/2 table has no cap height, for which reportlab uses the ascent and
  `valign="cap"` sits too low, is reported in the log.
- **Images inside a line.** `inline_image(path, width, height, depth=…)` writes
  the `<img/>` tag of an image standing on the baseline, its depth below: a
  formula typeset by TeX lines up with the text around it, where reportlab's
  default puts every image 0.2 em below the baseline.
- **`InlineParagraph`**, a `Paragraph` whose lines make room for the images
  they hold. With `autoLeading`, reportlab still hangs the first baseline one
  type size below the top of the block, so a tall image on the first line stuck
  out above the paragraph and overprinted the block before it. And when a wrap
  puts an image at the head of a line, reportlab's `breakLines` gives that line
  the extent of its font, not of the image, which then overprinted the block
  below. Both are corrected; an ordinary paragraph is drawn exactly as before.
  `baselines()` gives the baseline of every line as drawn.
- **`TaggedParagraph`**, a paragraph with a tag set flush right on its last
  line, like LaTeX's `\hfill` — the points of a question, a reference. The tag
  takes a line of its own when the last one is full, and goes with the last
  part when the paragraph splits.
- **Columns.** `PDFMaker.draw_columns(story, columns=2, gap=4)` flows a story
  over columns from the cursor, fills page after page, and balances the columns
  on the last one, as LaTeX's `multicols` does, before the cursor moves under
  them. `FrameBreak` ends a column, `KeepTogether` is honoured, and a block too
  tall for a column overflows it with a warning instead of looping. A heading
  whose style asks `keepWithNext` stays with what follows it, as in a
  `SimpleDocTemplate` (`keep_with_next`). The packing behind it,
  `pack_columns` and `balanced_height`, only wraps and splits: the balancing
  trials draw nothing.

## [1.4.0] — 2026-09-26

### Added

- **`valign="cap"` for a paragraph placed with `absolute=True`.** `y` is then
  the middle of its capitals, from the cap height of the first line down to the
  baseline of the last, where `middle` centres its block. The two are not the
  same: reportlab hangs the first baseline one type size below the top of the
  block, so the capitals lie `size − (leading + cap height) / 2` below its
  middle, whatever the number of lines. Measured on the rendered ink, a
  Helvetica 15 paragraph set solid lands 2.11 pt low with `middle` and within
  0.03 pt of the target with `cap`. The line pitch is the one reportlab used,
  `autoLeading` included.

  A table or an image has no capitals, and refuses `cap` with a `ValueError`
  rather than falling back to `middle`.
- `scripts/paragraph_cap_probe.py`, which measures these figures again.

### Changed

- An unknown `valign` in absolute mode raises `ValueError`, as an unknown
  `halign` does, instead of a bare `KeyError`.

## [1.3.0] — 2026-09-26

### Fixed

- **`PDFMaker` writes into a file object.** `PDFMaker(io.BytesIO())` left the
  buffer empty, and wrote a file literally named `<_io.BytesIO object at 0x…>`
  into the working directory: the output went through `str()` before reaching
  reportlab. A binary file object — `io.BytesIO`, a file opened in `"wb"` mode,
  a Django `HttpResponse` — now goes to reportlab as it is, which is what a web
  view returning a PDF needs. It receives the whole PDF at `save()`, or at the
  end of the `with` block, and is left open, positioned after the PDF: call
  `seek(0)` before reading it back. Anything that is neither a path nor a file
  object raises `TypeError` at construction, instead of becoming a file name.
- **The header no longer overprints the first block.** `set_header` hung the
  header from the top edge of the content area. That is the line the cursor
  starts from, so the first element laid down in flow landed on top of it. The
  header now stands on that edge, in the top margin. This mirrors the footer,
  which hangs from the bottom edge into the bottom margin, and leaves the
  content area to the flow.

  Every document with a header will see it move up by its own height. Make sure
  the `top` margin is tall enough for it, and remove any offset you added to
  push the flow clear of it. The header style's `spaceAfter` sets the gap above
  the content, as the footer's `spaceBefore` already did below it.

### Added

- `OutputLike`, the type of `PDFMaker`'s first argument, and `Writable`, the
  protocol a file object has to meet: a `write` method that takes bytes.
- A warning in the log when the header is taller than the top margin, or the
  footer taller than the bottom margin, since the edge of the page cuts it off.
- The reference now documents two behaviours: `draw_table` never splits a table
  across pages, and centring an image in the flow takes `wscale` as well as
  `halign`.

## [1.2.0] — 2026-09-01

### Added

- `ShapePainter.ellipse` and `ShapePainter.circle`, with the matching
  `PDFMaker.draw_ellipse` and `PDFMaker.draw_circle`.

  Both take a **centre** and radii rather than a bounding box, to match
  `regular_polygon`: a shape defined by a centre is nearly always placed by its
  centre, and reportlab's own corner-to-corner form makes that an arithmetic
  chore at every call site. `circle` is `ellipse` with equal radii.

## [1.1.0] — 2026-09-01

### Added

- `ShapePainter.polygon` and `ShapePainter.regular_polygon`, with the matching
  `PDFMaker.draw_polygon` and `PDFMaker.draw_regular_polygon`. Arbitrary vertex
  lists, and regular polygons or star polygons inscribed in a circle.

  `regular_polygon` takes the *k* of the Schläfli symbol {n/k} as `leap`, so
  `vertices=5, leap=2` draws the five-pointed star. A `leap` sharing a divisor
  with `vertices` raises rather than silently drawing a smaller shape: {6/2}
  closes after three vertices and would trace a triangle, the hexagram needing
  two separate paths.

  `polygon` exposes `fill_mode`, which decides how a self-crossing path is
  filled — solid with the default `FILL_NON_ZERO`, hollow-centred with
  `FILL_EVEN_ODD` — and `line_join`, mitre spikes on small sharp points being
  a common surprise.

## [1.0.2] — 2026-08-25

### Fixed

- **Text no longer inherits the canvas fill colour.** `draw_string` and
  `apply_style` only set the fill when given an explicit colour, so a string
  drawn right after a filled shape came out in that shape's colour — white on
  white where the shape was a white background, which made the text vanish
  entirely. Both now default to black; pass `color=None` to deliberately keep
  the current colour.

  This is a regression against the module this package grew out of, whose
  `set_style` reset the fill to black on every call. It is worth checking any
  document produced with 1.0.0 or 1.0.1 that draws text over filled shapes.

## [1.0.1] — 2026-08-25

A documentation release. Nothing executable changed: same behaviour, same API,
same output. What changed is everything you read around it.

### Changed

- Documentation, docstrings and comments are now in English throughout — the
  reference, the changelog, the examples, the scripts and everything `help()`
  and an IDE will show you.
- `examples/attestation.py` is now `examples/certificate.py`.
- The two centring figures are replaced by a single
  `docs/img/centering.png`, reproducible from `scripts/centering_proof.py`
  alone. The one it replaced was generated from a private module and could not
  be rebuilt from this repository.

### Fixed

- Links and the figure on the package page. The 1.0.0 README used repository
  paths relative to itself, which PyPI does not resolve, so they rendered dead.
  They are absolute now.
- The version is declared in one place only, `reportlab_layout.__version__`, and
  read from there by the build. It used to be repeated in `pyproject.toml`,
  where it could drift from the tag the publish workflow checks against.

## [1.0.0] — 2026-08-25

First published release. `pdf_maker`, until now a private local module, is split
up, corrected and renamed `reportlab_layout`. The API moves to `snake_case`: a
deliberate break, with the full mapping in
[`docs/DOC.md`](docs/DOC.md#migrating-from-pdf_maker).

### Fixed

- **Vertical text centring.** The anchor was worked out as `y - height/2` with
  `height = ascent - descent`. Since the descent is negative, text dropped by
  `|descent|` too much, roughly 20% of the type size. The correct offset is
  `(ascent + descent)/2`.
- **Metrics ignoring the drawing scale.** `drawStringCenterHV` and
  `drawStringLeftCenterV` read the height at the style's nominal size while the
  text was drawn at `fontSize × size`; `drawStringCenterH` measured the width
  the same way. At `size=0.5` the centring was wrong by a factor of two, both
  horizontally and vertically. `TextMetrics` now carries the scale and every
  metric accounts for it.
- **`before` read in two different units.** It was converted to `unit` to place
  the element, but added to the cursor in points, shifting everything after it.
- **`drawParagraph`'s `valign="top"`.** The height, in points, was added to an
  ordinate expressed in `unit`. Replaced by `valign` on `draw()`, applied in
  absolute mode.
- **`drawTable`'s `addstyle`.** `TableStyle.add(list)` pushed the list on as a
  single command, which made rendering the table fail with
  `ValueError: not enough values to unpack`. Extra commands now go through
  `style=`.
- **`frameParagraph` raised `TypeError`.** It forwarded `fontsize=` to
  `getParagraph`, which took no such parameter.
- **`get_image` raised `TypeError` without a width.** The `hauteur` and `scale`
  parameters were declared but ignored. `ImageSpec.scaled` handles them and
  refuses an unconstrained request outright.
- **`drawParagraph` returned `(paragraph, box)`**, out of step with the other
  drawing methods, which broke callers unpacking four values. Every method now
  returns a `Box`.
- **`NumberedCanvas` lost the last page** when used as a standalone canvas,
  without a `DocTemplate`.
- **Canvas state leaking.** Colours, line width and rotation were not restored
  after a drawing and contaminated the next one.
- **Style collisions.** The `styles` sheet was a shared module-level object: two
  modules defining the same style name raised `KeyError` at import time.
- **Printing to standard output.** `newFrame` and `drawFrame` always wrote to
  `stdout`; the package now goes through `logging`.

### Added

- `Box`, the named 4-tuple every drawing call returns.
- `TextMetrics`, a style's metrics at a given scale, with the anchors.
- `PageGeometry` and `Cursor`, the sole owners of coordinate conversion.
- `draw_string`, one method replacing the four string-drawing variants, with
  `halign`, `valign`, `angle`, `dx`, `dy`.
- The `valign="cap"` anchor, centring on the cap box: on a short label the ink
  lands within a tenth of a point of the middle of its box, and a row of labels
  shares one baseline whatever their descenders. `TextMetrics.cap_height` rests
  on `STANDARD_CAP_HEIGHTS`, a table taken from Adobe's AFM files that reportlab
  does not expose; `scripts/cap_height_probe.py` checks it by rasterisation.
- `ImageSpec`, replacing the dictionary with French keys.
- `make_stylesheet()` and `add_style()`, for isolated stylesheets.
- Context-manager support: the output is only written if the block succeeds.
- `cursor_y`, `cursor_point`, `remaining_height`, `Cursor.fits`.
- Support for page-size names (`"A4"`, `"letter"`) and for colours given as hex
  or CSS names.
- Type annotations across the public API, with `py.typed`.
- 131 tests, run on Python 3.11 to 3.14 and reportlab 4.x and 5.x.
